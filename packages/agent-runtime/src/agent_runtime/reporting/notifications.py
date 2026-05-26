from __future__ import annotations

import subprocess
import sys
from typing import Literal

from agent_runtime.models import BudgetConsumption, BudgetEnvelope


def notify(
    title: str,
    message: str,
    level: Literal["info", "warning", "error"] = "info",
) -> None:
    if sys.platform != "darwin":
        return

    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception:
        pass


def notify_budget_threshold(
    agent: str,
    consumption: BudgetConsumption,
    envelope: BudgetEnvelope,
) -> None:
    warnings: list[str] = []

    if envelope.max_cost_usd and consumption.cost_usd / envelope.max_cost_usd > 0.75:
        pct = int(consumption.cost_usd / envelope.max_cost_usd * 100)
        warnings.append(f"cost {pct}% used")

    if envelope.max_items and consumption.items_processed / envelope.max_items > 0.75:
        pct = int(consumption.items_processed / envelope.max_items * 100)
        warnings.append(f"items {pct}% used")

    if envelope.max_wall_time_sec and consumption.wall_time_sec / envelope.max_wall_time_sec > 0.75:
        pct = int(consumption.wall_time_sec / envelope.max_wall_time_sec * 100)
        warnings.append(f"time {pct}% used")

    if warnings:
        notify(
            f"Agent {agent}: budget warning",
            ", ".join(warnings),
            level="warning",
        )


def notify_run_complete(
    agent: str,
    run_id: str,
    status: str,
    cost_usd: float,
) -> None:
    notify(
        f"Agent {agent}: run {status}",
        f"run_id={run_id[:12]}… cost=${cost_usd:.4f}",
        level="info" if status == "completed" else "warning",
    )
