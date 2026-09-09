from __future__ import annotations

from pathlib import Path

import pytest

from video_clipping.audio.slice import slice_transcript
from video_clipping.audio.transcribe import (
    WhisperSegment,
    WhisperTranscript,
    transcribe,
)
from video_clipping.exceptions import TranscriptionError
from video_clipping.models import Segment

from tests.fakes import FakeWhisperModel, FakeWhisperSegment


def _seg(start: float, end: float) -> Segment:
    return Segment(start=start, end=end, duration=end - start)


def test_slice_transcript_by_windows() -> None:
    tr = WhisperTranscript(
        segments=(
            WhisperSegment(start=0.0, end=1.5, text="first bit"),
            WhisperSegment(start=1.8, end=3.2, text="second bit"),
            WhisperSegment(start=3.5, end=5.0, text="third bit"),
            WhisperSegment(start=6.0, end=7.0, text="fourth bit"),
            WhisperSegment(start=8.0, end=9.0, text="fifth bit"),
        )
    )
    windows = [_seg(0.0, 3.0), _seg(3.0, 6.0), _seg(6.0, 10.0)]
    assert slice_transcript(tr, windows[0]) == "first bit second bit"
    assert slice_transcript(tr, windows[1]) == "second bit third bit"
    assert slice_transcript(tr, windows[2]) == "fourth bit fifth bit"


def test_slice_transcript_empty_window_yields_empty_string() -> None:
    tr = WhisperTranscript(
        segments=(WhisperSegment(start=0.0, end=1.0, text="hi"),)
    )
    assert slice_transcript(tr, _seg(5.0, 8.0)) == ""


def test_slice_transcript_strips_whitespace() -> None:
    tr = WhisperTranscript(
        segments=(
            WhisperSegment(start=0.0, end=1.0, text="  hi   "),
            WhisperSegment(start=1.0, end=2.0, text=""),
        )
    )
    assert slice_transcript(tr, _seg(0.0, 3.0)) == "hi"


def test_transcribe_uses_loader_and_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeWhisperModel(
        segments=[
            FakeWhisperSegment(start=0.0, end=1.0, text="one"),
            FakeWhisperSegment(start=1.0, end=2.0, text="two"),
        ],
        duration=2.0,
    )
    dummy_video = tmp_path / "v.mp4"
    dummy_video.write_bytes(b"x")

    result = transcribe(dummy_video, "small.en", _loader=lambda name: fake)
    assert [s.text for s in result.segments] == ["one", "two"]


def test_transcribe_retries_then_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("video_clipping.audio.transcribe.WHISPER_BACKOFF_SEC", 0.0)

    calls = {"n": 0}

    def flaky_loader(_name: str):
        calls["n"] += 1
        raise RuntimeError("boom")

    dummy_video = tmp_path / "v.mp4"
    dummy_video.write_bytes(b"x")

    with pytest.raises(TranscriptionError, match="failed after"):
        transcribe(dummy_video, "small.en", _loader=flaky_loader)
    assert calls["n"] == 2  # WHISPER_MAX_ATTEMPTS


def test_transcribe_recovers_on_second_attempt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("video_clipping.audio.transcribe.WHISPER_BACKOFF_SEC", 0.0)

    attempts = {"n": 0}
    good = FakeWhisperModel(
        segments=[FakeWhisperSegment(start=0.0, end=1.0, text="ok")],
        duration=1.0,
    )

    def flaky_loader(_name: str):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("first attempt failed")
        return good

    dummy_video = tmp_path / "v.mp4"
    dummy_video.write_bytes(b"x")

    result = transcribe(dummy_video, "small.en", _loader=flaky_loader)
    assert result.segments[0].text == "ok"
    assert attempts["n"] == 2
