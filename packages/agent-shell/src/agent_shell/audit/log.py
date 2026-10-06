from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only JSONL: one record per tool call.

    Lives beside the runtime trace: runs/<date>/<app>/<session_id>/audit.jsonl.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_session(cls, agent_data_dir: Path, app: str, session_id: str) -> AuditLog:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        return cls(agent_data_dir / "runs" / date / app / session_id / "audit.jsonl")

    def record(self, **fields: Any) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), **fields}
        line = json.dumps(entry, default=str) + "\n"
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line)

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x]
