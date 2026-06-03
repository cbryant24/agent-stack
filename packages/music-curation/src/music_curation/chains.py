"""LLM chains for music generation and delegation trigger logic."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from agent_runtime.tracing import record_delegation_decision, record_llm_call

from music_curation.constants import (
    DELEGATION_ARTIST_REF_THRESHOLD,
    DELEGATION_MUSIC_THEORY_THRESHOLD,
    DELEGATION_SUNO_FEATURE_THRESHOLD,
    MAX_GENERATION_TOKENS,
    MODEL_GENERATOR,
    STYLE_FIELD_MAX_CHARS,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
)
from music_curation.models import GenerationRef, MusicResult, SunoPrompt
from music_curation.retrieval import RetrievedContext, build_context_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert music curator and music-theory specialist helping craft Suno AI prompts.

Your capabilities:
- Deep knowledge of music theory: harmony, chord progressions, rhythm, genre conventions,
  instrumentation, song structure, production techniques
- Accurate knowledge of Suno's prompt system: style field, lyrics field, meta-tags,
  character limits, vocal control, structural markers
- Persistent memory of the user's taste and prior generations (provided in context)

Core rules for Suno prompts:
- Style field: comma-separated descriptors, max 1000 characters
- Never use artist names in style fields — describe sonic qualities instead
- Lyrics field: use structural markers [Hook], [Verse], [Instrumental], etc.
- Language specifiers go in the style field, not lyrics
- Parentheses in lyrics = backing vocals / ad-libs

When context is provided:
- [PRIOR GENERATION: reaction=LOVED] entries are the user's best results — build on them
- [USER FACT: suno_mechanics] entries are user-verified, treat as authoritative
- [TASTE: positive/...] entries are confirmed user preferences — honour them
- [TUTORIAL KNOWLEDGE] entries are good references but defer to USER FACT on conflicts

Output format (JSON):
{
  "prompts": [
    {
      "style_field": "...",
      "lyrics_field": null or "..."
    }
  ],
  "theory_reasoning": "...",
  "suggested_titles": ["title for prompt 1", "title for prompt 2"]
}

Generate 1-3 prompt variants. theory_reasoning should explain why the choices work
musically and cite the retrieved context where relevant. If you silently defaulted on
any input dimension (key, BPM, language, structure), disclose it in theory_reasoning.
"""

_ONE_QUESTION_PROMPT = """\
You have a music generation request. Before generating, determine if ONE clarifying
question would substantially improve the output. Only ask if the answer would change
the core direction.

If you need to ask: respond with EXACTLY this JSON:
{{"ask": true, "question": "...", "suggestion": "...", "reasoning": "..."}}

If you can generate now: respond with:
{{"ask": false}}

Request: {request}
Retrieved context summary: {context_summary}
"""

