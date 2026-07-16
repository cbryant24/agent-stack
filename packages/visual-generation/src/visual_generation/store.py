"""VisualGenerationStore — wrapper over agent-runtime's MemoryStore.

Owns the `visual_generation_memory` Qdrant collection, routing the three memory
types (`generation`, `technique_lesson`, `workflow_template`) to it discriminated
by the `memory_type` payload field. Also owns the model/LoRA registry (a local
JSON file via `ModelRegistry`) so the store is the single persistence surface.

Mirrors the sibling wrappers' use of MemoryStore's low-level surface
(`embedding_client`, `upsert_raw_points`, `set_payload`, `query_by_vector`,
`retrieve_points`, `_client.scroll`). The one genuine difference: `generation`
points are embedded via the **multimodal** surface (image+caption,
voyage-multimodal-3), so their searches must embed the text query through the
same surface (text-only) to land in the same vector space. The text-embedded
`technique_lesson`/`workflow_template` types (voyage-3-large) coexist in the
collection because every search filters by `memory_type` and never compares
vectors across types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_runtime.memory.embeddings import MultimodalInput
from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query
from qdrant_client.models import (
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchAny,
    MatchValue,
    PointStruct,
)

from visual_generation.constants import (
    COLLECTION_NAME,
    EMBEDDING_DIM,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TECHNIQUE_LESSON,
    MEMORY_TYPE_WORKFLOW_TEMPLATE,
    STATUS_COMPLETE,
    STATUS_PENDING,
    VIDEO_ASSET_EXTS,
)
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)


def _memory_type_filter(memory_type: str) -> Filter:
    return Filter(must=[FieldCondition(key="memory_type", match=MatchValue(value=memory_type))])


def _generation_input(gen: VisualGeneration) -> MultimodalInput:
    """Build the multimodal embedding input for a generation.

    Stills embed image + caption (voyage-multimodal-3). Video clips (`.mp4`/`.webm`/…)
    embed **text-only** — the caption + motion prompt — because voyage-multimodal-3
    cannot embed video; handing it an mp4 path would fail. (A later refinement could
    embed a ffmpeg-extracted middle frame; not needed for v1.)
    """
    image_path: Path | None = None
    if gen.asset_path and not gen.asset_path.lower().endswith(VIDEO_ASSET_EXTS):
        image_path = Path(gen.asset_path)
    return MultimodalInput(text=gen.caption, image_path=image_path)


class VisualGenerationStore:
    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = COLLECTION_NAME,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name
        self._models = model_registry or ModelRegistry()

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection(self._collection, vector_size=EMBEDDING_DIM)

    # ── Generation writes (multimodal: image + caption) ──────────────────────

    async def upsert_generation(self, gen: VisualGeneration) -> None:
        """Embed the image+caption and upsert as a generation point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed_multimodal(
            [_generation_input(gen)], input_type="document"
        )
        point = PointStruct(id=gen.entry_id, vector=vector, payload=gen.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_generations_bulk(self, gens: list[VisualGeneration]) -> None:
        if not gens:
            return
        embedder = self._store.embedding_client
        vectors = await embedder.embed_multimodal(
            [_generation_input(g) for g in gens], input_type="document"
        )
        points = [
            PointStruct(id=g.entry_id, vector=v, payload=g.to_payload())
            for g, v in zip(gens, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)

    async def update_generation_reaction(
        self,
        entry_id: str,
        reaction: str,
        *,
        rating: int | None = None,
        notes: str | None = None,
        context: str | None = None,
        reacted_at: str | None = None,
    ) -> None:
        """Record a reaction on a stored generation, flipping status pending →
        complete. Does NOT re-embed (the image+caption are unchanged). Called by
        `report` (Step 4)."""
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

    async def get_generation(self, entry_id: str) -> VisualGeneration | None:
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        payload = records[0].payload or {}
        if payload.get("memory_type") != MEMORY_TYPE_GENERATION:
            return None
        return VisualGeneration.from_payload(payload)

    async def search_generations(
        self,
        query: str,
        *,
        exclude_pending: bool = True,
        limit: int = 10,
    ) -> list[tuple[str, float, VisualGeneration]]:
        """Search generation entries. Returns (entry_id, score, VisualGeneration).

        The query is embedded through the **multimodal** surface (text-only) so it
        shares the voyage-multimodal-3 space of the stored image+caption vectors —
        a voyage-3-large query vector would be in a different space despite the
        matching 1024 dimension.
        """
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION))
        ]
        if exclude_pending:
            conditions.append(FieldCondition(key="status", match=MatchValue(value=STATUS_COMPLETE)))
        filters = Filter(must=conditions)

        embedder = self._store.embedding_client
        [qv] = await embedder.embed_multimodal(
            [MultimodalInput(text=query)], input_type="query"
        )
        raw = await self._store.query_by_vector(self._collection, qv, limit=limit, filters=filters)
        record_memory_query(self._collection, query, len(raw))
        return [
            (pid, score, VisualGeneration.from_payload(payload)) for pid, score, payload in raw
        ]

    async def list_pending(self) -> list[VisualGeneration]:
        """Return all pending generations (rendered, awaiting a reaction), oldest first.

        Filter-only scroll with offset pagination — no vector, no fixed-limit
        truncation. `status` is derived in to_payload, so the status==pending
        filter is exact.
        """
        filters = Filter(
            must=[
                FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION)),
                FieldCondition(key="status", match=MatchValue(value=STATUS_PENDING)),
            ]
        )
        gens = await self._scroll_generations(filters)
        return sorted(gens, key=lambda g: g.created_at)

    async def list_generations(
        self, *, project: str | None = None
    ) -> list[VisualGeneration]:
        """All generations (optionally for one project), oldest first. Filter-scroll, no
        embedding — feeds the bounded `digest` session-primer."""
        conditions = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION))
        ]
        if project:
            conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
        gens = await self._scroll_generations(Filter(must=conditions))
        return sorted(gens, key=lambda g: g.created_at)

    async def get_chain(self, chain_root_id: str) -> list[VisualGeneration]:
        """Return all generations in a chain, ordered by created_at."""
        filters = Filter(
            must=[
                FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION)),
                FieldCondition(key="chain_root_id", match=MatchValue(value=chain_root_id)),
            ]
        )
        gens = await self._scroll_generations(filters)
        return sorted(gens, key=lambda g: g.created_at)

    async def _scroll_generations(self, filters: Filter) -> list[VisualGeneration]:
        gens: list[VisualGeneration] = []
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            gens.extend(VisualGeneration.from_payload(r.payload or {}) for r in records)
            if offset is None:
                break
        return gens

    # ── Technique-lesson writes ──────────────────────────────────────────────

    async def upsert_lesson(self, lesson: TechniqueLesson) -> None:
        """Embed the statement (text) and upsert as a technique_lesson point."""
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([lesson.statement], input_type="document")
        point = PointStruct(id=lesson.entry_id, vector=vector, payload=lesson.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])

    async def upsert_lessons_bulk(self, lessons: list[TechniqueLesson]) -> None:
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
    ) -> list[tuple[str, float, TechniqueLesson]]:
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TECHNIQUE_LESSON))
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
            (pid, score, TechniqueLesson.from_payload(payload)) for pid, score, payload in raw
        ]

    async def list_lessons(
        self,
        *,
        confirmed_only: bool = True,
        scope: str | None = None,
        valence: str | None = None,
    ) -> list[TechniqueLesson]:
        """Filter-scroll (no vector) every technique_lesson point, oldest first.

        The management inverse of `search_lessons`/recall: no embedding, no fixed-limit
        truncation, and the caller reads `lesson.entry_id` to target one for removal.
        """
        conditions: list[FieldCondition] = [
            FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_TECHNIQUE_LESSON))
        ]
        if confirmed_only:
            conditions.append(FieldCondition(key="confirmed", match=MatchValue(value=True)))
        if scope is not None:
            conditions.append(FieldCondition(key="scope", match=MatchValue(value=scope)))
        if valence is not None:
            conditions.append(FieldCondition(key="valence", match=MatchValue(value=valence)))
        filters = Filter(must=conditions)

        lessons: list[TechniqueLesson] = []
        offset = None
        while True:
            records, offset = await self._store._client.scroll(
                collection_name=self._collection,
                scroll_filter=filters,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            lessons.extend(TechniqueLesson.from_payload(r.payload or {}) for r in records)
            if offset is None:
                break
        return sorted(lessons, key=lambda le: le.created_at)

    async def get_lesson(self, entry_id: str) -> TechniqueLesson | None:
        """Retrieve a technique_lesson by id.

        Returns None if no point has that id. Raises ValueError(<memory_type>) if a point
        exists but is NOT a technique_lesson — so callers can refuse to delete a generation
        or workflow_template addressed by its id.
        """
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        payload = records[0].payload or {}
        mt = payload.get("memory_type")
        if mt != MEMORY_TYPE_TECHNIQUE_LESSON:
            raise ValueError(mt or "unknown")
        return TechniqueLesson.from_payload(payload)

    async def delete_lesson(self, entry_id: str) -> None:
        """Delete the technique_lesson with `entry_id`.

        Reuses the raw qdrant client delete pattern from `prune_templates_by_name`. The
        selector is scoped to `memory_type == technique_lesson` AND this `entry_id`, so it can
        only ever remove the one targeted lesson — never a generation or workflow_template.
        """
        await self._store._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="memory_type",
                        match=MatchValue(value=MEMORY_TYPE_TECHNIQUE_LESSON),
                    ),
                    FieldCondition(key="entry_id", match=MatchValue(value=entry_id)),
                ],
            ),
        )

    # ── Workflow-template writes ─────────────────────────────────────────────

    async def prune_templates_by_name(self, names: list[str], keep_entry_id: str) -> None:
        """Delete every workflow_template point whose name is in `names`, EXCEPT the
        point with id `keep_entry_id`.

        This is the prune half of an insert-then-prune upsert (see `upsert_template`):
        the template's identity is its `name`, not its uuid `entry_id`, so registering a
        name must collapse to a single point. We insert the new point FIRST and prune
        older same-name points (including pre-existing duplicates) AFTER, so at every
        instant at least one point for the name exists.

        Crash semantics: insert-first means a crash between the insert and this prune
        leaves a transient same-name duplicate — never data loss; the next register of
        that name self-heals it. (A delete-then-insert would risk dropping the template
        outright on a crash in the gap.)
        """
        if not names:
            return
        await self._store._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="memory_type",
                        match=MatchValue(value=MEMORY_TYPE_WORKFLOW_TEMPLATE),
                    ),
                    FieldCondition(key="name", match=MatchAny(any=names)),
                ],
                must_not=[HasIdCondition(has_id=[keep_entry_id])],
            ),
        )

    async def upsert_template(self, tmpl: WorkflowTemplate) -> None:
        """Embed the descriptor (text) and upsert as a workflow_template point.

        Replace-by-name: insert the new point, then prune any older points sharing this
        name (keeping the one just written). Idempotent and self-healing for existing
        same-name duplicates.
        """
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([tmpl.descriptor], input_type="document")
        point = PointStruct(id=tmpl.entry_id, vector=vector, payload=tmpl.to_payload())
        await self._store.upsert_raw_points(self._collection, [point])
        await self.prune_templates_by_name([tmpl.name], tmpl.entry_id)

    async def upsert_templates_bulk(self, tmpls: list[WorkflowTemplate]) -> None:
        if not tmpls:
            return
        # Collapse in-batch duplicate names, keeping the last occurrence (last-write-wins),
        # so a single bulk call can't seed same-name duplicates.
        deduped = list({t.name: t for t in tmpls}.values())
        embedder = self._store.embedding_client
        vectors = await embedder.embed([t.descriptor for t in deduped], input_type="document")
        points = [
            PointStruct(id=t.entry_id, vector=v, payload=t.to_payload())
            for t, v in zip(deduped, vectors)
        ]
        await self._store.upsert_raw_points(self._collection, points)
        # Prune older same-name points, keeping the id actually written for each name.
        for t in deduped:
            await self.prune_templates_by_name([t.name], t.entry_id)

    async def search_templates(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[tuple[str, float, WorkflowTemplate]]:
        filters = _memory_type_filter(MEMORY_TYPE_WORKFLOW_TEMPLATE)
        embedder = self._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        raw = await self._store.query_by_vector(self._collection, qv, limit=limit, filters=filters)
        record_memory_query(self._collection, query, len(raw))
        return [
            (pid, score, WorkflowTemplate.from_payload(payload)) for pid, score, payload in raw
        ]

    async def get_template(self, entry_id: str) -> WorkflowTemplate | None:
        records = await self._store.retrieve_points(self._collection, [entry_id])
        if not records:
            return None
        payload = records[0].payload or {}
        if payload.get("memory_type") != MEMORY_TYPE_WORKFLOW_TEMPLATE:
            return None
        return WorkflowTemplate.from_payload(payload)

    async def get_template_by_name(self, name: str) -> WorkflowTemplate | None:
        """Exact lookup by template name (filter-scroll, no embedding) — resolves a
        spec's `workflow_ref`."""
        filters = Filter(
            must=[
                FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_WORKFLOW_TEMPLATE)),
                FieldCondition(key="name", match=MatchValue(value=name)),
            ]
        )
        records, _ = await self._store._client.scroll(
            collection_name=self._collection, scroll_filter=filters, limit=1, with_payload=True
        )
        if not records:
            return None
        return WorkflowTemplate.from_payload(records[0].payload or {})

    # ── Generation cost history (seeds the per-run GPU estimate) ──────────────

    async def recent_generation_costs(
        self, limit: int = 20, *, workflow_ref: str | None = None
    ) -> list[float]:
        """Recent non-zero per-run `cost_usd` across generations, oldest→newest.

        Feeds `gpu_tracker.estimate_per_run_cost`'s learned branch; an empty list
        (cold start) makes it fall back to the per-modality config default. When
        `workflow_ref` is given, only generations from that template are counted — so a
        video template's estimate is learned from prior video runs, never contaminated
        by cheap image runs (a 5s FLF2V clip and a Z-Image still can't share an estimate).
        """
        conditions = [FieldCondition(key="memory_type", match=MatchValue(value=MEMORY_TYPE_GENERATION))]
        if workflow_ref is not None:
            conditions.append(
                FieldCondition(key="workflow_ref", match=MatchValue(value=workflow_ref))
            )
        gens = await self._scroll_generations(Filter(must=conditions))
        gens.sort(key=lambda g: g.created_at)
        costs = [g.cost_usd for g in gens if g.cost_usd and g.cost_usd > 0]
        return costs[-limit:]

    # ── Model/LoRA registry (delegated to the JSON-backed registry the store owns) ─

    def register_model(self, asset: ModelAsset) -> None:
        """Register a single model/LoRA asset (upsert by name; sets identity_bearing)."""
        self._models.add(asset)

    def list_models(self) -> list[ModelAsset]:
        return self._models.list_models()

    def get_model(self, name: str) -> ModelAsset | None:
        return self._models.get_model(name)
