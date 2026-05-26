from __future__ import annotations

import subprocess
from pathlib import Path

from yt_intelligence_pipeline.models import TimestampEntry


def extract_frames(
    video_path: Path,
    timestamps: list[TimestampEntry],
    output_dir: Path,
) -> list[TimestampEntry]:
    """Extract one PNG frame per timestamp; delete the source video when done."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, entry in enumerate(timestamps, 1):
        out_path = output_dir / f"screenshot_{i:03d}.png"
        _run_ffmpeg(video_path, entry.timestamp_seconds, out_path)
        entry.extracted_image_path = out_path

    video_path.unlink()
    return timestamps


def _run_ffmpeg(video_path: Path, seconds: int, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss", str(seconds),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(out_path),
        ],
        check=True,
        capture_output=True,
    )
