"""concept-script agent entry points.

Two front doors — `draft` (generative) and `shape` (curation) — both produce a
single editable `script.md`. v1 is stateless: no Qdrant collection, no stores, no
delegation. The only side effect is writing the script file; runtime wiring
(budget, tracing, reporting) mirrors the rest of the stack.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    TracePersister,
    get_config,
    notify_run_complete,
    render_run_report,
)

from concept_script.chains import generate_brief, shape_brief
from concept_script.constants import DEFAULT_BUDGET
from concept_script.models import ConceptResult, VideoBrief
from concept_script.serialize import to_script_md

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT = Path("script.md")


async def _run(
    mode: str,
    produce_brief: Any,
    *,
    budget: BudgetEnvelope | None,
    output: Path | None,
    dry_run: bool,
) -> ConceptResult:
    """Shared run scaffold for both modes.

    `produce_brief` is an async callable taking the AsyncAnthropic client and
    returning a VideoBrief. Handles budget tracking, tracing, file write, and
    the run report.
    """
    config = get_config()
    effective_budget = budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    agent_name = "concept-script"
    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    brief: VideoBrief | None = None
    start = time.monotonic()

    try:
        async with BudgetTracker(effective_budget, agent_name) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=agent_name, run_id=run_id):
                tracker.check_budget()
                if dry_run:
                    brief = VideoBrief(
                        logline=f"(dry run — no generation performed; mode={mode})",
                        sections=[],
                    )
                else:
                    brief = await produce_brief(client)
                    tracker.add_item_processed()
    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec
    else:
        wall_time_sec = time.monotonic() - start

    # Write the artifact (skip on dry-run or if nothing was produced).
    script_path: Path | None = None
    if brief is not None and not dry_run and brief.sections:
        script_path = Path(output) if output else _DEFAULT_OUTPUT
        script_path.write_text(to_script_md(brief), encoding="utf-8")

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, agent_name)
        except FileNotFoundError:
            pass
        notify_run_complete(agent_name, run_id, status, cost_usd)

    return ConceptResult(
        brief=brief if brief is not None else VideoBrief(logline=""),
        script_path=script_path,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


async def draft(
    seeds: str,
    *,
    prior_script: str | None = None,
    budget: BudgetEnvelope | None = None,
    output: Path | None = None,
    dry_run: bool = False,
) -> ConceptResult:
    """Generative mode: sparse seeds (+ optional prior-script reference) -> script.md."""

    async def produce(client: AsyncAnthropic) -> VideoBrief:
        return await generate_brief(seeds, client, prior_script=prior_script)

    return await _run("draft", produce, budget=budget, output=output, dry_run=dry_run)


async def shape(
    transcript: str,
    *,
    budget: BudgetEnvelope | None = None,
    output: Path | None = None,
    dry_run: bool = False,
) -> ConceptResult:
    """Curation mode: a verbatim dictation transcript -> script.md (with cut trailer)."""

    async def produce(client: AsyncAnthropic) -> VideoBrief:
        return await shape_brief(transcript, client)

    return await _run("shape", produce, budget=budget, output=output, dry_run=dry_run)


def draft_sync(seeds: str, **kwargs: Any) -> ConceptResult:
    """Synchronous wrapper for draft()."""
    return asyncio.run(draft(seeds, **kwargs))


def shape_sync(transcript: str, **kwargs: Any) -> ConceptResult:
    """Synchronous wrapper for shape()."""
    return asyncio.run(shape(transcript, **kwargs))
