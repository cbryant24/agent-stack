"""faster-whisper single-pass transcription.

One pass over the whole source audio; per-segment slicing happens in
`slice.py`. Whisper is a fatal step: on any failure after `WHISPER_MAX_ATTEMPTS`
attempts, `TranscriptionError` is raised so the orchestrator can mark the run
`status="failed"` cleanly.

The model download (~40MB for `small.en`, ~150MB for `medium.en`) happens on
first use through faster-whisper's default HF cache. No `clip model sync`
command in Phase 1.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.tracing.decorators import record_tool_call

from video_clipping.constants import (
    WHISPER_BACKOFF_SEC,
    WHISPER_MAX_ATTEMPTS,
)
from video_clipping.exceptions import TranscriptionError


@dataclass(frozen=True)
class WhisperSegment:
    """One transcribed chunk with a time window and its text."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class WhisperTranscript:
    """Full-video transcript, chunked as faster-whisper emits it."""

    segments: tuple[WhisperSegment, ...]


def _load_model(model_name: str):  # pragma: no cover — imports the heavy dep
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="auto", compute_type="int8")


def transcribe(
    video: Path,
    model_name: str,
    _loader=_load_model,
) -> WhisperTranscript:
    """Transcribe `video` in one pass, with retry+backoff on failure.

    `_loader` is exposed for tests; production callers should not pass it.
    """
    last_exc: Exception | None = None
    for attempt in range(1, WHISPER_MAX_ATTEMPTS + 1):
        try:
            model = _loader(model_name)
            segments_iter, info = model.transcribe(
                str(video),
                word_timestamps=False,
                vad_filter=False,
            )
            segments = tuple(
                WhisperSegment(start=float(s.start), end=float(s.end), text=str(s.text))
                for s in segments_iter
            )
            record_tool_call(
                "faster_whisper.transcribe",
                f"video={video.name} model={model_name}",
                f"segments={len(segments)} duration={getattr(info, 'duration', 0.0):.2f}s",
            )
            return WhisperTranscript(segments=segments)
        except Exception as exc:
            last_exc = exc
            if attempt < WHISPER_MAX_ATTEMPTS:
                time.sleep(WHISPER_BACKOFF_SEC)
    raise TranscriptionError(
        f"faster-whisper failed after {WHISPER_MAX_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc
