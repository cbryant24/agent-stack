"""Slice a full transcript by candidate-segment boundaries.

Overlap is inclusive on both edges (a whisper segment counts if it overlaps
the candidate window at all). Returns an empty string when nothing overlaps so
downstream code can distinguish "silent segment" from "not yet processed"
(the field's default is `None`).
"""

from __future__ import annotations

from video_clipping.audio.transcribe import WhisperTranscript
from video_clipping.models import Segment


def slice_transcript(transcript: WhisperTranscript, seg: Segment) -> str:
    """Concatenate whisper text that falls inside [seg.start, seg.end).

    Interval is half-open on the right so a whisper segment starting exactly on
    a candidate boundary lands in the *later* window, not both.
    """
    parts: list[str] = []
    for ws in transcript.segments:
        if ws.end <= seg.start or ws.start >= seg.end:
            continue
        text = ws.text.strip()
        if text:
            parts.append(text)
    return " ".join(parts)
