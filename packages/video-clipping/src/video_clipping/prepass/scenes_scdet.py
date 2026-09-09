"""ffmpeg scdet wrapper — per-frame scores → post-processed cut list.

scdet prints per-frame lines to stderr like:
    [scdet @ 0x...] lavfi.scd.score: 12.345678, lavfi.scd.time: 4.567
We collect frames above SCDET_THRESHOLD, merge cuts within SCDET_MERGE_WINDOW_SEC,
and emit the resulting scene ranges as [(start, end), ...] (start = 0, then each
subsequent cut becomes the next scene boundary).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from video_clipping.constants import SCDET_MERGE_WINDOW_SEC, SCDET_THRESHOLD

_LINE_RE = re.compile(
    r"lavfi\.scd\.score:\s*([\d.]+).*?lavfi\.scd\.time:\s*([\d.]+)"
)


def _run_scdet(video: Path, threshold: float) -> list[tuple[float, float]]:
    """Return raw (score, time) frames above threshold."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i", str(video),
            "-vf", f"scdet=s=1:threshold={threshold}",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    frames: list[tuple[float, float]] = []
    for line in result.stderr.splitlines():
        m = _LINE_RE.search(line)
        if not m:
            continue
        score = float(m.group(1))
        t = float(m.group(2))
        if score >= threshold:
            frames.append((score, t))
    return frames


def _merge_cuts(times: list[float], merge_window_sec: float) -> list[float]:
    """Collapse cuts that fall within merge_window_sec of the previous kept cut."""
    kept: list[float] = []
    for t in sorted(times):
        if not kept or (t - kept[-1]) > merge_window_sec:
            kept.append(t)
    return kept


def detect_scenes_scdet(
    video: Path,
    duration_sec: float,
    threshold: float = SCDET_THRESHOLD,
    merge_window_sec: float = SCDET_MERGE_WINDOW_SEC,
) -> list[tuple[float, float]]:
    """Return scene ranges (start, end) built by post-processing scdet frames."""
    frames = _run_scdet(video, threshold)
    cut_times = _merge_cuts([t for _, t in frames], merge_window_sec)

    scenes: list[tuple[float, float]] = []
    prev = 0.0
    for t in cut_times:
        if t > prev:
            scenes.append((prev, t))
        prev = t
    if duration_sec > prev:
        scenes.append((prev, duration_sec))
    return scenes
