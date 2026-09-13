"""Auto-accrued lessons from `clip generate` runs (Phase 2).

Two pattern detectors run over each completed run:

- `exclude_cluster`: >= LESSON_CLUSTER_MIN segments share an exclude_reason
  (other than duplicate/error) → one Lesson.
- `cross_run_repeat`: >= LESSON_CROSS_RUN_MIN cross-run drops point at the same
  prior run → one Lesson.

Lessons are Qdrant-persisted `memory_type="lesson"` points. On subsequent runs,
`surface_lessons_for_spec` retrieves the top-K nearest lessons by the spec's
`event_type + first content_wanted` embedding and returns their human_summary
strings for injection into the decide prompt.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from video_clipping.constants import (
    LESSON_CLUSTER_MIN,
    LESSON_CROSS_RUN_MIN,
    LESSON_SURFACE_THRESHOLD,
    LESSON_SURFACE_TOP_K,
)
from video_clipping.models import ClipDecision, Lesson, Run
from video_clipping.similarity.cross_run import CrossRunHit
from video_clipping.store import VideoClippingStore

logger = logging.getLogger(__name__)

# Exclude reasons that never justify a lesson (they're the pipeline's own signal,
# not a director-actionable pattern).
_LESSON_SUPPRESSED_REASONS = frozenset(
    {"duplicate_of_previous", "duplicate_of_previous_run", "error"}
)


def accrue_lessons(
    run: Run,
    decisions: list[ClipDecision],
    cross_run_hits: list[CrossRunHit],
) -> list[Lesson]:
    """Scan a completed run for pattern-worthy lessons.

    Returns a list of new Lesson objects (may be empty).
    """
    lessons: list[Lesson] = []
    lessons.extend(_exclude_cluster_lessons(run, decisions))
    lessons.extend(_cross_run_repeat_lessons(run, cross_run_hits))
    return lessons


def _exclude_cluster_lessons(run: Run, decisions: list[ClipDecision]) -> list[Lesson]:
    counts: Counter[str] = Counter()
    for d in decisions:
        if d.action != "exclude":
            continue
        if not d.exclude_reason or d.exclude_reason in _LESSON_SUPPRESSED_REASONS:
            continue
        counts[d.exclude_reason] += 1

    lessons: list[Lesson] = []
    for reason, n in counts.items():
        if n < LESSON_CLUSTER_MIN:
            continue
        content0 = (run.spec.content_wanted or ["(unspecified)"])[0]
        human_summary = (
            f"For {run.spec.event_type} spec with content '{content0}', {n} "
            f"segments were excluded as '{reason}'. Consider tightening pre-pass "
            f"or spec wording."
        )
        lessons.append(
            Lesson(
                source_run_id=run.run_id,
                pattern_type="exclude_cluster",
                pattern_payload={
                    "exclude_reason": reason,
                    "count": n,
                    "event_type": run.spec.event_type,
                    "content_wanted": list(run.spec.content_wanted),
                },
                human_summary=human_summary,
                event_type=run.spec.event_type,
            )
        )
    return lessons


def _cross_run_repeat_lessons(
    run: Run, cross_run_hits: list[CrossRunHit]
) -> list[Lesson]:
    by_prior: dict[str, int] = defaultdict(int)
    for hit in cross_run_hits:
        if hit.prior_run_id:
            by_prior[hit.prior_run_id] += 1

    lessons: list[Lesson] = []
    for prior_run_id, n in by_prior.items():
        if n < LESSON_CROSS_RUN_MIN:
            continue
        video_short = (run.video_sha256 or "")[:8]
        human_summary = (
            f"Runs on video {video_short} tend to duplicate prior run "
            f"{prior_run_id[:8]} ({n} matches). Consider skipping this footage "
            f"or narrowing the spec."
        )
        lessons.append(
            Lesson(
                source_run_id=run.run_id,
                pattern_type="cross_run_repeat",
                pattern_payload={
                    "prior_run_id": prior_run_id,
                    "count": n,
                    "video_sha256": run.video_sha256,
                },
                human_summary=human_summary,
                event_type=run.spec.event_type,
            )
        )
    return lessons


async def surface_lessons_for_spec(
    run: Run,
    store: VideoClippingStore,
    *,
    top_k: int = LESSON_SURFACE_TOP_K,
    threshold: float = LESSON_SURFACE_THRESHOLD,
) -> list[str]:
    """Retrieve human_summary strings from lessons relevant to this spec.

    Silently returns [] on Qdrant failure — surfacing is best-effort and
    must not fail the run.
    """
    spec = run.spec
    content = (spec.content_wanted or [""])[0]
    query = f"{spec.event_type}: {content}".strip(": ").strip()
    if not query:
        return []
    try:
        embedder = store._store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        hits = await store.query_nearest(qv, top_k=top_k, filter_by_type="lesson")
    except Exception as exc:
        logger.warning(
            "Lesson surfacing skipped (Qdrant unreachable?): %s. "
            "Start Qdrant with `docker compose -f infrastructure/docker-compose.yml up -d` "
            "to enable lesson-aware decide prompts.",
            exc,
        )
        return []

    summaries: list[str] = []
    for _pid, score, payload in hits:
        if score < threshold:
            continue
        text = payload.get("human_summary") or payload.get("statement")
        if text:
            summaries.append(str(text))
    return summaries
