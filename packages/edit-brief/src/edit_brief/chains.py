"""The synthesis chain — one whole-brief Claude call.

The LLM's job is narrow and load-bearing in exactly one direction: place the
retrieved technique findings against the COMPUTED grids and emit per-section
ordered checkbox steps a director can execute in DaVinci Resolve free, in order,
without leaving the document. It is handed the timeline timestamps and beat
proposals as GIVEN FACTS and must never produce or alter a number. Every
instruction must be groundable in the supplied toolset/findings; gaps are named,
never filled.

Mirrors voiceover-direction/chains.py: inline system prompt, the _record_llm →
BudgetTracker bridge, JSON parse with a single explicit retry.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from anthropic import AsyncAnthropic

from edit_brief.constants import MAX_BRIEF_TOKENS, MODEL_BRIEF
from edit_brief.models import BeatGrid, DiscoveredAsset, SectionSteps, TimelineRow
from edit_brief.retrieval import RetrievedContext

logger = logging.getLogger(__name__)


class BriefParseError(Exception):
    """The synthesis response could not be parsed into section steps."""


_SYSTEM_PROMPT = """\
You are an expert video editor's assistant preparing a DIRECTOR-OWNED execution \
brief for a DaVinci Resolve (free version) edit session. The director does the \
editing; you write the ordered, do-this-now checklist.

Hard rules:
- You are given each section's start/end TIMESTAMPS and the beat-grid PROPOSALS \
as fixed facts. NEVER invent, recompute, or change a timestamp, duration, BPM, \
or beat number. Refer to the numbers you are given, verbatim.
- Every instruction MUST be executable in DaVinci Resolve free and groundable in \
the provided TOOLSET FACTS and TECHNIQUE FINDINGS. If a section needs a technique \
not covered by the supplied knowledge, do NOT invent guidance — add a notation \
naming the gap (e.g. "no findings on color grading — run technique-research").
- Carry any finding's toolset-fit note and paid/Studio upgrade flag through \
VERBATIM when you use that finding.
- For footage/assets: generated assets (with a prompt/intent) you may map to the \
section they fit; director footage you SURFACE as ranked candidates for the \
director to pick — never decide the final pick.

For each section, produce an ORDERED list of steps. Each step is a single \
imperative action: which file, which timestamp (from the facts), which Resolve \
page/tool (Cut/Edit/Fairlight/Color/Deliver), what to do. Keep steps concrete \
and in execution order.

Respond with EXACTLY this JSON and nothing else:
{
  "sections": [
    {
      "section_id": "<verbatim id from the input>",
      "steps": ["place the VO file … on the timeline at 0.0s", "..."],
      "notations": ["any named gap or surfaced ambiguity for this section"]
    }
  ],
  "overall_notations": ["any brief-level gap or note"]
}
Preserve every section_id exactly. Order sections as given.
"""

_RETRY_SUFFIX = (
    "Your previous response was not valid JSON in the required shape. Reply again "
    "with ONLY the JSON object: a top-level `sections` array of "
    "{section_id, steps, notations} plus `overall_notations`. No prose, no fences."
)


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route LLM cost through the active BudgetTracker when present."""
    from agent_runtime.budget import get_current_tracker
    from agent_runtime.tracing import record_llm_call

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        record_llm_call(model, input_tokens, output_tokens, 0.0)


def _fmt_ts(sec: float) -> str:
    """Whole-second-friendly mm:ss.mmm style is overkill here — keep raw seconds
    so the LLM echoes the exact number it was given."""
    return f"{sec:.3f}s"


