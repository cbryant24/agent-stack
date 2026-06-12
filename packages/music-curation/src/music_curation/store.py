from __future__ import annotations

from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from agent_runtime.diagnostics import DiagnosticReport, RemediationOutcome
from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query, record_memory_write

from music_curation.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_SOUND_REFERENCE,
    MEMORY_TYPE_TASTE,
    MEMORY_TYPE_TEMPLATE,
    REACTION_PENDING,
    STATUS_PENDING,
)
from music_curation.models import (
    Generation,
    GenerationRef,
    SoundReference,
    TasteLesson,
    Template,
)


def _memory_type_filter(memory_type: str) -> Filter:
    return Filter(must=[FieldCondition(key="memory_type", match=MatchValue(value=memory_type))])


def _and_filter(*conditions: FieldCondition) -> Filter:
    return Filter(must=list(conditions))


class MusicCurationStore:
    """Owns music_curation_memory. Routes the four memory types to the same
    Qdrant collection, discriminated by the memory_type payload field.

    Uses MemoryStore's low-level surface (upsert_raw_points, set_payload,
    query_by_vector, retrieve_points) so it controls the payload schema.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection(self._collection, vector_size=1024)

    # ── Writes ────────────────────────────────────────────────────────────────

    async def upsert_generation(self, gen: Generation) -> None:
        """Embed the style_field and upsert as a generation point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([gen.style_field], input_type="document")
        payload = gen.to_payload()
        point = PointStruct(id=gen.entry_id, vector=vector, payload=payload)
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_generations_bulk(self, gens: list[Generation]) -> None:
        """Batch-embed and upsert multiple generations."""
        if not gens:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed([g.style_field for g in gens], input_type="document")
        points = [
            PointStruct(id=g.entry_id, vector=v, payload=g.to_payload())
            for g, v in zip(gens, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def upsert_template(self, tmpl: Template) -> None:
        """Embed the descriptor and upsert as a template point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([tmpl.descriptor], input_type="document")
        point = PointStruct(id=tmpl.entry_id, vector=vector, payload=tmpl.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_templates_bulk(self, tmpls: list[Template]) -> None:
        if not tmpls:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed([t.descriptor for t in tmpls], input_type="document")
        points = [
            PointStruct(id=t.entry_id, vector=v, payload=t.to_payload())
            for t, v in zip(tmpls, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def upsert_taste(self, lesson: TasteLesson) -> None:
        """Embed the statement and upsert as a taste point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([lesson.statement], input_type="document")
        point = PointStruct(id=lesson.entry_id, vector=vector, payload=lesson.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_taste_bulk(self, lessons: list[TasteLesson]) -> None:
        if not lessons:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed([l.statement for l in lessons], input_type="document")
        points = [
            PointStruct(id=l.entry_id, vector=v, payload=l.to_payload())
            for l, v in zip(lessons, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def upsert_sound_ref(self, ref: SoundReference) -> None:
        """Embed the description and upsert as a sound_reference point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([ref.description], input_type="document")
        point = PointStruct(id=ref.entry_id, vector=vector, payload=ref.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def update_generation_reaction(
        self,
        entry_id: str,
        reaction: str,
        *,
        notes: str | None = None,
        context: str | None = None,
        rating: int | None = None,
        reacted_at: str | None = None,
    ) -> None:
        """Update reaction, status, and optional feedback on a stored generation point.
        Does NOT re-embed (style_field is unchanged).

        notes   — action-oriented (what to change next time)
        context — reasoning-oriented (why the user reacted as they did; retrieval signal)
        rating  — 1-5 intensity within a reaction tier
        """
        from datetime import UTC, datetime
        from music_curation.constants import STATUS_COMPLETE
        payload: dict[str, Any] = {
            "reaction": reaction,
            "status": STATUS_COMPLETE,
            "reacted_at": reacted_at or datetime.now(UTC).isoformat(),
        }
        if notes is not None:
            payload["notes"] = notes
        if context is not None:
            payload["context"] = context
        if rating is not None:
            payload["rating"] = rating
        await self._store.set_payload(self._collection, entry_id, payload)

    # ── Searches ─────────────────────────────────────────────────────────────

    async def search_generations(
        self,
        query: str,
        *,
        exclude_pending: bool = True,
        limit: int = 10,
    ) -> list[tuple[str, float, Generation]]:
        """Search generation entries. Returns (entry_id, score, Generation) tuples."""
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION))
        ]
        if exclude_pending:
            conditions.append(
                FieldCondition(key="status", match=MatchValue(value="complete"))
            )
        filters = Filter(must=conditions)

        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(
            self._collection, qv, limit=limit, filters=filters
        )
        record_memory_query(self._collection, query, len(raw))
        return [
            (pid, score, Generation.from_payload(payload))
            for pid, score, payload in raw
        ]

    async def search_templates(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[tuple[str, float, Template]]:
        filters = _memory_type_filter(MEMORY_TYPE_TEMPLATE)
        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(
            self._collection, qv, limit=limit, filters=filters
        )
        record_memory_query(self._collection, query, len(raw))
        return [(pid, score, Template.from_payload(payload)) for pid, score, payload in raw]

    async def search_taste(
        self,
        query: str,
        *,
        confirmed_only: bool = True,
        valence: str | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, TasteLesson]]:
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TASTE))
        ]
        if confirmed_only:
            conditions.append(
                FieldCondition(key="confirmed", match=MatchValue(value=True))
            )
        if valence is not None:
            conditions.append(
                FieldCondition(key="valence", match=MatchValue(value=valence))
            )
        filters = Filter(must=conditions)

        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(
            self._collection, qv, limit=limit, filters=filters
        )
        record_memory_query(self._collection, query, len(raw))
        return [(pid, score, TasteLesson.from_payload(payload)) for pid, score, payload in raw]

    async def search_sound_refs(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[tuple[str, float, SoundReference]]:
        filters = _memory_type_filter(MEMORY_TYPE_SOUND_REFERENCE)
        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(
            self._collection, qv, limit=limit, filters=filters
        )
        record_memory_query(self._collection, query, len(raw))
        return [(pid, score, SoundReference.from_payload(payload)) for pid, score, payload in raw]

    async def get_generation(self, entry_id: str) -> Generation | None:
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        record = records[0]
        payload = record.payload or {}
        if payload.get("memory_type") != MEMORY_TYPE_GENERATION:
            return None
        return Generation.from_payload(payload)

    async def list_pending(self) -> list[Generation]:
        """Return all generations with status=pending (unseen Suno reactions)."""
        conditions = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION)),
            FieldCondition(key="status", match=MatchValue(value=STATUS_PENDING)),
        ]
        filters = Filter(must=conditions)
        records, _ = await self._store._client.scroll(
            collection_name=self._collection,
            scroll_filter=filters,
            limit=100,
            with_payload=True,
        )
        return [Generation.from_payload(r.payload or {}) for r in records]

    async def get_chain(self, chain_root_id: str) -> list[Generation]:
        """Return all generations in a chain, ordered by created_at."""
        conditions = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION)),
            FieldCondition(key="chain_root_id", match=MatchValue(value=chain_root_id)),
        ]
        filters = Filter(must=conditions)
        records, _ = await self._store._client.scroll(
            collection_name=self._collection,
            scroll_filter=filters,
            limit=100,
            with_payload=True,
        )
        gens = [Generation.from_payload(r.payload or {}) for r in records]
        return sorted(gens, key=lambda g: g.created_at)

    def to_generation_ref(self, gen: Generation) -> GenerationRef:
        return GenerationRef(
            entry_id=gen.entry_id,
            style_field_excerpt=gen.style_field[:100],
            reaction=gen.reaction,
            suggested_track_title=gen.suggested_track_title,
        )

    async def migrate_approved_to_liked(self) -> int:
        """One-shot migration for the `approved` → `liked` reaction rename.

        Scans music_curation_memory for points with payload.reaction == "approved"
        and rewrites each to "liked" via set_payload (no re-embedding). Idempotent:
        re-running finds zero matches once complete. IRREVERSIBLE — there is no
        liked → approved rollback. Returns the number of points migrated.
        """
        filters = Filter(must=[
            FieldCondition(key="reaction", match=MatchValue(value="approved")),
        ])
        migrated = 0
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            for r in records:
                await self._store.set_payload(
                    self._collection, str(r.id), {"reaction": "liked"}
                )
                migrated += 1
            if offset is None:
                break
        return migrated

    # ── Remediation (orchestrator diagnostics delegation) ──────────────────────

    async def remediate(self, report: DiagnosticReport) -> RemediationOutcome:
        """Execute a diagnostic report's remediation spec against this store's own
        collection — the music-curation side of the orchestrator's diagnose →
        delegate seam. The orchestrator diagnoses but never writes to Qdrant; this
        method performs the write under music-curation's ownership, with the report
        (its status transitions + evidence) as the audit record.

        Implemented as a filter-parameterized generalization of
        migrate_approved_to_liked(): scroll the points matching `spec.match` and
        `set_payload(spec.set)` on each (no re-embedding, idempotent). Returns the
        number of points rewritten in the outcome detail.

        Validates before writing and *refuses* (returning status="open", so a report
        delegate_remediation already flipped to "delegated" lands back as a manual
        work order rather than stranding at "delegated") when the report isn't for
        this collection, carries no spec, or the spec is unsupported/malformed."""
        if report.collection != self._collection:
            return RemediationOutcome(
                status="open",
                detail=(
                    f"refused: report targets '{report.collection}', but this store owns "
                    f"'{self._collection}'"
                ),
            )
        spec = report.remediation
        if spec is None:
            return RemediationOutcome(
                status="open", detail="refused: report carries no remediation spec"
            )
        if spec.kind != "retag":
            return RemediationOutcome(
                status="open",
                detail=f"refused: unsupported remediation kind '{spec.kind}' (only 'retag')",
            )
        if not spec.match or not spec.set:
            return RemediationOutcome(
                status="open",
                detail="refused: malformed retag spec (both 'match' and 'set' are required)",
            )

        filters = Filter(
            must=[
                FieldCondition(key=key, match=MatchValue(value=value))
                for key, value in spec.match.items()
            ]
        )
        rewritten = 0
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=False,
            )
            for r in records:
                await self._store.set_payload(self._collection, str(r.id), spec.set)
                rewritten += 1
            if offset is None:
                break
        return RemediationOutcome(
            status="fixed",
            detail=f"re-tagged {rewritten} point(s): {spec.match} → {spec.set}",
        )

    async def count_by_reaction(self, reaction: str) -> int:
        """Count generation points with a given reaction value (used for migration verification)."""
        filters = Filter(must=[
            FieldCondition(key="reaction", match=MatchValue(value=reaction)),
        ])
        total = 0
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=False,
            )
            total += len(records)
            if offset is None:
                break
        return total
