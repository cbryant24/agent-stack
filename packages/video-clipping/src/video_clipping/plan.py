"""plan.json / run.json I/O for the video-clipping pipeline.

`clip draft` writes `plan.json` (immutable pre-generate artifact).
`clip generate` reads plan.json, then writes `run.json` (same Run schema, with
the post-generate fields populated).
"""

from __future__ import annotations

import json
from pathlib import Path

from video_clipping.models import Run

PLAN_FILENAME = "plan.json"
RUN_FILENAME = "run.json"


def load_plan(path: Path) -> Run:
    """Load a `plan.json` written by `clip draft`."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Run.from_payload(raw)


def load_run(path: Path) -> Run:
    """Load a `run.json` written by `clip generate`."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Run.from_payload(raw)


def save_run(run: Run, run_dir: Path) -> Path:
    """Write the completed Run to `<run_dir>/run.json` and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / RUN_FILENAME
    out.write_text(
        json.dumps(run.to_payload(), indent=2, default=str),
        encoding="utf-8",
    )
    return out
