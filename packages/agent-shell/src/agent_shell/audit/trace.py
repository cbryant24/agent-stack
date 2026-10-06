from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ulid import ULID

from agent_runtime.models import TraceEvent


class SessionTrace:
    """Writes the agent-runtime trace format for one session segment.

    Same layout and events as `TracePersister` (runs/<date>/<app>/<run_id>/trace.jsonl with
    `llm_call` events and a `run_end` summary), so scripts/agent_costs.py reads REPL sessions
    unchanged. Kept separate from TracePersister because that locates its files through the
    runtime config, which would differ from the shell's own data dir (and need API keys).
    One segment per `Session.start`, so a resumed session sums correctly by session id.
    """

    def __init__(self, agent_data_dir: Path, app: str, session_id: str) -> None:
        self.app, self.session_id = app, session_id
        self.run_id = str(ULID())
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        d = agent_data_dir / "runs" / date / app / self.run_id
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / "trace.jsonl"
        self._lock = threading.Lock()
        self.cost_usd = 0.0
        self.llm_calls = 0
        self.tool_calls = 0
        self.turns = 0
        self.providers: list[str] = []
        self._write(TraceEvent(event_type="info", metadata={
            "event": "run_start", "agent": app, "run_id": self.run_id, "session_id": session_id,
        }))

    def _write(self, event: TraceEvent) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def llm_call(
        self, model: str, input_tokens: int, output_tokens: int, cost_usd: float, **extra: Any
    ) -> None:
        self.cost_usd += cost_usd
        self.llm_calls += 1
        self._write(TraceEvent(event_type="llm_call", metadata={
            "llm.model": model, "llm.input_tokens": input_tokens,
            "llm.output_tokens": output_tokens, "llm.cost_usd": cost_usd, **extra,
        }))

    def tool_call(self, name: str) -> None:
        self.tool_calls += 1
        self._write(TraceEvent(event_type="tool_call", metadata={"tool": name}))

    def end(self, status: str = "completed") -> None:
        self._write(TraceEvent(event_type="info", metadata={
            "event": "run_end", "agent": self.app, "run_id": self.run_id, "status": status,
            "summary": {
                "cost_usd": self.cost_usd, "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls, "turns": self.turns,
            },
            "envelope": {"session_id": self.session_id},
            "providers": self.providers,
        }))
