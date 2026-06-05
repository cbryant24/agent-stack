"""VoiceoverDirectionStore — wrapper over agent-runtime's MemoryStore.

Owns the `voiceover_direction_memory` Qdrant collection, routing the two memory
types (`take`, `direction_lesson`) to it discriminated by the `memory_type`
payload field. Also owns the voice registry (a local JSON file via
`VoiceRegistry`) so the store is the single persistence surface. Mirrors
MusicCurationStore's use of MemoryStore's low-level surface (`embedding_client`,
`upsert_raw_points`, `set_payload`, `query_by_vector`, `retrieve_points`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from voiceover_direction.constants import (
    COLLECTION_NAME,
    EMBEDDING_DIM,
    MEMORY_TYPE_DIRECTION_LESSON,
    MEMORY_TYPE_TAKE,
    STATUS_COMPLETE,
    STATUS_PENDING,
)
from voiceover_direction.models import DirectionLesson, Take, VoiceProfile
from voiceover_direction.voice_registry import VoiceRegistry


def _memory_type_filter(memory_type: str) -> Filter:
    return Filter(must=[FieldCondition(key="memory_type", match=MatchValue(value=memory_type))])


class VoiceoverDirectionStore:
    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = COLLECTION_NAME,
        voice_registry: VoiceRegistry | None = None,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name
        self._voices = voice_registry or VoiceRegistry()

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection(self._collection, vector_size=EMBEDDING_DIM)

    # ── Take writes ──────────────────────────────────────────────────────────

    async def upsert_take(self, take: Take) -> None:
        """Embed the take text and upsert as a take point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([take.text], input_type="document")
        point = PointStruct(id=take.entry_id, vector=vector, payload=take.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_takes_bulk(self, takes: list[Take]) -> None:
        if not takes:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed([t.text for t in takes], input_type="document")
        points = [
            PointStruct(id=t.entry_id, vector=v, payload=t.to_payload())
            for t, v in zip(takes, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def update_take_reaction(
        self,
        entry_id: str,
        reaction: str,
        *,
        rating: int | None = None,
        notes: str | None = None,
        context: str | None = None,
        reacted_at: str | None = None,
    ) -> None:
        """Record a reaction on a stored take, flipping status pending → complete.
        Does NOT re-embed (the take text is unchanged). Called by `report` (Step 4).
        """
        payload: dict[str, Any] = {
            "reaction": reaction,
            "status": STATUS_COMPLETE,
            "reacted_at": reacted_at or datetime.now(UTC).isoformat(),
        }
        if rating is not None:
            payload["rating"] = rating
        if notes is not None:
            payload["notes"] = notes
        if context is not None:
            payload["context"] = context
        await self._store.set_payload(self._collection, entry_id, payload)

    async def get_take(self, entry_id: str) -> Take | None:
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        return Take.from_payload(records[0].payload)

    async def search_takes(
        self,
        query: str,
        *,
        section_id: str | None = None,
        exclude_pending: bool = True,
        limit: int = 10,
    ) -> list[tuple[str, float, Take]]:
        """Search take entries. Returns (entry_id, score, Take) tuples."""
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TAKE))
        ]
        if exclude_pending:
            conditions.append(FieldCondition(key="status", match=MatchValue(value=STATUS_COMPLETE)))
        if section_id is not None:
            conditions.append(FieldCondition(key="section_id", match=MatchValue(value=section_id)))
        filters = Filter(must=conditions)

        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(self._collection, qv, limit=limit, filters=filters)
        record_memory_query(self._collection, query, len(raw))
        return [(pid, score, Take.from_payload(payload)) for pid, score, payload in raw]

    async def latest_take_for_section(self, project_id: str, section_id: str) -> Take | None:
        """Return the most recent take for a section, or None if it has none.

        Section-scoped lineage is continuous, so pending takes are included (no status
        filter). Enumerated via a filter-only scroll with offset pagination — no vector
        (similarity against a placeholder is undefined) and no fixed limit (a truncated
        page would let the next take parent off the wrong node).
        """
        filters = Filter(
            must=[
                FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TAKE)),
                FieldCondition(key="project_id", match=MatchValue(value=project_id)),
                FieldCondition(key="section_id", match=MatchValue(value=section_id)),
            ]
        )
        takes: list[Take] = []
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            takes.extend(Take.from_payload(r.payload or {}) for r in records)
            if offset is None:
                break
        # created_at is ISO-8601, so lexicographic max == chronological max.
        return max(takes, key=lambda t: t.created_at) if takes else None

    async def list_pending(self) -> list[Take]:
        """Return all pending takes (generated, awaiting a reaction), oldest first.

        Filter-only scroll with offset pagination — no vector, no fixed-limit truncation.
        `status` is derived in Take.to_payload, so the status==pending filter is exact.
        """
        filters = Filter(
            must=[
                FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TAKE)),
                FieldCondition(key="status", match=MatchValue(value=STATUS_PENDING)),
            ]
        )
        takes: list[Take] = []
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            takes.extend(Take.from_payload(r.payload or {}) for r in records)
            if offset is None:
                break
        return sorted(takes, key=lambda t: t.created_at)

    # ── Direction-lesson writes ──────────────────────────────────────────────

    async def upsert_lesson(self, lesson: DirectionLesson) -> None:
        """Embed the statement and upsert as a direction_lesson point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([lesson.statement], input_type="document")
        point = PointStruct(id=lesson.entry_id, vector=vector, payload=lesson.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_lessons_bulk(self, lessons: list[DirectionLesson]) -> None:
        if not lessons:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed([le.statement for le in lessons], input_type="document")
        points = [
            PointStruct(id=le.entry_id, vector=v, payload=le.to_payload())
            for le, v in zip(lessons, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def search_lessons(
        self,
        query: str,
        *,
        confirmed_only: bool = True,
        scope: str | None = None,
        valence: str | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float, DirectionLesson]]:
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_DIRECTION_LESSON))
        ]
        if confirmed_only:
            conditions.append(FieldCondition(key="confirmed", match=MatchValue(value=True)))
        if scope is not None:
            conditions.append(FieldCondition(key="scope", match=MatchValue(value=scope)))
        if valence is not None:
            conditions.append(FieldCondition(key="valence", match=MatchValue(value=valence)))
        filters = Filter(must=conditions)

        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(self._collection, qv, limit=limit, filters=filters)
        record_memory_query(self._collection, query, len(raw))
        return [
            (pid, score, DirectionLesson.from_payload(payload)) for pid, score, payload in raw
        ]

    # ── Voice registry (delegated to the JSON-backed registry the store owns) ─

    def sync_voices(self, voices: list[VoiceProfile]) -> None:
        """Replace the whole local voice registry (the `voice sync` write)."""
        self._voices.replace(voices)

    def list_voices(self) -> list[VoiceProfile]:
        return self._voices.list_voices()

    def get_voice(self, voice_id: str) -> VoiceProfile | None:
        return self._voices.get_voice(voice_id)
