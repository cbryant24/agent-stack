"""Stage 3 — sample frames + Claude Sonnet vision summary."""

from __future__ import annotations

from video_clipping.vision.sample_frames import frame_count, sample_frames
from video_clipping.vision.summarize import summarize_segment

__all__ = ["sample_frames", "frame_count", "summarize_segment"]
