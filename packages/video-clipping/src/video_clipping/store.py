"""VideoClippingStore — Qdrant wrapper for the video-clipping agent.

Wraps `agent_runtime.memory.MemoryStore`, writes and reads points in the
`video_clipping_memory` collection under three `memory_type` discriminators:
`run`, `segment`, `lesson`.

Point-id policy
---------------
Sibling agents (visual-generation etc.) use `uuid.uuid4()` entry_ids. This
store uses deterministic `uuid.uuid5(NAMESPACE_VIDEO_CLIPPING, key)` so a
retried `clip generate` upserts (not duplicates) points for the same
run_id/segment_id/lesson_id.

Payload indices
---------------
`memory_type` and `run_id` are indexed as KEYWORDs so cross-run dedupe and
explain can filter cheaply. Nothing else in the repo indexes payload today —
this is intentional and documented. `create_payload_index` is idempotent so
we call it from `ensure_collection()` on every startup.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from agent_runtime.memory.store import MemoryStore
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
)

from video_clipping.constants import (
    COLLECTION_NAME,
    EMBEDDING_DIM,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_RUN,
    MEMORY_TYPE_SEGMENT,
    NAMESPACE_VIDEO_CLIPPING,
)
from video_clipping.models import ClipDecision, Lesson, Run, Segment


# ── Deterministic point-id helpers ───────────────────────────────────────────

def _run_point_id(run_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE_VIDEO_CLIPPING, f"run:{run_id}"))


def _segment_point_id(run_id: str, segment_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE_VIDEO_CLIPPING, f"segment:{run_id}:{segment_id}"))


def _lesson_point_id(lesson_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE_VIDEO_CLIPPING, f"lesson:{lesson_id}"))


# ── Payload / embedding-text builders ────────────────────────────────────────

def _run_summary_string(run: Run) -> str:
    """Short embedded string that captures a run's identity for retrieval."""
    accepted = len(run.accepted_segment_ids)
    content = ", ".join(run.spec.content_wanted[:3]) or "unspecified"
    return (
        f"{run.spec.event_type} at {run.spec.location}: "
        f"{accepted} accepted clips; content: {content}"
    )


def _run_payload(run: Run) -> dict[str, Any]:
    """Payload persisted on a run-type point. Denormalizes a few spec fields for filtering."""
    excluded_reason_counts: dict[str, int] = {}
    for d in run.decisions:
        if d.action == "exclude" and d.exclude_reason:
            excluded_reason_counts[d.exclude_reason] = (
                excluded_reason_counts.get(d.exclude_reason, 0) + 1
            )
    return {
        "memory_type": MEMORY_TYPE_RUN,
        "run_id": run.run_id,
        "created_at": run.created_at,
        "video_sha256": run.video_sha256,
        "spec": run.spec.model_dump(mode="json"),
        "prepass_metrics": run.prepass_metrics.model_dump(mode="json"),
        "status": run.status,
        "halted_reason": run.halted_reason,
        "actual_cost_usd": run.actual_cost_usd,
        "cost_estimate": run.cost_estimate.model_dump(mode="json"),
        "accepted_segment_ids": list(run.accepted_segment_ids),
        "clip_paths": [str(p) for p in run.clip_paths],
        "lessons_recorded": list(run.lessons_recorded),
        "excluded_reason_counts": excluded_reason_counts,
        "qdrant_deviation": run.qdrant_deviation,
        "event_type": run.spec.event_type,
        "location": run.spec.location,
    }


def _segment_payload(
    *, run: Run, segment: Segment, decision: ClipDecision, clip_path: str | None
) -> dict[str, Any]:
    return {
        "memory_type": MEMORY_TYPE_SEGMENT,
        "segment_id": segment.segment_id,
        "run_id": run.run_id,
        "created_at": run.created_at,
        "refined_start": decision.refined_start,
        "refined_end": decision.refined_end,
        "duration": max(0.0, decision.refined_end - decision.refined_start),
        "transcript": segment.transcript,
        "visual_summary": segment.visual_summary,
        "decision": {
            "action": decision.action,
            "theme_match": decision.theme_match,
            "confidence": decision.confidence,
            "one_line_summary": decision.one_line_summary,
        },
        "clip_path": clip_path,
        "video_sha256": run.video_sha256,
        "event_type": run.spec.event_type,
        "location": run.spec.location,
    }


