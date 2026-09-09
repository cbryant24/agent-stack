from __future__ import annotations

import json
import subprocess
from pathlib import Path


from tests.conftest import requires_ffmpeg
from tests.fixtures.generate_synthetic_video import generate as generate_video
from video_clipping.cut.ffmpeg_cut import _slug, cut_clip, has_audio_stream
from video_clipping.models import ClipDecision


def _ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True,
    )
    return float(json.loads(proc.stdout)["format"]["duration"])


def _decision(seg_id: str, start: float, end: float, summary: str) -> ClipDecision:
    return ClipDecision(
        segment_id=seg_id, action="include",
        refined_start=start, refined_end=end,
        theme_match=0.8, confidence=0.8, one_line_summary=summary,
    )


def test_slug_basic() -> None:
    assert _slug("Wide granite summit view!") == "wide-granite-summit-view"
    assert _slug("") == "clip"
    assert _slug("   ---   ") == "clip"
    long = _slug("a" * 200, max_len=10)
    assert len(long) == 10


@requires_ffmpeg
def test_cut_clip_produces_playable_files(tmp_path: Path) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    clips_dir = tmp_path / "clips"

    d1 = _decision("s1", 0.0, 2.0, "opening testsrc")
    d2 = _decision("s2", 6.0, 8.0, "closing testsrc dim")
    p1 = cut_clip(video, d1, 1, clips_dir)
    p2 = cut_clip(video, d2, 2, clips_dir)

    assert p1.exists() and p1.stat().st_size > 0
    assert p2.exists() and p2.stat().st_size > 0
    assert p1.name == "01_opening-testsrc.mp4"
    assert p2.name == "02_closing-testsrc-dim.mp4"

    # Duration within 0.3s tolerance — ffmpeg keyframe alignment on -c copy can shift boundaries.
    assert abs(_ffprobe_duration(p1) - 2.0) < 0.3
    assert abs(_ffprobe_duration(p2) - 2.0) < 0.3


@requires_ffmpeg
def test_has_audio_stream_caches(tmp_path: Path) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    cache: dict[Path, bool] = {}
    assert has_audio_stream(video, cache=cache) is True
    # Second call should hit the cache — no assert on ffprobe count here (subprocess is transparent),
    # but the return must be stable.
    assert has_audio_stream(video, cache=cache) is True
    assert video.resolve() in cache


@requires_ffmpeg
def test_cut_clip_silent_source_uses_an(tmp_path: Path) -> None:
    """When the source has no audio, the re-encode fallback must use -an, not -c:a aac."""
    # Build a silent video.
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=15",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
         str(silent)],
        check=True,
    )
    assert has_audio_stream(silent) is False

    d = _decision("s0", 0.2, 1.7, "silent slice")
    out = cut_clip(silent, d, 1, tmp_path / "clips")
    assert out.exists() and out.stat().st_size > 0
    # And still silent.
    assert has_audio_stream(out) is False
