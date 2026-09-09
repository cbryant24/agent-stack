"""Stage 6 — ffmpeg cut (stream copy first, re-encode fallback)."""

from __future__ import annotations

from video_clipping.cut.ffmpeg_cut import cut_clip, has_audio_stream

__all__ = ["cut_clip", "has_audio_stream"]
