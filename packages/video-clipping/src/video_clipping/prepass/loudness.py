"""ffmpeg ebur128 per candidate window → integrated loudness (LUFS).

Uses the EBU R 128 standard. `astats` returns dB RMS, not LUFS, so it cannot
back the `mean_loudness_lufs` field — ebur128 only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# ebur128 summary block includes lines like:
#   [Parsed_ebur128_0 @ 0x...] Summary:
#     Integrated loudness:
#       I:         -23.0 LUFS
_INTEGRATED_RE = re.compile(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", re.MULTILINE)


def mean_loudness_lufs(video: Path, start: float, duration: float) -> float | None:
    """Return integrated loudness (LUFS) over [start, start+duration], or None on failure."""
    if duration <= 0:
        return None
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-ss", f"{start}",
            "-t", f"{duration}",
            "-i", str(video),
            "-af", "ebur128=peak=true",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    matches = _INTEGRATED_RE.findall(result.stderr)
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except ValueError:
        return None
    # ebur128 reports -inf-like sentinels (e.g. "-70.0") for silence; keep as-is
    # rather than converting to None so a caller can see the actual measurement.
    return value
