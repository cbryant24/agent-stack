from __future__ import annotations

from pathlib import Path


from tests.conftest import requires_ffmpeg
from tests.fixtures.generate_synthetic_video import generate as generate_synthetic_video
from video_clipping.prepass.silence import detect_silences


@requires_ffmpeg
def test_silencedetect_finds_middle_gap(tmp_path: Path) -> None:
    video = generate_synthetic_video(tmp_path / "sample.mp4")
    silences = detect_silences(video, noise_db=-30.0, min_duration_sec=0.5)
    assert silences, "expected at least one silence window in the synthetic fixture"
    # The synthetic clip is silent from t=3.0 to t=6.0 (3 seconds).
    starts = [s for s, _ in silences]
    ends = [e for _, e in silences]
    assert any(2.5 < s < 3.5 for s in starts), f"no silence start near 3.0s: {silences}"
    assert any(5.5 < e < 6.5 for e in ends), f"no silence end near 6.0s: {silences}"
