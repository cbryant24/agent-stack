"""Extract JPEG frames from a segment window with ffmpeg.

Frame count uses the same formula as the Phase-0 cost projection in
`draft._project_cost`, so the projected and actual frame counts line up
exactly.
"""

from __future__ import annotations

import subprocess
from math import ceil
from pathlib import Path

from agent_runtime.tracing.decorators import record_tool_call

from video_clipping.constants import FRAME_SAMPLE_INTERVAL_SEC, MAX_FRAMES_PER_SEGMENT
from video_clipping.exceptions import VisionError
from video_clipping.models import Segment


def frame_count(duration_sec: float) -> int:
    """How many frames to sample for a segment of the given duration."""
    return min(max(1, ceil(duration_sec / FRAME_SAMPLE_INTERVAL_SEC)), MAX_FRAMES_PER_SEGMENT)


def sample_frames(video: Path, seg: Segment, scratch_dir: Path) -> list[Path]:
    n = frame_count(seg.duration)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # Sample at the midpoint of each of `n` equal sub-windows across the segment.
    # This keeps every timestamp strictly inside (seg.start, seg.end) so ffmpeg
    # never seeks to the exact end (which fails when it's past the last frame).
    timestamps = [seg.start + (i + 0.5) * seg.duration / n for i in range(n)]

    out_paths: list[Path] = []
    for i, t in enumerate(timestamps):
        out = scratch_dir / f"{seg.segment_id}_{i:02d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{t:.3f}", "-i", str(video),
            "-frames:v", "1", "-q:v", "3",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise VisionError(
                f"ffmpeg frame extract failed for {seg.segment_id} @ {t:.3f}s: "
                f"{exc.stderr.decode(errors='replace').strip()}"
            ) from exc
        if not out.exists() or out.stat().st_size == 0:
            raise VisionError(f"ffmpeg wrote no frame for {seg.segment_id} @ {t:.3f}s")
        out_paths.append(out)

    record_tool_call(
        "ffmpeg.frame_extract",
        f"segment={seg.segment_id} n={n} duration={seg.duration:.2f}s",
        f"frames_written={len(out_paths)}",
    )
    return out_paths
