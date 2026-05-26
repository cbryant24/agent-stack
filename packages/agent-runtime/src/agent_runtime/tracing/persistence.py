from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_runtime.models import TraceEvent


class TracePersister:
    def __init__(self, agent: str, run_id: str) -> None:
        self.agent = agent
        self.run_id = run_id
        self._lock = threading.Lock()
        self._file: Any = None
        self._path: Path | None = None

    def _build_path(self) -> Path:
        from agent_runtime.config import get_config
        config = get_config()
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        path = config.agent_data_dir / "runs" / date_str / self.agent / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path / "trace.jsonl"

    def __enter__(self) -> TracePersister:
        self._path = self._build_path()
        self._file = open(self._path, "a", encoding="utf-8")
        return self

    def __exit__(self, *_: Any) -> None:
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None

    def record(self, event: TraceEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self._lock:
            if self._file:
                self._file.write(line)
                self._file.flush()


def load_trace(run_id: str, agent: str, date: str | None = None) -> list[TraceEvent]:
    from agent_runtime.config import get_config
    config = get_config()
    runs_dir = config.agent_data_dir / "runs"

    candidates: list[Path] = []
    if date:
        p = runs_dir / date / agent / run_id / "trace.jsonl"
        if p.exists():
            candidates.append(p)
    else:
        for date_dir in sorted(runs_dir.iterdir(), reverse=True):
            p = date_dir / agent / run_id / "trace.jsonl"
            if p.exists():
                candidates.append(p)

    if not candidates:
        return []

    events: list[TraceEvent] = []
    for path in candidates:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(TraceEvent.model_validate_json(line))
    return events