def _lesson_payload(lesson: Lesson) -> dict[str, Any]:
    payload = lesson.to_payload()
    payload["memory_type"] = MEMORY_TYPE_LESSON
    return payload


# ── Filter helpers ───────────────────────────────────────────────────────────

def _build_filter(
    *,
    filter_by_type: str | Iterable[str] | None,
    exclude_run_ids: Iterable[str] | None,
    extra_musts: list[Any] | None = None,
) -> Filter | None:
    musts: list[Any] = []
    must_nots: list[Any] = []

    if filter_by_type is not None:
        if isinstance(filter_by_type, str):
            musts.append(
                FieldCondition(key="memory_type", match=MatchValue(value=filter_by_type))
            )
        else:
            types = list(filter_by_type)
            if len(types) == 1:
                musts.append(
                    FieldCondition(key="memory_type", match=MatchValue(value=types[0]))
                )
            elif len(types) > 1:
                # Not-in-anything-but-these-types via MatchExcept over the complement isn't
                # sensible here; use MatchExcept for exclude only. For multi-type inclusion
                # we run one query per type at the caller layer. Fall through to no
                # memory_type filter (caller must post-filter).
                pass

    if exclude_run_ids:
        for r in exclude_run_ids:
            must_nots.append(
                FieldCondition(key="run_id", match=MatchValue(value=str(r)))
            )

    if extra_musts:
        musts.extend(extra_musts)

    if not musts and not must_nots:
        return None
    return Filter(must=musts or None, must_not=must_nots or None)


# ── Store ────────────────────────────────────────────────────────────────────


class VideoClippingStore:
    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name

    @property
    def collection(self) -> str:
        return self._collection

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection(self._collection, vector_size=EMBEDDING_DIM)
        # Idempotent — Qdrant no-ops if the index already exists.
        for field_name in ("memory_type", "run_id"):
            try:
                await self._store._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                # Index already present; ignore. (qdrant-client raises on duplicate
                # index creation; there is no dry-run/`if not exists` variant.)
                pass

    # ── Writes ──────────────────────────────────────────────────────────────

    async def upsert_run(self, run: Run) -> str:
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([_run_summary_string(run)], input_type="document")
        point_id = _run_point_id(run.run_id)
        point = PointStruct(id=point_id, vector=vector, payload=_run_payload(run))
        await self._store.upsert_raw_points(self._collection, [point])
        return point_id

    async def upsert_segment(
        self,
        *,
        run: Run,
        segment: Segment,
        decision: ClipDecision,
        clip_path: str | None,
        precomputed_vector: list[float] | None = None,
    ) -> str:
        if precomputed_vector is not None:
            vector = precomputed_vector
        else:
            embedder = self._store.embedding_client
            [vector] = await embedder.embed(
                [decision.one_line_summary], input_type="document"
            )
        point_id = _segment_point_id(run.run_id, segment.segment_id)
        payload = _segment_payload(
            run=run, segment=segment, decision=decision, clip_path=clip_path
        )
        point = PointStruct(id=point_id, vector=vector, payload=payload)
        await self._store.upsert_raw_points(self._collection, [point])
        return point_id

    async def upsert_lesson(self, lesson: Lesson) -> str:
        text = lesson.embedding_text()
        if not text:
            raise ValueError(f"lesson {lesson.lesson_id} has no embeddable text")
        embedder = self._store.embedding_client
        [vector] = await embedder.embed([text], input_type="document")
        point_id = _lesson_point_id(lesson.lesson_id)
        point = PointStruct(id=point_id, vector=vector, payload=_lesson_payload(lesson))
        await self._store.upsert_raw_points(self._collection, [point])
        return point_id

    # ── Reads ───────────────────────────────────────────────────────────────

    async def query_nearest(
        self,
        vector: list[float],
        *,
        top_k: int = 10,
        filter_by_type: str | None = None,
        exclude_run_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Return top-K nearest points as (point_id, score, payload) tuples."""
        filters = _build_filter(
            filter_by_type=filter_by_type, exclude_run_ids=exclude_run_ids
        )
        return await self._store.query_by_vector(
            self._collection, vector, limit=top_k, filters=filters
        )

    async def retrieve_lessons(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch lesson payloads by internal lesson_id (uuid5-mapped)."""
        if not ids:
            return []
        point_ids = [_lesson_point_id(i) for i in ids]
        records = await self._store.retrieve_points(self._collection, point_ids)
        return [dict(r.payload or {}) for r in records]
