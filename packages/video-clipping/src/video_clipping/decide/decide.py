"""Stage 4 — structured decision on one segment.

Mirrors `visual_generation/chains.py` structured-output pattern:
1. System prompt spells out the JSON exemplar.
2. `provider.complete(...)` → strip an optional ```json fence → json.loads
   → ClipDecision.model_validate.
3. On JSONDecodeError or ValidationError, retry once with a suffix and re-parse.
4. Final failure → DecisionParseError, caught by the orchestrator.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.llm import LLMProvider
from pydantic import ValidationError

from video_clipping.constants import DECIDE_MAX_TOKENS, PHASE1_MODEL_ID
from video_clipping.exceptions import DecisionParseError
from video_clipping.models import ClipDecision, Segment, Spec
from video_clipping.vision.summarize import _record_llm  # shared cost-bridge

_JSON_FENCE_OPEN = "```json"
_JSON_FENCE_ALT = "```"
_JSON_FENCE_CLOSE = "```"

_RETRY_SUFFIX = (
    "\n\nYour previous reply did not parse as valid JSON matching the schema. "
    "Return exactly one JSON object matching the schema, with no prose, no code "
    "fences, and no additional keys."
)


def _system_prompt(spec: Spec) -> str:
    exclude_options = list(spec.exclude_when) or [
        "low_video_quality", "short_or_long", "low_audio_quality",
        "theme_mismatch", "duplicate_of_previous", "unidentifiable",
    ]
    exclude_options_str = ", ".join(f'"{r}"' for r in exclude_options)
    lo, hi = spec.target_clip_length_sec
    return f"""You are the decision agent for a video-highlight pipeline.

For ONE candidate segment, decide whether to include it, exclude it, or trim
its boundaries. Weigh the director spec, the pre-pass metrics, the transcript,
the visual summary, and any prior-accepted summaries (to avoid duplicates).

Return STRICT JSON of this exact shape — no prose, no code fences, no extra keys:

{{
  "action":            "include" | "exclude" | "trim",
  "refined_start":     <float seconds within the segment window>,
  "refined_end":       <float seconds within the segment window>,
  "exclude_reason":    one of [{exclude_options_str}]  OR null,
  "theme_match":       <float 0..1 — how well the content matches content_wanted>,
  "confidence":        <float 0..1 — your confidence in this decision>,
  "one_line_summary":  "<12-word max summary of the segment content>"
}}

Rules:
- action "trim" means keep the segment but adjust refined_start/refined_end to
  tighten the window. action "include" keeps the pre-pass window as-is.
- exclude_reason MUST be non-null iff action == "exclude". For include/trim,
  exclude_reason MUST be null.
- refined_start and refined_end must lie within the pre-pass segment window
  and satisfy refined_start < refined_end.
- Target clip length is {lo:.1f}–{hi:.1f}s. Prefer trims that land in that band.
- Never invent a "duplicate_of_previous" exclusion — that's handled downstream.
- one_line_summary is used for downstream duplicate detection; make it specific
  and factual (subjects + setting + action), not evaluative.
"""


def _user_message(
    spec: Spec,
    seg: Segment,
    prior_accepted_summaries: list[str],
    prior_lessons: list[str] | None = None,
) -> str:
    prior = (
        "\n".join(f"- {s}" for s in prior_accepted_summaries)
        if prior_accepted_summaries
        else "(none)"
    )
    lessons_block = ""
    if prior_lessons:
        lesson_lines = "\n".join(f"- {s}" for s in prior_lessons)
        lessons_block = (
            "\n"
            "PRIOR LESSONS FOR THIS EVENT TYPE (from previous runs — soft guidance, not rules)\n"
            "-------------------------------------------------------------------------------\n"
            f"{lesson_lines}\n"
        )
    return f"""SPEC
----
location: {spec.location}
event_type: {spec.event_type}
target_clip_length_sec: {spec.target_clip_length_sec}
max_total_output_min: {spec.max_total_output_min}
content_wanted:
{chr(10).join(f'  - {c}' for c in spec.content_wanted) or '  (none)'}
tone_notes: {spec.tone_notes or '(none)'}

SEGMENT
-------
segment_id: {seg.segment_id}
window: [{seg.start:.2f}s → {seg.end:.2f}s]   duration: {seg.duration:.2f}s
mean_loudness_lufs: {seg.mean_loudness_lufs}
detector_provenance: {seg.detector_provenance}
length_status: {seg.length_status}

TRANSCRIPT
----------
{seg.transcript or '(no speech in this window)'}

VISUAL SUMMARY
--------------
{seg.visual_summary or '(vision summary missing)'}

PREVIOUSLY-ACCEPTED SEGMENTS (avoid content duplicates)
------------------------------------------------------
{prior}
{lessons_block}"""


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith(_JSON_FENCE_OPEN):
        t = t[len(_JSON_FENCE_OPEN):]
    elif t.startswith(_JSON_FENCE_ALT):
        t = t[len(_JSON_FENCE_ALT):]
    if t.endswith(_JSON_FENCE_CLOSE):
        t = t[: -len(_JSON_FENCE_CLOSE)]
    return t.strip()


def _parse(text: str, segment_id: str) -> ClipDecision:
    payload: dict[str, Any] = json.loads(_strip_fence(text))
    payload["segment_id"] = segment_id  # forced from caller — never trust the LLM here
    return ClipDecision.model_validate(payload)


async def decide_segment(
    provider: LLMProvider,
    spec: Spec,
    seg: Segment,
    prior_accepted_summaries: list[str],
    prior_lessons: list[str] | None = None,
) -> ClipDecision:
    system = _system_prompt(spec)
    user = _user_message(spec, seg, prior_accepted_summaries, prior_lessons)

    comp = await provider.complete(
        system=system,
        user_text=user,
        model=PHASE1_MODEL_ID,
        max_tokens=DECIDE_MAX_TOKENS,
    )
    _record_llm(comp.model, comp.input_tokens, comp.output_tokens)
    try:
        return _parse(comp.text, seg.segment_id)
    except (json.JSONDecodeError, ValidationError):
        pass

    retry = await provider.complete(
        system=system,
        user_text=user + _RETRY_SUFFIX,
        model=PHASE1_MODEL_ID,
        max_tokens=DECIDE_MAX_TOKENS,
    )
    _record_llm(retry.model, retry.input_tokens, retry.output_tokens)
    try:
        return _parse(retry.text, seg.segment_id)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DecisionParseError(
            f"decision JSON invalid for {seg.segment_id} after retry: {exc}"
        ) from exc
