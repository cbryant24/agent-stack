"""video-clipping — CLI agent for cutting highlights from long-form video.

Phase 0 ships the free pre-pass (ffmpeg + PySceneDetect + scdet + ffprobe +
ebur128) and stubs for `generate`, `report`, `explain`. See docs/masterplan.md
for the full pipeline and phase plan.
"""

from __future__ import annotations

from video_clipping.constants import (
    AGENT_NAME,
    COLLECTION_NAME,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_RUN,
    MEMORY_TYPE_SEGMENT,
)
from video_clipping.draft import DraftResult, draft_sync
from video_clipping.models import (
    ClipDecision,
    CostEstimate,
    Lesson,
    PrepassMetrics,
    Run,
    Segment,
    Spec,
)
from video_clipping.store import VideoClippingStore

__all__ = [
    "AGENT_NAME",
    "COLLECTION_NAME",
    "ClipDecision",
    "CostEstimate",
    "DraftResult",
    "Lesson",
    "MEMORY_TYPE_LESSON",
    "MEMORY_TYPE_RUN",
    "MEMORY_TYPE_SEGMENT",
    "PrepassMetrics",
    "Run",
    "Segment",
    "Spec",
    "VideoClippingStore",
    "draft_sync",
]
