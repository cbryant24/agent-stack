"""Phase-1 exception taxonomy for video-clipping.

Two failure severities:

- Per-segment errors (`VisionError`, `DecisionParseError`, `CutError`) are caught
  inside the segment loop; the segment is recorded with action="exclude" +
  exclude_reason="error" and the run keeps going.
- Whole-run errors (`TranscriptionError`, `FfprobeError`) halt the run; run.json
  records status="failed" and halted_reason.
"""

from __future__ import annotations


class VideoClippingError(Exception):
    """Base class for video-clipping domain errors."""


class TranscriptionError(VideoClippingError):
    """Whisper failed after retries."""


class FfprobeError(VideoClippingError):
    """ffprobe failed to read the source video."""


class VisionError(VideoClippingError):
    """Frame extraction or vision-summary LLM call failed."""


class DecisionParseError(VideoClippingError):
    """Decision LLM output did not parse into a ClipDecision after retry."""


class CutError(VideoClippingError):
    """ffmpeg cut failed for one clip (stream copy AND re-encode)."""
