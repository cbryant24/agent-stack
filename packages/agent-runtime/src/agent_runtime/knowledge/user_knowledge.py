from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, PointStruct

from agent_runtime.memory.store import MemoryStore

logger = logging.getLogger(__name__)

COLLECTION_NAME = "user_knowledge"
_DRAFT_EXPIRY_DAYS = 7

# Confidence level ordering for confidence_min filtering.
_CONFIDENCE_LEVELS: dict[str, list[str]] = {
    "low": ["low", "medium", "high"],
    "medium": ["medium", "high"],
    "high": ["high"],
}

# superseded_by is stored as "" for active entries and as the superseding entry_id
# when the entry has been replaced. This sentinel makes Qdrant filtering simple
# (MatchValue(value="") for current_only) without requiring null/missing-field handling.
_ACTIVE_SENTINEL = ""


@dataclass
class Draft:
    draft_id: str
    statement: str
    domain: str
    source_type: str
    topic_tags: list[str]
    source_ref: str | None
    examples: list[str]
    confidence: str
    created_at: datetime


@dataclass
class KnowledgeEntry:
    entry_id: str
    statement: str
    domain: str
    topic_tags: list[str]
    source_type: str
    source_ref: str | None
    examples: list[str]
    created_at: datetime
    updated_at: datetime
    confidence: str
    superseded_by: str | None  # None = active; UUID string = replaced by that entry


@dataclass
class KnowledgeHit:
    score: float
    statement: str
    domain: str
    topic_tags: list[str]
    source_type: str
    confidence: str
    source_ref: str | None
    entry_id: str


def _draft_to_dict(d: Draft) -> dict[str, Any]:
    return {
        "draft_id": d.draft_id,
        "statement": d.statement,
        "domain": d.domain,
        "source_type": d.source_type,
        "topic_tags": d.topic_tags,
        "source_ref": d.source_ref,
        "examples": d.examples,
        "confidence": d.confidence,
        "created_at": d.created_at.isoformat(),
    }


