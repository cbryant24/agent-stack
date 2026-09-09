"""Build a short synthetic video with scene cuts and known silent windows.

Uses only ffmpeg-lavfi sources so the test suite has no external dependencies
beyond ffmpeg itself.

Layout (~9 seconds total):
  [0.0, 3.0)  testsrc  + sine 440Hz    ← audible scene 1
  [3.0, 4.5)  smptebars + silence      ← scene cut + silent window
  [4.5, 6.0)  smptehdbars + silence    ← another scene cut, still silent
  [6.0, 9.0)  testsrc  + sine 220Hz    ← audible scene 3

The silent middle section lets `silencedetect` find one silence window; the
three visually distinct sources make both scene detectors report at least two
cuts each.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FILTER_COMPLEX = (
    # video sources
    "testsrc=duration=3:size=320x240:rate=15[v0];"
    "smptebars=duration=1.5:size=320x240:rate=15[v1];"
    "smptehdbars=duration=1.5:size=320x240:rate=15[v2];"
    "testsrc=duration=3:size=320x240:rate=15,eq=brightness=-0.3[v3];"
    "[v0][v1][v2][v3]concat=n=4:v=1:a=0[v];"
    # audio sources — silent in the middle
    "sine=frequency=440:duration=3[a0];"
    "anullsrc=r=44100:cl=stereo,atrim=duration=3[a1];"
    "sine=frequency=220:duration=3[a2];"
    "[a0][a1][a2]concat=n=3:v=0:a=1[a]"
)


def generate(path: Path) -> Path:
    """Write the synthetic video to `path` and return it. No-op if already present."""
    if path.exists():
        return path
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to build the synthetic fixture")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-filter_complex", FILTER_COMPLEX,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ],
        check=True,
    )
    return path
