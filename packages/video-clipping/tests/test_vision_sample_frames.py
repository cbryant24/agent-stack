from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import requires_ffmpeg
from tests.fixtures.generate_synthetic_video import generate as generate_video
from video_clipping.models import Segment
from video_clipping.vision.sample_frames import frame_count, sample_frames


def _seg(start: float, end: float) -> Segment:
    return Segment(start=start, end=end, duration=end - start)


@pytest.mark.parametrize(
    "duration,expected",
    [(1.0, 1), (5.0, 3), (20.0, 8), (60.0, 8), (0.1, 1)],
)
def test_frame_count(duration: float, expected: int) -> None:
    assert frame_count(duration) == expected


@requires_ffmpeg
def test_sample_frames_writes_expected_count(tmp_path: Path) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    scratch = tmp_path / "frames"
    seg = _seg(0.0, 3.0)  # duration=3.0 → 2 frames per formula
    paths = sample_frames(video, seg, scratch)
    assert len(paths) == frame_count(3.0)
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0
        assert p.suffix == ".jpg"


@requires_ffmpeg
def test_sample_frames_single_frame_at_midpoint(tmp_path: Path) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    seg = _seg(6.5, 7.0)  # duration=0.5 → 1 frame
    paths = sample_frames(video, seg, tmp_path / "frames")
    assert len(paths) == 1
    assert paths[0].exists()
