"""Cross-run duplicate detection (Phase 2, opt-in via --cross-run-dedupe).

For each intra-run-accepted decision, query `video_clipping_memory` for the
nearest `segment`-type points from other runs. If any exceeds `threshold`, the
current decision is flipped to `action="exclude"` /
`exclude_reason="duplicate_of_previous_run"`, and a `CrossRunHit` describing
the prior match is recorded for the report.

Runs AFTER intra-run dedupe. Reuses the vectors already computed in stage 5 —
no additional embedding cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from video_clipping.constants import SIMILARITY_THRESHOLD
from video_clipping.models import ClipDecision
from video_clipping.store import VideoClippingStore

logger = logging.getLogger(__name__)


@dataclass
class CrossRunHit:
    """One accepted-then-dropped decision matched to a prior run's segment."""

    segment_id: str
    one_line_summary: str
    prior_run_id: str
    prior_segment_id: str
    prior_one_line: str
    score: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "one_line_summary": self.one_line_summary,
            "prior_run_id": self.prior_run_id,
            "prior_segment_id": self.prior_segment_id,
            "prior_one_line": self.prior_one_line,
            "score": self.score,
        }


@dataclass
class CrossRunOutcome:
    kept: list[ClipDecision] = field(default_factory=list)
    hits: list[CrossRunHit] = field(default_factory=list)
    skipped_segment_ids: list[str] = field(default_factory=list)


async def apply_cross_run_dedupe(
    *,
    decisions: list[ClipDecision],
    embeddings: dict[str, list[float]],
    current_run_id: str,
    store: VideoClippingStore,
    threshold: float = SIMILARITY_THRESHOLD,
    top_k: int = 5,
) -> CrossRunOutcome:
    """Drop cross-run duplicates from `decisions` (already intra-run-deduped).

    `embeddings[segment_id]` is the L2-normalized vector already computed by
    stage 5. If a decision's vector is missing, we skip cross-run for that
    segment (recorded in `outcome.skipped_segment_ids`) and let it through.
    """
    outcome = CrossRunOutcome()

    for decision in decisions:
        vector = embeddings.get(decision.segment_id)
        if vector is None:
            outcome.skipped_segment_ids.append(decision.segment_id)
            outcome.kept.append(decision)
            continue

        try:
            hits = await store.query_nearest(
                vector,
                top_k=top_k,
                filter_by_type="segment",
                exclude_run_ids=[current_run_id],
            )
        except Exception:
            logger.exception(
                "cross-run query failed for segment %s; keeping it", decision.segment_id
            )
            outcome.skipped_segment_ids.append(decision.segment_id)
            outcome.kept.append(decision)
            continue

        match = _first_over_threshold(hits, threshold)
        if match is None:
            outcome.kept.append(decision)
            continue

        _pid, score, payload = match
        prior_run_id = str(payload.get("run_id", ""))
        prior_segment_id = str(payload.get("segment_id", ""))
        prior_one_line = str(
            (payload.get("decision") or {}).get("one_line_summary")
            or payload.get("one_line_summary")
            or ""
        )
        outcome.hits.append(
            CrossRunHit(
                segment_id=decision.segment_id,
                one_line_summary=decision.one_line_summary,
                prior_run_id=prior_run_id,
                prior_segment_id=prior_segment_id,
                prior_one_line=prior_one_line,
                score=float(score),
            )
        )
        # We do NOT append the flipped decision to `kept`; the orchestrator
        # will merge the flipped copies back into `all_decisions` for the report.
    return outcome


def _first_over_threshold(
    hits: list[tuple[str, float, dict[str, Any]]], threshold: float
) -> tuple[str, float, dict[str, Any]] | None:
    for h in hits:
        if h[1] >= threshold:
            return h
    return None


def flip_to_cross_run_duplicate(decision: ClipDecision) -> ClipDecision:
    """Produce the excluded copy of a decision that lost to a prior run."""
    return decision.model_copy(
        update={
            "action": "exclude",
            "exclude_reason": "duplicate_of_previous_run",
        }
    )