def _draft_from_dict(data: dict[str, Any]) -> Draft:
    return Draft(
        draft_id=data["draft_id"],
        statement=data["statement"],
        domain=data["domain"],
        source_type=data["source_type"],
        topic_tags=data.get("topic_tags", []),
        source_ref=data.get("source_ref"),
        examples=data.get("examples", []),
        confidence=data.get("confidence", "high"),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def _entry_from_payload(point_id: str, payload: dict[str, Any]) -> KnowledgeEntry:
    raw_superseded = payload.get("superseded_by", _ACTIVE_SENTINEL)
    return KnowledgeEntry(
        entry_id=payload.get("entry_id", point_id),
        statement=payload.get("statement", ""),
        domain=payload.get("domain", "general"),
        topic_tags=payload.get("topic_tags", []),
        source_type=payload.get("source_type", "manual"),
        source_ref=payload.get("source_ref") or None,
        examples=payload.get("examples", []),
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        confidence=payload.get("confidence", "high"),
        superseded_by=raw_superseded if raw_superseded else None,
    )


def _hit_from_raw(point_id: str, score: float, payload: dict[str, Any]) -> KnowledgeHit:
    return KnowledgeHit(
        score=score,
        statement=payload.get("statement", ""),
        domain=payload.get("domain", "general"),
        topic_tags=payload.get("topic_tags", []),
        source_type=payload.get("source_type", "manual"),
        confidence=payload.get("confidence", "high"),
        source_ref=payload.get("source_ref") or None,
        entry_id=payload.get("entry_id", point_id),
    )


class UserKnowledgeStore:
    """Runtime-owned wrapper for the user_knowledge Qdrant collection.

    This is the ONLY authorized writer to the user_knowledge collection.
    Other code may query the collection via UserKnowledgeStore.search() or
    directly via MemoryStore.query_by_vector(). What it must NOT do is call
    MemoryStore.upsert_points() or upsert_raw_points() against user_knowledge
    directly — those paths bypass the draft/confirm workflow and the schema
    contract maintained here.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name

    def _draft_dir(self) -> Path:
        from agent_runtime.config import get_config
        return get_config().agent_data_dir / "drafts" / "user_knowledge"

    def _draft_path(self, draft_id: str) -> Path:
        return self._draft_dir() / f"{draft_id}.json"

    async def ensure_collection(self) -> None:
        """Idempotent — creates the collection if it does not exist."""
        await self._store.ensure_collection(self._collection, vector_size=1024)

    async def propose_entry(
        self,
        statement: str,
        domain: str,
        source_type: str,
        *,
        topic_tags: list[str] | None = None,
        source_ref: str | None = None,
        examples: list[str] | None = None,
        confidence: str = "high",
    ) -> Draft:
        """Create a Draft and persist it to disk. Does NOT write to Qdrant."""
        draft = Draft(
            draft_id=str(uuid.uuid4()),
            statement=statement,
            domain=domain,
            source_type=source_type,
            topic_tags=topic_tags or [],
            source_ref=source_ref,
            examples=examples or [],
            confidence=confidence,
            created_at=datetime.now(UTC),
        )
        draft_dir = self._draft_dir()
        draft_dir.mkdir(parents=True, exist_ok=True)
        self._draft_path(draft.draft_id).write_text(
            json.dumps(_draft_to_dict(draft)), encoding="utf-8"
        )
        return draft

    async def confirm_entry(self, draft_id: str) -> str:
        """Embed the draft statement, upsert to Qdrant, delete the draft. Returns entry_id."""
        draft_path = self._draft_path(draft_id)
        data = json.loads(draft_path.read_text(encoding="utf-8"))
        draft = _draft_from_dict(data)

        await self.ensure_collection()

        entry_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        embedder = self._store.embedding_client
        [vector] = await embedder.embed([draft.statement], input_type="document")

        payload: dict[str, Any] = {
            "statement": draft.statement,
            "domain": draft.domain,
            "topic_tags": draft.topic_tags,
            "source_type": draft.source_type,
            "source_ref": draft.source_ref,
            "examples": draft.examples,
            "created_at": draft.created_at.isoformat(),
            "updated_at": now,
            "confidence": draft.confidence,
            "superseded_by": _ACTIVE_SENTINEL,
            "entry_id": entry_id,
        }
        point = PointStruct(id=entry_id, vector=vector, payload=payload)
        await self._store.upsert_raw_points(self._collection, [point])

        draft_path.unlink()
        return entry_id

    async def reject_entry(self, draft_id: str) -> None:
        """Delete a draft without writing to Qdrant."""
        draft_path = self._draft_path(draft_id)
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft not found: {draft_id}")
        draft_path.unlink()

    async def list_drafts(self) -> list[Draft]:
        """Return all active drafts, pruning any older than 7 days.

        Corrupt or unreadable draft files are skipped with a warning; they are
        NOT auto-deleted so they can be inspected manually. The 7-day expiry
        clock will eventually remove them.
        """
        draft_dir = self._draft_dir()
        if not draft_dir.exists():
            return []

        now = datetime.now(UTC)
        expiry_cutoff = now - timedelta(days=_DRAFT_EXPIRY_DAYS)

        drafts: list[Draft] = []
        for path in sorted(draft_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                draft = _draft_from_dict(data)
            except Exception:
                logger.warning("Skipping unreadable draft file (preserved for inspection): %s", path)
                continue

            if draft.created_at.replace(tzinfo=UTC) < expiry_cutoff if draft.created_at.tzinfo is None else draft.created_at < expiry_cutoff:
                path.unlink()
                continue

            drafts.append(draft)

        return drafts

    async def bulk_load_verified(
        self,
        entries: list[dict[str, Any]],
        source_ref: str,
    ) -> list[str]:
        """Bulk-ingest human-curated entries directly to Qdrant (no propose/confirm cycle).

        `source_ref` is REQUIRED — it is the curation provenance for every entry in the batch.
        Raises ValueError if source_ref is empty.
        """
        if not source_ref:
            raise ValueError("source_ref is required for bulk_load_verified")

        await self.ensure_collection()

        statements = [e["statement"] for e in entries]
        vectors = await self._store.embedding_client.embed(statements, input_type="document")

        now = datetime.now(UTC).isoformat()
        entry_ids: list[str] = []
        points: list[PointStruct] = []

        for entry, vector in zip(entries, vectors):
            entry_id = str(uuid.uuid4())
            entry_ids.append(entry_id)
            payload: dict[str, Any] = {
                "statement": entry["statement"],
                "domain": entry.get("domain", "general"),
                "topic_tags": entry.get("topic_tags", []),
                "source_type": entry.get("source_type", "manual"),
                "source_ref": source_ref,
                "examples": entry.get("examples", []),
                "created_at": entry.get("created_at", now),
                "updated_at": now,
                "confidence": entry.get("confidence", "high"),
                "superseded_by": _ACTIVE_SENTINEL,
                "entry_id": entry_id,
            }
            points.append(PointStruct(id=entry_id, vector=vector, payload=payload))

        await self._store.upsert_raw_points(self._collection, points)
        return entry_ids

    async def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        current_only: bool = True,
        limit: int = 10,
        confidence_min: str | None = None,
    ) -> list[KnowledgeHit]:
        """Semantic search over user knowledge.

        current_only=True (default) excludes entries where superseded_by is set.
        """
        conditions: list[FieldCondition] = []

        if current_only:
            conditions.append(
                FieldCondition(key="superseded_by", match=MatchValue(value=_ACTIVE_SENTINEL))
            )

        if domain is not None:
            conditions.append(
                FieldCondition(key="domain", match=MatchValue(value=domain))
            )

        if confidence_min is not None:
            allowed = _CONFIDENCE_LEVELS.get(confidence_min, ["high"])
            conditions.append(
                FieldCondition(key="confidence", match=MatchAny(any=allowed))
            )

        filters = Filter(must=conditions) if conditions else None

        embedder = self._store.embedding_client
        [query_vector] = await embedder.embed([query], input_type="query")

        raw = await self._store.query_by_vector(
            self._collection, query_vector, limit=limit, filters=filters
        )
        return [_hit_from_raw(pid, score, payload) for pid, score, payload in raw]

    async def supersede(
        self,
        old_entry_id: str,
        new_statement: str,
        **fields: Any,
    ) -> str:
        """Write a new entry and mark the old one as superseded by it.

        Returns the new entry_id. Additional keyword args override fields from the
        new entry (domain, source_type, confidence, topic_tags, source_ref, examples).
        """
        await self.ensure_collection()

        new_entry_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        embedder = self._store.embedding_client
        [vector] = await embedder.embed([new_statement], input_type="document")

        payload: dict[str, Any] = {
            "statement": new_statement,
            "domain": fields.get("domain", "general"),
            "topic_tags": fields.get("topic_tags", []),
            "source_type": fields.get("source_type", "manual"),
            "source_ref": fields.get("source_ref"),
            "examples": fields.get("examples", []),
            "created_at": now,
            "updated_at": now,
            "confidence": fields.get("confidence", "high"),
            "superseded_by": _ACTIVE_SENTINEL,
            "entry_id": new_entry_id,
        }
        point = PointStruct(id=new_entry_id, vector=vector, payload=payload)
        await self._store.upsert_raw_points(self._collection, [point])

        # Link old entry to new
        await self._store.set_payload(
            self._collection, old_entry_id, {"superseded_by": new_entry_id}
        )
        return new_entry_id

    async def get_entry(self, entry_id: str) -> KnowledgeEntry | None:
        """Direct fetch by ID. Returns superseded entries too (for chain walking)."""
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        record = records[0]
        return _entry_from_payload(str(record.id), record.payload or {})
