"""The mapping/diagnosis chain — one whole-revision Claude call.

The LLM's job: map each perceptual feedback item to a section ANCHOR (or surface
it as unresolved), diagnose the change, and emit either rewritten step text or a
timing OPERATION + the amount the director STATED. It is handed the brief's
sections, the computed timeline, and the grounding as fixed facts.

It must NEVER produce, recompute, or alter a timestamp. For a timing request it
names the operation and quotes the director's stated amount; all arithmetic is
done downstream by the pure time engine. Ambiguity is surfaced as `unresolved`,
never guessed. Mirrors edit_brief/chains.py: inline system prompt, the
_record_llm → BudgetTracker bridge, JSON parse with one explicit retry.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from anthropic import AsyncAnthropic

from feedback_iteration.constants import MAX_REVISE_TOKENS, MODEL_REVISE
from feedback_iteration.models import (
    FeedbackItem,
    LessonCandidate,
    MappedItem,
    MappingResult,
    ParsedBrief,
    StepRewriteSpec,
    TimeShiftSpec,
)
from feedback_iteration.retrieval import RetrievedContext

logger = logging.getLogger(__name__)


class MappingParseError(Exception):
    """The mapping response could not be parsed into the required shape."""


_VALID_CHANGE_TYPES = {"step_rewrite", "time_shift", "lesson_only", "unresolved"}
_VALID_OPS = {"adjust_duration", "set_duration", "shift"}
_VALID_DIRECTIONS = {"shorter", "longer", "earlier", "later"}


_SYSTEM_PROMPT = """\
You are the revision assistant for a DIRECTOR-OWNED DaVinci Resolve (free) edit \
brief. The director gives natural-language feedback on a draft edit; you map each \
item to the exact part of the brief it refers to and diagnose the change.

Hard rules:
- You NEVER produce, recompute, or alter a timestamp, duration, or gap. For a \
timing change, name the OPERATION and the AMOUNT THE DIRECTOR STATED, quoting \
their exact words. All arithmetic is done downstream by code. If a timing change \
has no stated amount (e.g. "shave a couple seconds"), mark the item `unresolved` \
and say the amount is missing — do NOT invent a number.
- Map perceptual references ("the drop", "the bridge") to a section by its \
ANCHOR id, using the section names, timestamps, and step content. If you cannot \
confidently map an item, mark it `unresolved` with a diagnosis — NEVER guess a \
target.
- Every recommended edit must be executable in DaVinci Resolve free and \
groundable in the supplied TOOLSET FACTS / TECHNIQUE FINDINGS. Carry any \
finding's toolset-fit note and paid/Studio upgrade flag through VERBATIM.
- A statement referencing THIS project's content ("the bridge", "section 3") is a \
project-scoped fix — revision only, never a lesson. A craft/taste rule that would \
hold for the NEXT project is a `lesson_candidate`.

For each feedback item choose ONE change_type:
- "step_rewrite": rewrite one step's text (give target_step_number) or append a \
new step (target_step_number: null). new_text is the step body only (no checkbox, \
no leading number).
- "time_shift": resize or move a section. op is one of adjust_duration (change \
length by the stated amount), set_duration (set length to the stated amount), or \
shift (move start by the stated amount without resizing). magnitude_sec is the \
director's stated number; magnitude_source_quote is the verbatim phrase it came \
from; direction is shorter/longer (resize) or earlier/later (shift).
- "lesson_only": no edit to this brief, only a durable lesson.
- "unresolved": cannot map, or a timing change with no stated amount.

A lesson_candidate may accompany any item when the feedback implies a durable \
craft preference.

