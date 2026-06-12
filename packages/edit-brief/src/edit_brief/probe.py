"""ffprobe duration reader.

Durations are read from the audio/video files on disk, never trusted from a
collection's metadata (the handoff's resolved rule). No shared ffprobe helper
exists in the stack, so this is edit-brief's. It degrades to None on any
failure — a missing/unreadable file becomes a "missing input" notation
downstream, never an exception.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def ffprobe_duration(path: str | Path) -> float | None:
    """Return the media duration in seconds, or None if it cannot be read."""
    p = Path(path)
    if not p.is_file():
        logger.debug("ffprobe skipped — not a file: %s", p)
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        logger.warning("ffprobe failed for %s: %s", p, exc)
        return None
    if out.returncode != 0:
        logger.warning("ffprobe non-zero for %s: %s", p, out.stderr.strip())
        return None
    raw = out.stdout.strip()
    try:
        dur = float(raw)
    except ValueError:
        logger.warning("ffprobe gave non-numeric duration for %s: %r", p, raw)
        return None
    return dur if dur > 0 else None