_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _PRICING.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route LLM cost through the active BudgetTracker when present, else emit directly.

    Mirrors record_tool_call's bridge pattern. Without this, record_llm_call emits
    the trace event correctly but never increments tracker._consumption.cost_usd or
    ._consumption.llm_calls, causing cost aggregation to show $0.0 everywhere.
    """
    from agent_runtime.budget import get_current_tracker
    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
        # add_llm_cost calls record_llm_call internally — don't double-emit
    else:
        cost = _compute_cost(model, input_tokens, output_tokens)
        record_llm_call(model, input_tokens, output_tokens, cost)


def _truncate_style(s: str) -> str:
    return s[:STYLE_FIELD_MAX_CHARS] if len(s) > STYLE_FIELD_MAX_CHARS else s


async def check_for_question(
    request: str,
    ctx: RetrievedContext,
    client: AsyncAnthropic,
) -> dict[str, Any] | None:
    """Ask the model if one clarifying question would improve the output.

    Returns a dict with {ask, question, suggestion, reasoning} if a question
    is warranted, or None if generation should proceed immediately.
    """
    context_summary = (
        f"{len(ctx.prior_generations)} prior generations, "
        f"{len(ctx.taste_lessons)} taste lessons, "
        f"{len(ctx.suno_facts)} suno facts, "
        f"{len(ctx.tutorial_hits)} tutorial hits"
    )
    user_content = _ONE_QUESTION_PROMPT.format(
        request=request, context_summary=context_summary
    )

    response = await client.messages.create(
        model=MODEL_GENERATOR,
        max_tokens=256,
        messages=[{"role": "user", "content": user_content}],
    )
    _record_llm(MODEL_GENERATOR, response.usage.input_tokens, response.usage.output_tokens)

    text = response.content[0].text.strip()
    try:
        parsed = json.loads(text)
        if parsed.get("ask"):
            return parsed
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


class MissingTitlesError(ValueError):
    """Raised when the model response lacks a suggested_title for every prompt."""
    pass


_TITLES_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous response was missing the `suggested_titles` field "
    "or had fewer titles than prompts. `suggested_titles` is REQUIRED — one memorable "
    "3-5 word track handle per prompt (e.g. \"Memphis Night Crawl\", \"130 Raw Phonk\"). "
    "Without it the user cannot re-find the track in Suno. Reproduce your full JSON "
    "response with `suggested_titles` correctly populated."
)


async def generate_prompts(
    request: str,
    ctx: RetrievedContext,
    client: AsyncAnthropic,
    *,
    num_variants: int = 2,
) -> tuple[list[SunoPrompt], str, list[str]]:
    """Generate Suno prompts for the given request.

    Returns (prompts, theory_reasoning, suggested_titles).
    Retries once if the model omits suggested_titles rather than silently
    substituting a generic fallback — a missing title makes the field unreliable.
    """
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"

    user_message = f"""Request: {request}

Relevant context:
{context_block}

