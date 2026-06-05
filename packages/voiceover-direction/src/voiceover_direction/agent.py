"""voiceover-direction agent entry point — the `direct` free loop.

`direct` parses an input script, composes retrieval across the three collections,
runs the whole-script direction chain, and writes an editable directed-script file.
LLM-only: no ElevenLabs call, no TTS, no character budget. Free and re-runnable.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    MemoryStore,
    TracePersister,
    UserKnowledgeStore,
    get_config,
    get_memory_store,
    notify_run_complete,
    render_run_report,
)

from voiceover_direction.chains import direct_script
from voiceover_direction.constants import DEFAULT_BUDGET
from voiceover_direction.directed_script import write_directed_script
from voiceover_direction.models import DirectedScript, DirectionResult
from voiceover_direction.parser import parse_script
from voiceover_direction.retrieval import retrieve_context
from voiceover_direction.store import VoiceoverDirectionStore

logger = logging.getLogger(__name__)

AGENT_NAME = "voiceover-direction"


def _get_stores() -> tuple[VoiceoverDirectionStore, MemoryStore, UserKnowledgeStore]:
    ms = get_memory_store()
    store = VoiceoverDirectionStore(ms)
    knowledge = UserKnowledgeStore(ms)
    return store, ms, knowledge


def _default_output_path(script_path: Path) -> Path:
    return script_path.with_suffix("").with_suffix(".directed.md")


async def direct(
    script_path: str | Path,
    *,
    budget: BudgetEnvelope | None = None,
    output_path: str | Path | None = None,
    project_id: str | None = None,
    domain: str | None = None,
    dry_run: bool = False,
) -> DirectionResult:
    """Direct a whole script: retrieve context, run the chain, write the directed file.

    The script is parsed with the Step 1 heading parser; section identity is the
    heading slug. Voices are picked from the local registry (empty registry is fine —
    the chain leaves voice_id unset and notes the desired characteristics).
    """
    config = get_config()
    effective_budget = budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    store, memory_store, _knowledge = _get_stores()
    await store.ensure_collection()

    script_path = Path(script_path)
    out_path = Path(output_path) if output_path is not None else _default_output_path(script_path)
    parsed = parse_script(script_path)
    resolved_project_id = project_id or script_path.stem

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    cost_usd = 0.0
    items_processed = 0
    wall_time_sec = 0.0

    directed_sections = []
    overall_reasoning = ""

    try:
        async with BudgetTracker(effective_budget, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                tracker.check_budget()
                # Query is the whole script's prose — direction is whole-script.
                query = "\n".join(s.body for s in parsed.sections) or resolved_project_id
                ctx = await retrieve_context(query, store, memory_store, include_tutorial=True)

                voices = store.list_voices()

                tracker.check_budget()
                if dry_run:
                    overall_reasoning = "Dry run: would direct the script (no LLM call)."
                else:
                    directed_sections, overall_reasoning = await direct_script(
                        parsed, voices, ctx, client
                    )
                    tracker.add_item_processed()
                    items_processed = 1

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    directed = DirectedScript(
        project_id=resolved_project_id,
        domain=domain,
        sections=directed_sections,
        source_path=str(script_path),
    )

    written_path: Path | None = None
    if not dry_run and directed_sections:
        write_directed_script(directed, out_path)
        written_path = out_path

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass
        notify_run_complete(AGENT_NAME, run_id, status, cost_usd)

    return DirectionResult(
        directed_script=directed,
        output_path=written_path,
        overall_reasoning=overall_reasoning,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        items_processed=items_processed,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def direct_sync(script_path: str | Path, **kwargs: Any) -> DirectionResult:
    """Synchronous wrapper for direct()."""
    return asyncio.run(direct(script_path, **kwargs))
