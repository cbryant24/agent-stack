"""Stage 5 — intra-run + cross-run similarity dedupe on Voyage embeddings."""

from __future__ import annotations

from video_clipping.similarity.cross_run import (
    CrossRunHit,
    CrossRunOutcome,
    apply_cross_run_dedupe,
    flip_to_cross_run_duplicate,
)
from video_clipping.similarity.dedupe import dedupe
from video_clipping.similarity.embed import embed_summaries

__all__ = [
    "embed_summaries",
    "dedupe",
    "apply_cross_run_dedupe",
    "flip_to_cross_run_duplicate",
    "CrossRunHit",
    "CrossRunOutcome",
]
