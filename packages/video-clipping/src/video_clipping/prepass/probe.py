"""ffprobe wrapper — video-file metadata (resolution, fps, bitrate, duration)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from video_clipping.models import PrepassMetrics


def _run_ffprobe(video: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _parse_fps(rate: str) -> float:
    """ffprobe reports frame rates as 'num/den' strings (e.g. '30000/1001')."""
    if "/" in rate:
        num, den = rate.split("/", 1)
        num_f, den_f = float(num), float(den)
        return num_f / den_f if den_f else 0.0
    return float(rate)


def probe(video: Path) -> PrepassMetrics:
    data = _run_ffprobe(video)
    video_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise ValueError(f"No video stream found in {video}")
    v = video_streams[0]
    width = int(v.get("width") or 0)
    height = int(v.get("height") or 0)
    fps = _parse_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1")
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    bitrate_raw = (data.get("format") or {}).get("bit_rate")
    bitrate_kbps = int(int(bitrate_raw) / 1000) if bitrate_raw else None
    return PrepassMetrics(
        resolution=(width, height),
        fps=fps,
        bitrate_kbps=bitrate_kbps,
        duration_sec=duration,
    )
