"""Whole-script direction chain (Sonnet).

Direction is whole-script: the chain sees the full parsed script so pacing and arc
are decided across sections, and emits structured per-section direction — directed
text with eleven_v3 audio tags inline, a voice PICKED from the supplied registry
(never invented), a model, a model-agnostic settings dict, and brief reasoning. No
ElevenLabs call, no character budget — this is the free loop.
"""

from __future__ import annotations

import json
import logging
import re

from anthropic import AsyncAnthropic
from anthropic.types import Message

from agent_runtime.tracing import record_llm_call

from voiceover_direction.constants import (
    DEFAULT_MODEL,
    MAX_DIRECTION_TOKENS,
    MODEL_DIRECTOR,
)
from voiceover_direction.models import DirectedSection, ParsedScript, Take, VoiceProfile
from voiceover_direction.retrieval import RetrievedContext, build_context_prompt

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are an expert voiceover director working with ElevenLabs text-to-speech.

Your job: take a whole script (already split into sections) and direct it for narration
by a single narrator. Direction is whole-script — decide pacing, energy, and emotional
arc across sections, not section-by-section in isolation.

For each section, produce:
- directed_text: the section's prose with ElevenLabs eleven_v3 AUDIO TAGS inline as
  literal bracketed tags (e.g. [whispers], [excited], [pause], [sighs]). Keep the wording
  faithful to the input; you are directing delivery, not rewriting the script.
- voice_id: PICK one voice_id from the provided available-voices list — never invent an
  id. If no voices are available (the registry is empty), set voice_id to null and put the
  desired voice characteristics in voice_characteristics instead.
- voice_characteristics: a short phrase describing the ideal voice (only when voice_id is
  null; otherwise null).
- model: the ElevenLabs model, default "eleven_v3" (the expressive, audio-tag-capable one).
- settings: a small JSON object of generation params (model-agnostic; for eleven_v3 this is
  things like {"stability": "creative"} — omit knobs you have no reason to set, {} is fine).
- reasoning: one or two sentences on the delivery choice, citing retrieved context when relevant.

When context is provided:
- [PRIOR TAKE: reaction=LOVED] entries are the user's own best results — lean on them.
- [DIRECTION LESSON: positive/...] entries are confirmed preferences — honour them.
- [USER FACT: elevenlabs_mechanics] entries are user-verified — treat as authoritative.
- [TUTORIAL KNOWLEDGE] entries are useful references but defer to USER FACT on conflicts.

Output STRICT JSON of this shape, one entry per input section, preserving section_id:
{
  "sections": [
    {
      "section_id": "intro",
      "directed_text": "[whispers] Welcome back...",
      "voice_id": "voice-1" or null,
      "voice_characteristics": null or "warm calm female narrator",
      "model": "eleven_v3",
      "settings": {"stability": "creative"},
      "reasoning": "..."
    }
  ],
  "overall_reasoning": "script-level pacing and arc notes"
}
"""


class DirectionParseError(ValueError):
    """Raised when the direction response can't be parsed into per-section direction."""


_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous response was not valid JSON of the required shape, "
    "or was missing the `sections` array with a `directed_text` per input section. "
    "Reproduce your full JSON response exactly as specified: a `sections` array with one "
    "object per input section_id, each with directed_text, voice_id (from the available "
    "list or null), voice_characteristics, model, settings, and reasoning, plus a "
    "top-level overall_reasoning. Output JSON only."
)


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route LLM cost through the active BudgetTracker when present, else emit directly."""
    from agent_runtime.budget import get_current_tracker

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        # No active tracker (e.g. a unit test): emit the trace event with zero cost.
        record_llm_call(model, input_tokens, output_tokens, 0.0)


def _format_voices(voices: list[VoiceProfile]) -> str:
    if not voices:
        return "(none — the voice registry is empty; set voice_id to null and describe the ideal voice)"
    lines = []
    for v in voices:
        labels = ", ".join(f"{k}={val}" for k, val in v.labels.items())
        desc = f" — {v.description}" if v.description else ""
        suffix = f" [{labels}]" if labels else ""
        lines.append(f"- {v.voice_id}: {v.name} ({v.category}){suffix}{desc}")
    return "\n".join(lines)


def _build_user_message(
    parsed: ParsedScript,
    voices: list[VoiceProfile],
    ctx: RetrievedContext,
) -> str:
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"
    section_blocks = "\n\n".join(
        f"[SECTION section_id={s.section_id}] {s.heading}\n{s.body}" for s in parsed.sections
    )
    return f"""Available voices (pick voice_id from these):
{_format_voices(voices)}

Relevant context:
{context_block}

Script ({len(parsed.sections)} section(s)) — direct every section, preserving each section_id:
{section_blocks}"""


async def direct_script(
    parsed: ParsedScript,
    voices: list[VoiceProfile],
    ctx: RetrievedContext,
    client: AsyncAnthropic,
) -> tuple[list[DirectedSection], str]:
    """Run the whole-script direction chain. Returns (directed_sections, overall_reasoning).

    Retries once if the response can't be parsed, then raises (no silent fallback).
    """
    user_message = _build_user_message(parsed, voices, ctx)
    valid_voice_ids = {v.voice_id for v in voices}
    headings = {s.section_id: s.heading for s in parsed.sections}

    response = await client.messages.create(
        model=MODEL_DIRECTOR,
        max_tokens=MAX_DIRECTION_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_DIRECTOR, response.usage.input_tokens, response.usage.output_tokens)

    try:
        return _parse_direction_response(response, headings, valid_voice_ids)
    except DirectionParseError:
        logger.warning("Direction response unparseable; retrying once with explicit reminder")
        retry = await client.messages.create(
            model=MODEL_DIRECTOR,
            max_tokens=MAX_DIRECTION_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text},
                {"role": "user", "content": _RETRY_SUFFIX},
            ],
        )
        _record_llm(MODEL_DIRECTOR, retry.usage.input_tokens, retry.usage.output_tokens)
        return _parse_direction_response(retry, headings, valid_voice_ids)


_REDIRECT_SYSTEM_PROMPT = """\
You are an expert voiceover director working with ElevenLabs text-to-speech.

