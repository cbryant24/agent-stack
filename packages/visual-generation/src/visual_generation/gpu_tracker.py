"""Agent-local GPU cost tracking (Q3 — never a Claude BudgetEnvelope dimension).

No RunPod credential in v1 (Q4), so nothing here reads RunPod pricing or balance:

- the **rate** is user-supplied (`--gpu-rate`), falling back to a config default;
- **uptime** is the agent's warm-session wall-clock (first submit → drain), an
  *approximate* proxy for billed uptime (real billing starts at user spin-up,
  before the agent connects);
- the gate's **balance** is a locally-tracked cumulative spend against an OPTIONAL
  user-declared budget (`GpuLedger`), not a live RunPod balance.

The per-run estimate that seeds the gate is learned from prior generations'
recorded `cost_usd` when any exist, else a cold-start config default.

Pod uptime is a second, separate axis: a caller that creates and deletes the pod itself
(the chat's pod tools) records each pod's create-to-delete window as a `pod_uptime` entry.
It is never added to `cumulative_usd`: inference time sits inside uptime, so summing the two
would count it twice.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_runtime import get_config

from visual_generation.constants import (
    AGENT_SUBDIR,
    DEFAULT_PER_RUN_MINUTES,
    GPU_LEDGER_FILENAME,
    RECENT_COST_SAMPLE,
)


POD_UPTIME_ENTRY = "pod_uptime"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def uptime_seconds(started_at: str, ended_at: str) -> float:
    """Seconds between two ISO timestamps (never negative)."""
    return max(0.0, (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds())


def estimate_per_run_cost(prior_costs: list[float], rate: float) -> tuple[float, str]:
    """Seed the per-run cost estimate. Returns (usd, source).

    `learned` — mean of the most recent recorded non-zero per-run costs.
    `default` — cold-start: DEFAULT_PER_RUN_MINUTES × rate (always produces a value).
    """
    nonzero = [c for c in prior_costs if c and c > 0]
    if nonzero:
        sample = nonzero[-RECENT_COST_SAMPLE:]
        return sum(sample) / len(sample), "learned"
    return DEFAULT_PER_RUN_MINUTES / 60.0 * rate, "default"


class GpuLedger:
    """A tiny persisted ledger: cumulative local GPU spend + an optional budget."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_config().agent_data_dir / AGENT_SUBDIR / GPU_LEDGER_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict:
        if not self._path.exists():
            return {"cumulative_usd": 0.0, "declared_budget_usd": None}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def cumulative(self) -> float:
        return float(self._load().get("cumulative_usd", 0.0))

    def declared_budget(self) -> float | None:
        return self._load().get("declared_budget_usd")

    def set_budget(self, usd: float | None) -> None:
        data = self._load()
        data["declared_budget_usd"] = usd
        self._write(data)

    def record_session(self, cost_usd: float) -> None:
        data = self._load()
        data["cumulative_usd"] = float(data.get("cumulative_usd", 0.0)) + max(0.0, cost_usd)
        self._write(data)

    def remaining(self) -> float | None:
        """Declared budget minus cumulative spend, or None if no budget is declared."""
        budget = self.declared_budget()
        if budget is None:
            return None
        return budget - self.cumulative()

    # ── pod uptime (its own entry type; wall-clock UTC so it survives a restart) ──

    def entries(self, entry_type: str | None = None) -> list[dict[str, Any]]:
        rows = list(self._load().get("entries", []))
        return rows if entry_type is None else [r for r in rows if r.get("type") == entry_type]

    def open_pod_entry(self) -> dict[str, Any] | None:
        """The pod_uptime entry that has not been closed yet, if any."""
        for row in reversed(self.entries(POD_UPTIME_ENTRY)):
            if row.get("ended_at") is None:
                return row
        return None

    def open_pod_uptime(
        self, pod_id: str, rate_usd_per_hr: float, *, session_id: str = "",
        started_at: str | None = None, start_observed: bool = True,
    ) -> dict[str, Any]:
        """Start a pod's uptime window. `start_observed=False` marks a pod that was already
        running when it was first seen, so the true start is earlier than `started_at`."""
        data = self._load()
        row: dict[str, Any] = {
            "type": POD_UPTIME_ENTRY, "pod_id": pod_id, "started_at": started_at or _utc_now().isoformat(),
            "ended_at": None, "seconds": None, "rate_usd_per_hr": rate_usd_per_hr, "cost_usd": None,
            "session_id": session_id, "start_observed": start_observed, "end_observed": None,
        }
        data.setdefault("entries", []).append(row)
        self._write(data)
        return row

    def close_pod_uptime(
        self, pod_id: str, *, ended_at: str | None = None, end_observed: bool = True
    ) -> dict[str, Any] | None:
        """Close the open window for `pod_id` and price it. `end_observed=False` marks a pod
        found already gone, so `ended_at` is an upper bound. Returns the entry, or None."""
        data = self._load()
        for row in reversed(data.get("entries", [])):
            if row.get("type") == POD_UPTIME_ENTRY and row.get("pod_id") == pod_id and row.get("ended_at") is None:
                row["ended_at"] = ended_at or _utc_now().isoformat()
                row["seconds"] = uptime_seconds(row["started_at"], row["ended_at"])
                row["cost_usd"] = row["seconds"] / 3600.0 * float(row.get("rate_usd_per_hr") or 0.0)
                row["end_observed"] = end_observed
                self._write(data)
                return dict(row)
        return None

    def pod_uptime_total(self) -> float:
        """USD across every closed pod_uptime entry (kept apart from `cumulative()`)."""
        return sum(float(r.get("cost_usd") or 0.0) for r in self.entries(POD_UPTIME_ENTRY))


class SessionMeter:
    """Times a warm session and converts uptime/per-run wall-clock to cost.

    `clock` is injectable (defaults to time.monotonic) so tests can advance time
    deterministically without sleeping.
    """

    def __init__(self, rate_usd_per_hr: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = rate_usd_per_hr
        self._clock = clock
        self._start: float | None = None
        self._end: float | None = None
        self.run_seconds: list[float] = []

    def begin(self) -> None:
        self._start = self._clock()

    def end(self) -> None:
        self._end = self._clock()

    def add_run(self, seconds: float) -> None:
        self.run_seconds.append(seconds)

    def per_run_cost(self, seconds: float) -> float:
        return seconds / 3600.0 * self._rate

    def uptime_seconds(self) -> float:
        if self._start is None:
            return 0.0
        end = self._end if self._end is not None else self._clock()
        return max(0.0, end - self._start)

    def running_cost(self) -> float:
        """Uptime-so-far × rate (the billed axis is uptime, not per-run sum)."""
        return self.uptime_seconds() / 3600.0 * self._rate

    def session_cost(self) -> float:
        return self.running_cost()
