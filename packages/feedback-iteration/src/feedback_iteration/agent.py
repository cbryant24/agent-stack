"""feedback-iteration agent entry point.

The `revise` turn: parse the live brief (free) → parse the feedback items (one
version bump) → validate → [--dry-run stops here, spends nothing] → retrieve
grounding → one Claude mapping/diagnosis call under the budget envelope → apply a
targeted, state-preserving patch (time engine for numbers, surgical splice for
text) → snapshot + version bump + version-log entry → propose durable lessons →
standard run report.

All timing is computed in code; the LLM never produces a number. No DaVinci API,
no delegation. The edit-brief artifact is parsed as a foreign artifact — F&I
imports no sibling package.
"""
from __future__ import annotations

import asyncio
import logging
import re
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

from feedback_iteration.chains import map_and_diagnose
from feedback_iteration.constants import AGENT_NAME, DEFAULT_BUDGET
from feedback_iteration.lessons import propose_lessons
from feedback_iteration.models import (
    FeedbackItem,
    LessonCandidate,
    MappingResult,
    ParsedBrief,
    RevisionResult,
    now_date,
)
from feedback_iteration.parser import parse_brief_file
from feedback_iteration.patcher import (
    Replace,
    apply_patches,
    insert_step,
    replace_heading_timespan,
    replace_timeline_cells,
    retime_text,
    rewrite_step_text,
    set_checkbox,
    substitute_prose_boundaries,
)
from feedback_iteration.retrieval import build_retrieval_query, retrieve_context
from feedback_iteration.time_engine import (
    EngineRow,
    _fmt,
    adjust_section_duration,
    diff,
    set_section_duration,
    shift_section,
)
from feedback_iteration.versioning import (
    build_log_entry,
    bump_version_patch,
    snapshot,
    version_log_patch,
)

logger = logging.getLogger(__name__)

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _split_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        cleaned = _BULLET_RE.sub("", line.strip()).strip()
        if cleaned:
            items.append(cleaned)
    return items


def collect_feedback(inline: str | None, file: str | Path | None) -> list[FeedbackItem]:
    """Batch inline text + an optional --feedback FILE into discrete items.
    A single-line inline note is one item; multi-line input splits per line."""
    raw: list[str] = []
    if inline and inline.strip():
        if "\n" in inline.strip():
            raw += _split_items(inline)
        else:
            raw.append(inline.strip())
    if file:
        raw += _split_items(Path(file).read_text(encoding="utf-8"))
    return [FeedbackItem(index=i, text=t) for i, t in enumerate(raw)]


def _validate(parsed: ParsedBrief) -> list[str]:
    findings: list[str] = []
    if parsed.frontmatter.version is None:
        findings.append("frontmatter has no integer `version:` — version bump will assume 1")
    if not parsed.sections:
        findings.append("no <a id> section anchors found — nothing to revise")
    section_ids = {s.section_id for s in parsed.sections}
    missing = {r.section_id for r in parsed.timeline_rows} - section_ids
    if missing:
        findings.append(f"timeline references anchors with no section block: {sorted(missing)}")
    return findings


def _planned_snapshot_path(parsed: ParsedBrief) -> Path:
    version = parsed.frontmatter.version or 1
    return parsed.path.parent / "versions" / f"{parsed.path.stem}.v{version}.md"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _magnitude_traces_to_feedback(feedback_text: str, quote: str) -> bool:
    """The stated amount must be a NUMBER quoted verbatim from the feedback — this
    is the guard that stops the LLM inventing a duration for fuzzy phrasing."""
    if not quote or not re.search(r"\d", quote):
        return False
    return _norm(quote) in _norm(feedback_text)


def _engine_op(rows: list[EngineRow], section_id: str, spec: Any):
    sign = -1.0 if spec.direction in ("shorter", "earlier") else 1.0
    if spec.op == "adjust_duration":
        return adjust_section_duration(rows, section_id, delta=sign * spec.magnitude_sec)
    if spec.op == "set_duration":
        return set_section_duration(rows, section_id, new_length=spec.magnitude_sec)
    return shift_section(rows, section_id, delta=sign * spec.magnitude_sec)


