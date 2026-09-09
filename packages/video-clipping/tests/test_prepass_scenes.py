from __future__ import annotations

from pathlib import Path


from tests.conftest import requires_ffmpeg
from tests.fixtures.generate_synthetic_video import generate as generate_synthetic_video
from video_clipping.prepass.probe import probe
from video_clipping.prepass.scenes_pyscenedetect import detect_scenes_pyscenedetect
from video_clipping.prepass.scenes_scdet import detect_scenes_scdet


@requires_ffmpeg
def test_pyscenedetect_finds_cuts(tmp_path: Path) -> None:
    video = generate_synthetic_video(tmp_path / "sample.mp4")
    scenes = detect_scenes_pyscenedetect(video)
    # Synthetic clip has 3 hard scene transitions (4 distinct visual sources).
    assert len(scenes) >= 2, f"pyscenedetect returned too few scenes: {scenes}"
    for s, e in scenes:
        assert 0.0 <= s < e


@requires_ffmpeg
def test_scdet_finds_cuts(tmp_path: Path) -> None:
    video = generate_synthetic_video(tmp_path / "sample.mp4")
    metrics = probe(video)
    scenes = detect_scenes_scdet(video, duration_sec=metrics.duration_sec)
    assert len(scenes) >= 2, f"scdet returned too few scenes: {scenes}"
    for s, e in scenes:
        assert 0.0 <= s < e
