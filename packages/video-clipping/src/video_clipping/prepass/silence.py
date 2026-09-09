"""ffmpeg silencedetect wrapper — returns silent windows as [(start, end), ...]."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from video_clipping.constants import SILENCE_MIN_DURATION_SEC, SILENCE_NOISE_DB

# silencedetect prints to stderr like:
#   [silencedetect @ 0x...] silence_start: 12.345
#   [silencedetect @ 0x...] silence_end: 13.678 | silence_duration: 1.333
_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(
    video: Path,
    noise_db: float = SILENCE_NOISE_DB,
    min_duration_sec: float = SILENCE_MIN_DURATION_SEC,
) -> list[tuple[float, float]]:
    """Return silent windows discovered in the audio track."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i", str(video),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_duration_sec}",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,  # silencedetect may exit non-zero on audio-less inputs; we tolerate that.
    )
    stderr = result.stderr
    starts = [float(m) for m in _START_RE.findall(stderr)]
    ends = [float(m) for m in _END_RE.findall(stderr)]
    # Pair them up in order; if a start has no end (video ends silent), skip it.
    pairs: list[tuple[float, float]] = []
    for s, e in zip(starts, ends):
        if e > s:
            pairs.append((s, e))
    return pairs
