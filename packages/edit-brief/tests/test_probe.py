from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from edit_brief.probe import ffprobe_duration

from .conftest import requires_ffmpeg


def test_missing_file_returns_none(tmp_path: Path):
    assert ffprobe_duration(tmp_path / "nope.mp3") is None


def test_garbage_file_returns_none(tmp_path: Path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio at all")
    assert ffprobe_duration(bad) is None


@requires_ffmpeg
def test_reads_real_duration(tmp_path: Path):
    audio = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", str(audio)],
        check=True,
    )
    dur = ffprobe_duration(audio)
    assert dur is not None
    assert dur == pytest.approx(2.0, abs=0.1)