Generate {num_variants} prompt variant(s). Remember style field max {STYLE_FIELD_MAX_CHARS} chars."""

    response = await client.messages.create(
        model=MODEL_GENERATOR,
        max_tokens=MAX_GENERATION_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    _record_llm(MODEL_GENERATOR, response.usage.input_tokens, response.usage.output_tokens)

    try:
        return _parse_generation_response(response)
    except MissingTitlesError:
        logger.warning("Model omitted suggested_titles; retrying with explicit reminder")
        retry_response = await client.messages.create(
            model=MODEL_GENERATOR,
            max_tokens=MAX_GENERATION_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content[0].text},
                {"role": "user", "content": _TITLES_RETRY_SUFFIX},
            ],
        )
        _record_llm(
            MODEL_GENERATOR,
            retry_response.usage.input_tokens,
            retry_response.usage.output_tokens,
        )
        # Raise on second failure — don't silently fall back
        return _parse_generation_response(retry_response)


def _parse_generation_response(
    response: Message,
) -> tuple[list[SunoPrompt], str, list[str]]:
    text = response.content[0].text.strip()

    # Extract JSON from markdown code block if present
    json_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MissingTitlesError(
            f"Generation response was not valid JSON: {exc}"
        ) from exc

    prompts: list[SunoPrompt] = []
    for p in data.get("prompts", []):
        style = _truncate_style(p.get("style_field", ""))
        if style:
            prompts.append(SunoPrompt(
                style_field=style,
                lyrics_field=p.get("lyrics_field"),
            ))

    if not prompts:
        raise MissingTitlesError("Model returned no valid prompts")

    theory_reasoning = data.get("theory_reasoning", "")
    raw_titles = data.get("suggested_titles", [])

    # Validate: must have one non-empty, non-generic title per prompt
    if (
        len(raw_titles) < len(prompts)
        or any(not t or str(t).strip().lower() in ("generated prompt", "prompt", "") for t in raw_titles)
    ):
        raise MissingTitlesError(
            f"Expected {len(prompts)} specific suggested_titles, "
            f"got {raw_titles!r}"
        )

    return prompts, theory_reasoning, [str(t).strip() for t in raw_titles[:len(prompts)]]


# ── Delegation trigger logic ──────────────────────────────────────────────────

class DelegationTrigger:
    """Checks three concrete conditions before delegating to tutorial-research.

    Decision logic (in order):
    1. Suno feature/syntax query → search user_knowledge (suno_mechanics first)
    2. "Why does X work" music-theory query → search tutorial_research directly
    3. Artist/song/genre reference → search all three collections

    In each case: if local max_score >= threshold → answer locally.
    If < threshold → emit record_delegation_decision and recommend delegation.

    'Recommend delegation' means the caller should run tutorial-research retrieve
    mode first; only if that also fails does it use delegate() for fresh ingestion.
    """

    def __init__(self, curation_store, memory_store):
        self._curation_store = curation_store
        self._memory_store = memory_store

    async def check(self, request: str, ctx: RetrievedContext) -> str:
        """Return 'local', 'retrieve', or 'ingest'.

        'local' = answer from existing context
        'retrieve' = run tutorial-research in retrieve mode first
        'ingest' = run tutorial-research with full research/ingestion
        """
        # Trigger 1: Suno feature/syntax
        if _mentions_suno_feature(request):
            max_score = ctx.max_user_knowledge_score()
            decision = "local" if max_score >= DELEGATION_SUNO_FEATURE_THRESHOLD else "retrieve"
            record_delegation_decision(
                trigger_type="suno_feature",
                collection=USER_KNOWLEDGE_COLLECTION,
                query=request,
                local_max_score=max_score,
                threshold=DELEGATION_SUNO_FEATURE_THRESHOLD,
                decision=decision,
            )
            return decision

        # Trigger 2: Music theory "why" question
        if _is_theory_question(request):
            max_score = ctx.max_tutorial_score()
            decision = "local" if max_score >= DELEGATION_MUSIC_THEORY_THRESHOLD else "retrieve"
            record_delegation_decision(
                trigger_type="music_theory",
                collection=TUTORIAL_RESEARCH_COLLECTION,
                query=request,
                local_max_score=max_score,
                threshold=DELEGATION_MUSIC_THEORY_THRESHOLD,
                decision=decision,
            )
            return decision

        # Trigger 3: Artist/genre reference with no local context
        if _mentions_artist_or_genre_reference(request):
            max_score = max(ctx.max_user_knowledge_score(), ctx.max_tutorial_score())
            decision = "local" if max_score >= DELEGATION_ARTIST_REF_THRESHOLD else "retrieve"
            record_delegation_decision(
                trigger_type="artist_reference",
                collection=TUTORIAL_RESEARCH_COLLECTION,
                query=request,
                local_max_score=max_score,
                threshold=DELEGATION_ARTIST_REF_THRESHOLD,
                decision=decision,
            )
            return decision

        return "local"


def _mentions_suno_feature(request: str) -> bool:
    """True if the request specifically asks about Suno features or prompt syntax."""
    return bool(re.search(
        r"suno\s+(feature|syntax|tag|version|v\d|stem|remix|extend|cover|custom)"
        r"|style field|lyrics field|character limit|\[instrumental\]",
        request, re.IGNORECASE,
    ))


def _is_theory_question(request: str) -> bool:
    """True if the request asks 'why does X work' or similar music-theory questions."""
    return bool(re.search(
        r"\bwhy\b.*(work|sound|feel|resonat|hit|effective)|"
        r"music theory|chord progression|harmonic|explain.*sound|"
        r"what makes\b",
        request, re.IGNORECASE,
    ))


def _mentions_artist_or_genre_reference(request: str) -> bool:
    """True if the request references an artist, film, or show by name."""
    return bool(re.search(
        r"like\s+[A-Z][a-z]+|inspired by|in the style of|[A-Z][a-z]+'s|"
        r"sounds? like [A-Z]|vibes? of [A-Z]",
        request,
    ))