You are revising the direction for ONE section based on the user's note about the LAST take
of that section. The note says what to change. Incorporate it; keep the wording faithful to
the section (you are directing delivery — tags, pacing, voice, settings — not rewriting the
script). The current direction (the last take's directed text) is your starting point; evolve
it to address the note. Lean on the retrieved context, and note that a [PRIOR TAKE:
reaction=RENDER FAILED] means the render (not the direction) failed — keep that territory open.

Produce the revised direction for the single section:
- directed_text: the section's prose with ElevenLabs eleven_v3 AUDIO TAGS inline as literal
  bracketed tags (e.g. [whispers], [excited], [pause]).
- voice_id: PICK one from the provided available-voices list (usually keep the last take's
  voice unless the note asks to change it); null if the registry is empty.
- voice_characteristics: a short phrase only when voice_id is null; otherwise null.
- model: the ElevenLabs model, default "eleven_v3".
- settings: a small model-agnostic JSON object of generation params ({} is fine).
- reasoning: one or two sentences on what you changed and why, citing the note.

Output STRICT JSON of this shape — a single section, preserving the given section_id:
{
  "sections": [
    {
      "section_id": "<the given id>",
      "directed_text": "...",
      "voice_id": "voice-1" or null,
      "voice_characteristics": null or "...",
      "model": "eleven_v3",
      "settings": {"stability": "creative"},
      "reasoning": "..."
    }
  ],
  "overall_reasoning": "what the revision addresses"
}
"""


def _build_redirect_message(
    last_take: Take,
    note: str,
    ctx: RetrievedContext,
    voices: list[VoiceProfile],
) -> str:
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"
    reaction_line = f"Last take reaction: {last_take.reaction}"
    if last_take.context:
        reaction_line += f' (context: "{last_take.context}")'
    return f"""Available voices (pick voice_id from these):
{_format_voices(voices)}

Relevant context (this section's history):
{context_block}

Revise this ONE section (section_id={last_take.section_id}), incorporating the note.

{reaction_line}

Change requested (the note): {note}

Current direction (the last take's directed text — your starting point):
{last_take.text}"""


async def redirect_section(
    last_take: Take,
    heading: str,
    note: str,
    ctx: RetrievedContext,
    voices: list[VoiceProfile],
    client: AsyncAnthropic,
) -> DirectedSection:
    """Section-scoped re-direction: revise the last take's direction to fold in its note.

    The base is the LAST take's directed text (not the file's markup), so fold-ins compound
    along the section's take chain. Retries once on a parse failure, then raises.
    """
    user_message = _build_redirect_message(last_take, note, ctx, voices)
    headings = {last_take.section_id: heading}
    valid_voice_ids = {v.voice_id for v in voices}

    response = await client.messages.create(
        model=MODEL_DIRECTOR,
        max_tokens=MAX_DIRECTION_TOKENS,
        system=_REDIRECT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_DIRECTOR, response.usage.input_tokens, response.usage.output_tokens)

    try:
        sections, _ = _parse_direction_response(response, headings, valid_voice_ids)
    except DirectionParseError:
        logger.warning("Re-direction response unparseable; retrying once with explicit reminder")
        retry = await client.messages.create(
            model=MODEL_DIRECTOR,
            max_tokens=MAX_DIRECTION_TOKENS,
            system=_REDIRECT_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text},
                {"role": "user", "content": _RETRY_SUFFIX},
            ],
        )
        _record_llm(MODEL_DIRECTOR, retry.usage.input_tokens, retry.usage.output_tokens)
        sections, _ = _parse_direction_response(retry, headings, valid_voice_ids)
    return sections[0]


def _compose_notes(reasoning: str, voice_id: str | None, characteristics: str | None) -> str | None:
    parts: list[str] = []
    if voice_id is None and characteristics:
        parts.append(f"Suggested voice: {characteristics}")
    if reasoning:
        parts.append(reasoning)
    return " — ".join(parts) if parts else None


def _parse_direction_response(
    response: Message,
    headings: dict[str, str],
    valid_voice_ids: set[str],
) -> tuple[list[DirectedSection], str]:
    text = response.content[0].text.strip()
    json_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DirectionParseError(f"Direction response was not valid JSON: {exc}") from exc

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise DirectionParseError("Direction response had no `sections` array")

    directed: list[DirectedSection] = []
    for item in raw_sections:
        section_id = item.get("section_id")
        directed_text = item.get("directed_text")
        if not section_id or section_id not in headings or not directed_text:
            raise DirectionParseError(
                f"Section entry missing/unknown section_id or directed_text: {item.get('section_id')!r}"
            )

        # Pick a voice only if the model returned one that actually exists in the registry.
        raw_voice = item.get("voice_id")
        voice_id = raw_voice if raw_voice in valid_voice_ids else None
        characteristics = item.get("voice_characteristics")
        settings = item.get("settings") or {}
        if not isinstance(settings, dict):
            settings = {}

        directed.append(
            DirectedSection(
                section_id=section_id,
                heading=headings[section_id],
                text=directed_text,
                voice_id=voice_id,
                model=item.get("model") or DEFAULT_MODEL,
                settings=settings,
                notes=_compose_notes(item.get("reasoning", ""), voice_id, characteristics),
            )
        )

    overall_reasoning = data.get("overall_reasoning", "")
    return directed, overall_reasoning