def _apply_mapping(
    parsed: ParsedBrief, mapping: MappingResult, feedback_by_index: dict[int, str]
) -> tuple[list[Replace], list[str], list[str], list[str], list[LessonCandidate]]:
    """Turn the mapping into a patch list + audit notes. Director state is
    preserved: only touched step text is rewritten; a rewritten checked step is
    unchecked and named as invalidated; a mechanical timestamp cascade preserves
    check state."""
    patches: list[Replace] = []
    applied: list[str] = []
    unresolved: list[str] = []
    invalidated: list[str] = []
    lessons: list[LessonCandidate] = []
    # Pending step rewrites, applied AFTER the cascade is known so a rewrite in a
    # moved section can be retimed (it was authored against the old numbers).
    pending_rewrites: list[tuple[Any, Any, str, str]] = []  # (section, step|None, new_text, fb)
    rewritten_starts: set[int] = set()

    original = [EngineRow(r.section_id, r.start_sec, r.end_sec) for r in parsed.timeline_rows]
    working = list(original)
    time_targets: set[str] = set()

    for item in sorted(mapping.items, key=lambda i: i.feedback_index):
        fb = feedback_by_index.get(item.feedback_index, "")
        if item.lesson_candidate:
            lessons.append(item.lesson_candidate)

        if item.change_type == "unresolved":
            unresolved.append(f'"{fb}" — {item.diagnosis or "could not be confidently mapped"}')
            continue
        if item.change_type == "lesson_only":
            if item.lesson_candidate:
                applied.append(f'"{fb}" → durable lesson proposed (no brief edit)')
            else:
                unresolved.append(f'"{fb}" — marked lesson_only but no lesson produced')
            continue

        section = parsed.section_by_id(item.resolved_anchor) if item.resolved_anchor else None
        if section is None:
            unresolved.append(f'"{fb}" — {item.diagnosis or "no resolvable section anchor"}')
            continue

        if item.change_type == "step_rewrite":
            spec = item.step_rewrite
            if spec is None:
                unresolved.append(f'"{fb}" — step rewrite requested but no new text produced')
                continue
            if spec.target_step_number is not None:
                step = next((s for s in section.steps if s.number == spec.target_step_number), None)
                if step is None:
                    unresolved.append(
                        f'"{fb}" — #{section.section_id} has no step {spec.target_step_number}'
                    )
                    continue
                pending_rewrites.append((section, step, spec.new_text, fb))
                rewritten_starts.add(step.text_span.start)
            else:
                pending_rewrites.append((section, None, spec.new_text, fb))

        elif item.change_type == "time_shift":
            spec = item.time_shift
            if spec is None or not _magnitude_traces_to_feedback(fb, spec.magnitude_source_quote):
                unresolved.append(
                    f'"{fb}" — timing change has no stated amount; re-run with an explicit '
                    f'amount (e.g. "by 2s")'
                )
                continue
            if section.section_id in time_targets:
                unresolved.append(
                    f'"{fb}" — conflicts with an earlier timing change to #{section.section_id}'
                )
                continue
            try:
                cm = _engine_op(working, section.section_id, spec)
            except (ValueError, KeyError) as exc:
                unresolved.append(f'"{fb}" — timing change not applicable: {exc}')
                continue
            working = cm.rows
            time_targets.add(section.section_id)
            applied.append(
                f'"{fb}" → #{section.section_id} {spec.op} {spec.direction} '
                f'{spec.magnitude_sec:.3f}s; downstream sections retimed'
            )

    net = diff(original, working)

    # ── Step rewrites: retime the new text against the net cascade, then patch ─
    def _section_subs(section_id: str) -> list[tuple[float, float]]:
        subs = list(net.boundary_subs)
        change = net.change_for(section_id)
        if change is not None and change.kind == "resized":
            old_len = round(change.old_end - change.old_start, 3)
            new_len = round(change.new_end - change.new_start, 3)
            if old_len != new_len:
                subs.append((old_len, new_len))
        return subs

    for section, step, new_text, fb in pending_rewrites:
        retimed = retime_text(new_text, _section_subs(section.section_id))
        if step is not None:
            patches.append(rewrite_step_text(step, retimed))
            if step.checked:
                patches.append(set_checkbox(step, False))
                invalidated.append(
                    f'#{section.section_id} step {step.number} was checked; revision '
                    f'replaced its text — re-verify'
                )
            applied.append(f'"{fb}" → #{section.section_id} step {step.number} rewritten')
        else:
            next_num = max((s.number or 0 for s in section.steps), default=0) + 1
            patches.append(insert_step(section.steps_region_end, f"- [ ] {next_num}. {retimed}"))
            applied.append(f'"{fb}" → #{section.section_id} new step {next_num} appended')

    # ── Compose the time cascade: authoritative surfaces + prose retiming ─────
    if net.touched:
        for change in net.changes:
            if change.kind == "unchanged":
                continue
            row = parsed.row_by_id(change.section_id)
            if row is not None:
                patches += replace_timeline_cells(
                    row.start_span, row.end_span, _fmt(change.new_start), _fmt(change.new_end)
                )
            section = parsed.section_by_id(change.section_id)
            if section is None:
                continue
            if section.heading_timespan is not None:
                patches.append(
                    replace_heading_timespan(section, _fmt(change.new_start), _fmt(change.new_end))
                )
            # Bounded prose retiming; a manual rewrite already owns its step.
            patches += substitute_prose_boundaries(
                section, _section_subs(change.section_id), skip_spans=rewritten_starts
            )

    return patches, applied, unresolved, invalidated, lessons


