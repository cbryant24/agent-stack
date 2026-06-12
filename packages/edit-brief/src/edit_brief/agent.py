"""edit-brief agent entry point.

The `draft` turn: parse the script → discover artifacts by project_id (free) →
compute the timeline + beat grid in code (free, pure) → retrieve toolset/findings
→ synthesize per-section ordered steps (the one Claude call) → render and write
`edit-brief.md` next to the script → standard run report. `--dry-run` stops after
the free discovery + computed grids: it prints the degradation picture and spends
nothing.

All timing is computed in code; the LLM never produces a number. No DaVinci API,
no delegation.
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
    UserKnowledgeStore,
    get_config,
    get_memory_store,
    notify_run_complete,
    render_run_report,
)

from edit_brief.brief import assemble_brief, render_brief
from edit_brief.chains import synthesize_sections
from edit_brief.constants import (
    AGENT_NAME,
    DEFAULT_BUDGET,
    DEFAULT_GAP_SEC,
    DEFAULT_WORDS_PER_SEC,
)
from edit_brief.discovery import discover_inputs
from edit_brief.models import BriefResult, DiscoveredInputs, EditBrief, SectionSteps, TimelineRow
from edit_brief.parser import ParsedScript, ScriptSection, parse_script
from edit_brief.retrieval import retrieve_context
from edit_brief.time_engine import build_beat_grid, section_timestamps

logger = logging.getLogger(__name__)


def _build_timeline(
    sections: list[ScriptSection],
    inputs: DiscoveredInputs,
    gap: float,
    words_per_sec: float,
) -> list[TimelineRow]:
    dur_by_section = {t.section_id: t.duration_sec for t in inputs.vo_takes}
    file_by_section = {t.section_id: t.audio_path for t in inputs.vo_takes}
    rows = section_timestamps(
        [(s.section_id, s.heading) for s in sections],
        durations=[dur_by_section.get(s.section_id) for s in sections],
        word_counts=[s.word_count for s in sections],
        gap=gap,
        words_per_sec=words_per_sec,
    )
    for r in rows:
        path = file_by_section.get(r.section_id)
        if path:
            r.vo_file = Path(path).name
    return rows


def _retrieval_query(parsed: ParsedScript) -> str:
    """A compact query for the knowledge legs — the script's headings + music
    hint capture the editing territory without an LLM."""
    parts = [s.heading for s in parsed.sections]
    if parsed.music_hint:
        parts.append(parsed.music_hint)
    return " · ".join(parts) or "video edit"


def _empty_brief(project_id: str, source_path: str | None, inputs: DiscoveredInputs) -> EditBrief:
    return EditBrief(
        project_id=project_id,
        provenance=inputs,
        notations=["Script has no markdown headings — no sections to brief."],
        source_path=source_path,
    )


async def draft(
    script_path: str | Path,
    *,
    footage: str | None = None,
    music: str | None = None,
    bpm: int | None = None,
    gap: float = DEFAULT_GAP_SEC,
    words_per_sec: float = DEFAULT_WORDS_PER_SEC,
    project_id: str | None = None,
    output_path: str | Path | None = None,
    budget: BudgetEnvelope | None = None,
    dry_run: bool = False,
) -> BriefResult:
    config = get_config()
    script_path = Path(script_path)
    parsed = parse_script(script_path)
    pid = project_id or script_path.stem

    memory_store = get_memory_store()
    uks = UserKnowledgeStore(memory_store)

    section_ids = [s.section_id for s in parsed.sections]

    # ── Discovery (free) + the computed grids (free, pure code) ───────────────
    inputs = await discover_inputs(
        memory_store,
        project_id=pid,
        section_ids=section_ids,
        music_hint=parsed.music_hint,
        footage_dir=footage,
        music_file=music,
        bpm=bpm,
    )

    if not parsed.sections:
        return BriefResult(
            brief=_empty_brief(pid, str(script_path), inputs), dry_run=dry_run, status="completed"
        )

    timeline = _build_timeline(parsed.sections, inputs, gap, words_per_sec)
    beat_grid = build_beat_grid(
        inputs.music.bpm,
        [(r.section_id, r.start_sec) for r in timeline],
        track_duration=inputs.music.duration_sec,
    )
    ctx = await retrieve_context(_retrieval_query(parsed), memory_store, uks)

    # ── Dry run: the free op — no LLM, no file. Show the degradation picture. ──
    if dry_run:
        brief = assemble_brief(
            pid, str(script_path), inputs, timeline, beat_grid, [], ctx, []
        )
        return BriefResult(brief=brief, dry_run=True, status="completed")

    # ── Full run: synthesis (the one spend) under the budget envelope ─────────
    effective_budget = budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    sections: list[SectionSteps] = []
    overall: list[str] = []

    try:
        async with BudgetTracker(effective_budget, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            tracker.check_budget()
            sections, overall = await synthesize_sections(
                pid, timeline, beat_grid, ctx, inputs.assets, client
            )
            tracker.add_item_processed()
    except BudgetExhaustedError:
        status = "partial"

    brief = assemble_brief(
        pid, str(script_path), inputs, timeline, beat_grid, sections, ctx, overall
    )
    brief_path = _write_brief(brief, script_path, output_path)
    return _finalize(brief, brief_path, run_id, status, tracker_ref)


def _write_brief(
    brief: EditBrief, script_path: Path, output_path: str | Path | None
) -> Path:
    if output_path is not None:
        path = Path(output_path)
        if path.is_dir():
            path = path / f"{brief.project_id}.edit-brief.md"
    else:
        # Written next to the script (the evolved artifact convention).
        path = script_path.with_name(f"{script_path.stem}.edit-brief.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_brief(brief), encoding="utf-8")
    return path


def _finalize(
    brief: EditBrief,
    brief_path: Path,
    run_id: str,
    status: str,
    tracker_ref: BudgetTracker | None,
) -> BriefResult:
    cost_usd = wall = 0.0
    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd, wall = snap.cost_usd, snap.wall_time_sec

    report_run_path: Path | None = None
    if run_id:
        try:
            report_run_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass
        notify_run_complete(AGENT_NAME, run_id, status, cost_usd)

    return BriefResult(
        brief=brief,
        brief_path=brief_path,
        report_run_path=report_run_path,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall,
    )


def draft_sync(script_path: str | Path, **kwargs: Any) -> BriefResult:
    return asyncio.run(draft(script_path, **kwargs))
