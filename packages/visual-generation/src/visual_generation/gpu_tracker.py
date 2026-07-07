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
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from agent_runtime import get_config

from visual_generation.constants import (
    AGENT_SUBDIR,
    DEFAULT_PER_RUN_MINUTES,
    DEFAULT_PER_RUN_MINUTES_VIDEO,
    GPU_LEDGER_FILENAME,
    RECENT_COST_SAMPLE,
)


def estimate_per_run_cost(
    prior_costs: list[float], rate: float, *, is_video: bool = False
) -> tuple[float, str]:
    """Seed the per-run cost estimate. Returns (usd, source).

    `learned` — mean of the most recent recorded non-zero per-run costs. The caller
    filters `prior_costs` by `workflow_ref` so a video template's estimate is learned
    from prior video runs only, never contaminated by cheap image runs.
    `default` — cold-start: (video ? DEFAULT_PER_RUN_MINUTES_VIDEO : DEFAULT_PER_RUN_MINUTES)
    × rate. Video runs cost 10–30× an image run, so the cold-start is per-modality.
    """
    nonzero = [c for c in prior_costs if c and c > 0]
    if nonzero:
        sample = nonzero[-RECENT_COST_SAMPLE:]
        return sum(sample) / len(sample), "learned"
    minutes = DEFAULT_PER_RUN_MINUTES_VIDEO if is_video else DEFAULT_PER_RUN_MINUTES
    return minutes / 60.0 * rate, "default"


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
