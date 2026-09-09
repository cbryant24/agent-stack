"""Memory surface for the video-clipping agent.

Phase 0 re-exports the store client so future callers (Phase 2+) can import from
`video_clipping.memory` regardless of where the concrete class lives.
"""

from __future__ import annotations

from video_clipping.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_RUN,
    MEMORY_TYPE_SEGMENT,
)
from video_clipping.store import VideoClippingStore

__all__ = [
    "COLLECTION_NAME",
    "MEMORY_TYPE_LESSON",
    "MEMORY_TYPE_RUN",
    "MEMORY_TYPE_SEGMENT",
    "VideoClippingStore",
]