Respond with EXACTLY this JSON and nothing else:
{
  "items": [
    {
      "feedback_index": 0,
      "change_type": "step_rewrite | time_shift | lesson_only | unresolved",
      "resolved_anchor": "<section_id or null>",
      "diagnosis": "why this maps here, or why it cannot",
      "step_rewrite": {"target_step_number": 8, "new_text": "..."} ,
      "time_shift": {"op": "adjust_duration", "magnitude_sec": 2.0, "magnitude_source_quote": "...", "direction": "shorter"},
      "lesson_candidate": {"statement": "...", "confidence": "medium"}
    }
  ],
  "overall_notations": ["any knowledge gap surfaced while diagnosing"]
}
Include only the sub-objects relevant to each item; use null otherwise. Cover \
every feedback item exactly once, by its index.
"""

_RETRY_SUFFIX = (
    "Your previous response was not valid JSON in the required shape. Reply again "
    "with ONLY the JSON object: a top-level `items` array of "
    "{feedback_index, change_type, resolved_anchor, diagnosis, step_rewrite, "
    "time_shift, lesson_candidate} plus `overall_notations`. No prose, no fences."
)


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    from agent_runtime.budget import get_current_tracker
    from agent_runtime.tracing import record_llm_call

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        record_llm_call(model, input_tokens, output_tokens, 0.0)


def _build_user_message(
    parsed: ParsedBrief, feedback: list[FeedbackItem], ctx: RetrievedContext
) -> str:
    parts: list[str] = [f"Project: {parsed.project_id or '(unknown)'}", ""]

    parts.append("=== FEEDBACK ITEMS (map each by index) ===")
    for f in feedback:
        parts.append(f"[{f.index}] {f.text}")
    parts.append("")

    parts.append("=== BRIEF SECTIONS (anchors + current timing — fixed facts) ===")
    for s in parsed.sections:
        span = (
            f"  {s.start_sec:.3f}s → {s.end_sec:.3f}s"
            if s.start_sec is not None and s.end_sec is not None
            else ""
        )
        parts.append(f'#{s.section_id} "{s.heading_text}"{span}')
        for step in s.steps:
            box = "x" if step.checked else " "
            num = f"{step.number}. " if step.number is not None else ""
            parts.append(f"  - [{box}] {num}{step.text}")
        parts.append("")

    parts.append("=== TOOLSET FACTS (DaVinci Resolve free — the only toolset source) ===")
    parts += [f"- {t}" for t in ctx.toolset] or ["(none loaded)"]
    parts.append("")

    parts.append("=== TECHNIQUE FINDINGS (carry fit/upgrade verbatim) ===")
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
        parts.append("(no technique findings retrieved — name the gap if one is needed)")
    parts.append("")

    if ctx.tutorial:
        parts.append("=== TUTORIAL MATERIAL (supporting) ===")
        parts += [f"- {t}" for t in ctx.tutorial]
        parts.append("")

    if ctx.preferences:
        parts.append("=== DIRECTOR PREFERENCES (honour these) ===")
        parts += [f"- {p}" for p in ctx.preferences]
        parts.append("")

    parts.append(
        "Map and diagnose every feedback item now. Never produce a number; for a "
        "timing change name the operation and quote the director's stated amount."
    )
    return "\n".join(parts)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time_shift(raw: Any) -> TimeShiftSpec | None:
    if not isinstance(raw, dict):
        return None
    op = raw.get("op")
    mag = _coerce_float(raw.get("magnitude_sec"))
    direction = raw.get("direction")
    if op not in _VALID_OPS or mag is None or direction not in _VALID_DIRECTIONS:
        return None
    return TimeShiftSpec(
        op=op,
        magnitude_sec=mag,
        magnitude_source_quote=str(raw.get("magnitude_source_quote", "")).strip(),
        direction=direction,
    )


def _parse_step_rewrite(raw: Any) -> StepRewriteSpec | None:
    if not isinstance(raw, dict):
        return None
    new_text = str(raw.get("new_text", "")).strip()
    if not new_text:
        return None
    num = raw.get("target_step_number")
    target = int(num) if isinstance(num, (int, float)) else None
    return StepRewriteSpec(target_step_number=target, new_text=new_text)


def _parse_lesson(raw: Any) -> LessonCandidate | None:
    if not isinstance(raw, dict):
        return None
    statement = str(raw.get("statement", "")).strip()
    if not statement:
        return None
    return LessonCandidate(statement=statement, confidence=str(raw.get("confidence", "medium")).strip() or "medium")


def _parse(response: Any) -> MappingResult:
    text = response.content[0].text if response.content else ""
    data = _json_from_text(text)
    items: list[MappedItem] = []
    for raw in data.get("items", []):
        if not isinstance(raw, dict):
            continue
        change_type = raw.get("change_type")
        if change_type not in _VALID_CHANGE_TYPES:
            change_type = "unresolved"
        anchor = raw.get("resolved_anchor")
        items.append(
            MappedItem(
                feedback_index=int(raw.get("feedback_index", len(items))),
                change_type=change_type,
                resolved_anchor=str(anchor) if anchor else None,
                diagnosis=str(raw.get("diagnosis", "")).strip(),
                step_rewrite=_parse_step_rewrite(raw.get("step_rewrite")),
                time_shift=_parse_time_shift(raw.get("time_shift")),
                lesson_candidate=_parse_lesson(raw.get("lesson_candidate")),
            )
        )
    overall = [str(x).strip() for x in data.get("overall_notations", []) if str(x).strip()]
    return MappingResult(items=items, overall_notations=overall)


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
        raise MappingParseError(str(exc)) from exc
    if not isinstance(data, dict):
        raise MappingParseError("top-level JSON is not an object")
    return data


async def map_and_diagnose(
    parsed: ParsedBrief,
    feedback: list[FeedbackItem],
    ctx: RetrievedContext,
    client: AsyncAnthropic,
) -> MappingResult:
    """Map feedback to anchors + diagnose. One Claude call, one retry on a parse
    failure."""
    user_message = _build_user_message(parsed, feedback, ctx)

    response = await client.messages.create(
        model=MODEL_REVISE,
        max_tokens=MAX_REVISE_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_REVISE, response.usage.input_tokens, response.usage.output_tokens)

    try:
        return _parse(response)
    except MappingParseError:
        logger.warning("Mapping response unparseable; retrying once with a reminder")
        retry = await client.messages.create(
            model=MODEL_REVISE,
            max_tokens=MAX_REVISE_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text if response.content else ""},
                {"role": "user", "content": _RETRY_SUFFIX},
            ],
        )
        _record_llm(MODEL_REVISE, retry.usage.input_tokens, retry.usage.output_tokens)
        return _parse(retry)