def _build_user_message(
    project_id: str,
    timeline: list[TimelineRow],
    beat_grid: BeatGrid | None,
    ctx: RetrievedContext,
    assets: list[DiscoveredAsset],
) -> str:
    parts: list[str] = [f"Project: {project_id}", ""]

    parts.append("=== TIMELINE (computed — fixed facts) ===")
    for r in timeline:
        est = " [ESTIMATED — no VO take, timestamp is approximate]" if r.timing_source == "estimate" else ""
        vo = f" | VO: {r.vo_file}" if r.vo_file else " | VO: (none)"
        parts.append(
            f"[{r.section_id}] \"{r.heading}\"  {_fmt_ts(r.start_sec)} → "
            f"{_fmt_ts(r.end_sec)}{vo}{est}"
        )
    parts.append("")

    if beat_grid is not None:
        parts.append(
            f"=== BEAT GRID (computed — BPM {beat_grid.bpm}, beat "
            f"{beat_grid.beat_sec:.3f}s, bar {beat_grid.bar_sec:.3f}s) ==="
        )
        parts.append("Nearest-beat PROPOSALS at each section boundary (director chooses):")
        for bp in beat_grid.boundary_proposals:
            parts.append(
                f"[{bp.section_id}] boundary {_fmt_ts(bp.boundary_sec)} → "
                f"nearest beat {_fmt_ts(bp.nearest_beat_sec)} / nearest bar "
                f"{_fmt_ts(bp.nearest_bar_sec)}"
            )
        if beat_grid.note:
            parts.append(f"Note: {beat_grid.note}")
        parts.append("")
    else:
        parts.append("=== BEAT GRID === none (no BPM available — omit beat-aligned steps)")
        parts.append("")

    parts.append("=== TOOLSET FACTS (DaVinci Resolve free + tools — the only toolset source) ===")
    parts += [f"- {t}" for t in ctx.toolset] or ["(none loaded)"]
    parts.append("")

    parts.append("=== TECHNIQUE FINDINGS (the only technique source — carry fit/upgrade verbatim) ===")
    if ctx.findings:
        for f in ctx.findings:
            line = f"- {f.technique}: {f.description}"
            if f.application_notes:
                line += f" | apply: {f.application_notes}"
            if f.toolset_fit:
                line += f" | toolset fit: {f.toolset_fit}"
            if f.upgrade_flag:
                line += f" | ⬆ paid/Studio: {f.upgrade_flag}"
            parts.append(line)
    else:
        parts.append("(no technique findings retrieved — name the gap per section)")
    parts.append("")

    if ctx.tutorial:
        parts.append("=== TUTORIAL MATERIAL (supporting) ===")
        parts += [f"- {t}" for t in ctx.tutorial]
        parts.append("")

    if ctx.preferences:
        parts.append("=== DIRECTOR PREFERENCES (honour these) ===")
        parts += [f"- {p}" for p in ctx.preferences]
        parts.append("")

    parts.append("=== AVAILABLE ASSETS ===")
    gen = [a for a in assets if a.kind == "generated"]
    footage = [a for a in assets if a.kind == "footage"]
    if gen:
        parts.append("Generated (map to the section it fits — has intent):")
        for a in gen:
            parts.append(f"- {a.path} | intent: {a.prompt or a.description or '(none)'}")
    if footage:
        parts.append("Director footage (SURFACE as ranked candidates — never decide):")
        for a in footage:
            desc = f" | {a.description}" if a.description else ""
            dur = f" | {a.duration_sec:.1f}s" if a.duration_sec else ""
            parts.append(f"- {a.path}{desc}{dur}")
    if not gen and not footage:
        parts.append("(no assets discovered — note where footage is needed)")
    parts.append("")

    parts.append(
        "Write the per-section ordered steps now. Use the exact timestamps above. "
        "Ground every instruction in the toolset facts and findings; name any gap."
    )
    return "\n".join(parts)


def _parse(response: Any, section_ids: list[str]) -> tuple[list[SectionSteps], list[str]]:
    text = response.content[0].text if response.content else ""
    data = _json_from_text(text)
    raw_sections = data.get("sections", [])
    by_id = {s.get("section_id"): s for s in raw_sections if isinstance(s, dict)}

    sections: list[SectionSteps] = []
    headings_unknown = ""  # heading filled by the caller from the timeline
    for sid in section_ids:
        s = by_id.get(sid, {})
        steps = [str(x).strip() for x in s.get("steps", []) if str(x).strip()]
        notations = [str(x).strip() for x in s.get("notations", []) if str(x).strip()]
        sections.append(
            SectionSteps(section_id=sid, heading=headings_unknown, steps=steps, notations=notations)
        )
    overall = [str(x).strip() for x in data.get("overall_notations", []) if str(x).strip()]
    return sections, overall


def _json_from_text(text: str) -> dict[str, Any]:
    """Extract the JSON object, tolerating ```json fences and surrounding prose."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    if not fenced:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise BriefParseError(str(exc)) from exc
    if not isinstance(data, dict):
        raise BriefParseError("top-level JSON is not an object")
    return data


async def synthesize_sections(
    project_id: str,
    timeline: list[TimelineRow],
    beat_grid: BeatGrid | None,
    ctx: RetrievedContext,
    assets: list[DiscoveredAsset],
    client: AsyncAnthropic,
) -> tuple[list[SectionSteps], list[str]]:
    """Emit per-section ordered steps + brief-level notations. One Claude call,
    one explicit retry on a parse failure."""
    section_ids = [r.section_id for r in timeline]
    user_message = _build_user_message(project_id, timeline, beat_grid, ctx, assets)

    response = await client.messages.create(
        model=MODEL_BRIEF,
        max_tokens=MAX_BRIEF_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_BRIEF, response.usage.input_tokens, response.usage.output_tokens)

    try:
        sections, overall = _parse(response, section_ids)
    except BriefParseError:
        logger.warning("Brief response unparseable; retrying once with a reminder")
        retry = await client.messages.create(
            model=MODEL_BRIEF,
            max_tokens=MAX_BRIEF_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text if response.content else ""},
                {"role": "user", "content": _RETRY_SUFFIX},
            ],
        )
        _record_llm(MODEL_BRIEF, retry.usage.input_tokens, retry.usage.output_tokens)
        sections, overall = _parse(retry, section_ids)

    # Fill headings from the computed timeline (authoritative, not the LLM).
    heading_by_id = {r.section_id: r.heading for r in timeline}
    for s in sections:
        s.heading = heading_by_id.get(s.section_id, s.section_id)
    return sections, overall