async def revise(
    brief_path: str | Path,
    feedback_text: str | None = None,
    *,
    feedback_file: str | Path | None = None,
    max_cost: float | None = None,
    dry_run: bool = False,
    budget: BudgetEnvelope | None = None,
) -> RevisionResult:
    config = get_config()
    parsed = parse_brief_file(brief_path)
    feedback = collect_feedback(feedback_text, feedback_file)
    findings = _validate(parsed)

    version_from = parsed.frontmatter.version
    next_version = (version_from or 1) + 1
    feedback_texts = [f.text for f in feedback]
    section_ids = [s.section_id for s in parsed.sections]

    # ── Dry run: the free op — parse + validate + echo, no LLM, no writes ─────
    if dry_run:
        return RevisionResult(
            brief_path=parsed.path,
            snapshot_path=_planned_snapshot_path(parsed),
            project_id=parsed.project_id,
            section_ids=section_ids,
            feedback_items=feedback_texts,
            version_from=version_from,
            version_to=next_version,
            validation_findings=findings,
            dry_run=True,
            status="completed",
        )

    memory_store = get_memory_store()
    uks = UserKnowledgeStore(memory_store)
    query = build_retrieval_query(feedback, parsed)
    ctx = await retrieve_context(query, memory_store, uks)

    effective_budget = budget if max_cost is None else _with_max_cost(budget or DEFAULT_BUDGET, max_cost)
    effective_budget = effective_budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    mapping = MappingResult()

    try:
        async with BudgetTracker(effective_budget, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            tracker.check_budget()
            mapping = await map_and_diagnose(parsed, feedback, ctx, client)
            tracker.add_item_processed()
    except BudgetExhaustedError:
        status = "partial"

    feedback_by_index = {f.index: f.text for f in feedback}
    patches, applied, unresolved, invalidated, lessons = _apply_mapping(
        parsed, mapping, feedback_by_index
    )
    unresolved = unresolved + [f"(brief-level) {n}" for n in mapping.overall_notations]

    # ── Snapshot → version bump → version-log entry → write in place ──────────
    snapshot_path = snapshot(parsed)
    entry = build_log_entry(
        version=next_version,
        date=now_date(),
        feedback_items=feedback_texts,
        resolutions=applied,
        unresolved=unresolved,
        invalidated=invalidated,
    )
    if "version" in parsed.frontmatter.fields:
        patches.append(bump_version_patch(parsed, next_version))
    patches.append(version_log_patch(parsed, entry))

    new_text = apply_patches(parsed.text, patches)
    parsed.path.write_text(new_text, encoding="utf-8")

    # ── Lessons: propose-only (director gates confirm out of band) ────────────
    source_ref = f"{parsed.project_id or parsed.path.stem}:{parsed.path.name}"
    lesson_draft_ids = await propose_lessons(
        uks, lessons, source_ref=source_ref, feedback_verbatim=feedback_texts
    )

    return _finalize(
        parsed=parsed,
        snapshot_path=snapshot_path,
        section_ids=section_ids,
        feedback_texts=feedback_texts,
        version_from=version_from,
        next_version=next_version,
        applied=applied,
        unresolved=unresolved,
        invalidated=invalidated,
        lesson_draft_ids=lesson_draft_ids,
        findings=findings,
        run_id=run_id,
        status=status,
        tracker_ref=tracker_ref,
    )


def _with_max_cost(budget: BudgetEnvelope, max_cost: float) -> BudgetEnvelope:
    return BudgetEnvelope(
        max_items=budget.max_items,
        max_depth=budget.max_depth,
        max_cost_usd=max_cost,
        max_wall_time_sec=budget.max_wall_time_sec,
    )


def _finalize(
    *,
    parsed: ParsedBrief,
    snapshot_path: Path,
    section_ids: list[str],
    feedback_texts: list[str],
    version_from: int | None,
    next_version: int,
    applied: list[str],
    unresolved: list[str],
    invalidated: list[str],
    lesson_draft_ids: list[str],
    findings: list[str],
    run_id: str,
    status: str,
    tracker_ref: BudgetTracker | None,
) -> RevisionResult:
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

    return RevisionResult(
        brief_path=parsed.path,
        snapshot_path=snapshot_path,
        project_id=parsed.project_id,
        section_ids=section_ids,
        feedback_items=feedback_texts,
        version_from=version_from,
        version_to=next_version,
        applied=applied,
        unresolved=unresolved,
        invalidated_checks=invalidated,
        lesson_draft_ids=lesson_draft_ids,
        validation_findings=findings,
        report_run_path=report_run_path,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall,
    )


def revise_sync(brief_path: str | Path, feedback_text: str | None = None, **kwargs: Any) -> RevisionResult:
    return asyncio.run(revise(brief_path, feedback_text, **kwargs))
