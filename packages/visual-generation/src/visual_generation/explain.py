"""explain — the on-demand tutor deep-dive (Q6).

A grounded Claude explanation of a concept. Two invariants, independent of the
verbosity dial:
  1. It ALWAYS retrieves the three-collection context (own memory + user_knowledge
     + tutorial_research) — this is the draft/explain retrieval path.
  2. It ALWAYS surfaces the user's OWN relevant `technique_lesson`s back to them
     ("you noted CFG>7 washed skin on this checkpoint").

The `--level` dial (full / concise / quiet) changes ONLY how much GENERIC Claude
explanation rides along (via the system instruction + a max_tokens ceiling), never
whether own-lessons appear. `quiet` degenerates to own-lessons + a one-line gloss.

Carries the Claude cost only (BudgetEnvelope). It makes no ComfyUI call and never
imports the GPU tracker — the GPU axis is untouched on this path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    MemoryStore,
    TracePersister,
    get_config,
    get_memory_store,
    render_run_report,
)
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from visual_generation.constants import (
    AGENT_NAME,
    DEFAULT_EXPLAIN_LEVEL,
    EXPLAIN_BUDGET,
    EXPLAIN_LEVEL_CONCISE,
    EXPLAIN_LEVEL_FULL,
    EXPLAIN_LEVEL_QUIET,
    EXPLAIN_LEVELS,
    EXPLAIN_MAX_TOKENS,
    MODEL_DIRECTOR,
)
from visual_generation.retrieval import RetrievedContext, build_context_prompt, retrieve_context
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


_LEVEL_INSTRUCTION = {
    EXPLAIN_LEVEL_FULL: (
        "Give a THOROUGH explanation: the mechanism, why it behaves this way, and "
        "practical guidance. Ground every claim in the retrieved context where possible."
    ),
    EXPLAIN_LEVEL_CONCISE: (
        "Give a CONCISE explanation: 2-4 sentences covering the essential mechanism "
        "and the one practical takeaway. Ground it in the retrieved context."
    ),
    EXPLAIN_LEVEL_QUIET: (
        "Give a MINIMAL one-line gloss — a single sentence definition. Do not elaborate; "
        "the user's own lessons (shown to them separately) carry the weight."
    ),
}

_SYSTEM_PROMPT = """\
You are a diffusion / ComfyUI / RunPod platform tutor. The user asked you to explain
a concept. The user's OWN technique lessons are surfaced to them separately, so do
NOT restate them — produce the GENERIC explanation that complements them.

{level_instruction}

When retrieved context is provided, prefer it and cite source types implicitly:
- [USER FACT: ...] entries are user-verified platform mechanics — authoritative.
- [TUTORIAL KNOWLEDGE] entries are tutorial-derived technique — useful, defer to USER FACT on conflict.
- [PRIOR GENERATION] / [TECHNIQUE LESSON] / [WORKFLOW TEMPLATE] are the user's own memory.

Output plain prose (no JSON, no headings)."""


class ExplainResult(BaseModel):
    """The tutor deep-dive result: the generic gloss plus the always-surfaced
    own-lessons. `own_lessons` is independent of `level`."""

    concept: str
    level: str
    gloss: str = ""
    own_lessons: list[str] = Field(default_factory=list)  # the user's own surfaced lessons
    had_context: bool = False
    run_id: str = ""
    status: str = "completed"
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


def resolve_level(level: str | None) -> str:
    """Explicit flag wins; else the config default (env override), else concise."""
    import os

    from visual_generation.constants import EXPLAIN_LEVEL_ENV_VAR

    if level is not None:
        candidate = level
    else:
        candidate = os.getenv(EXPLAIN_LEVEL_ENV_VAR, DEFAULT_EXPLAIN_LEVEL)
    return candidate if candidate in EXPLAIN_LEVELS else DEFAULT_EXPLAIN_LEVEL


def _record_llm(model: str, input_tokens: int, output_tokens: int) -> None:
    """Route Claude cost through the active BudgetTracker (Claude axis only)."""
    from agent_runtime.budget import get_current_tracker
    from agent_runtime.tracing import record_llm_call

    tracker = get_current_tracker()
    if tracker is not None:
        tracker.add_llm_cost(model, input_tokens, output_tokens)
    else:
        record_llm_call(model, input_tokens, output_tokens, 0.0)


def _build_user_message(concept: str, ctx: RetrievedContext) -> str:
    context_block = build_context_prompt(ctx) if not ctx.is_empty() else "(no prior context)"
    return f"""Concept to explain:
{concept}

Retrieved context:
{context_block}

Explain this concept."""


async def explain(
    concept: str,
    *,
    level: str | None = None,
    budget: BudgetEnvelope | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: AsyncAnthropic | None = None,
) -> ExplainResult:
    """Grounded tutor deep-dive. Own-lessons always surfaced; level tunes the gloss."""
    resolved_level = resolve_level(level)
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    status = "completed"
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    gloss = ""
    own_lessons: list[str] = []
    had_context = False
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or EXPLAIN_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                ctx = await retrieve_context(concept, store, memory_store)
                had_context = not ctx.is_empty()
                # INVARIANT: own technique lessons are always surfaced, every level.
                own_lessons = [le.statement for _, le in ctx.technique_lessons]

                client = llm_client or AsyncAnthropic(api_key=get_config().anthropic_api_key)
                system = _SYSTEM_PROMPT.format(level_instruction=_LEVEL_INSTRUCTION[resolved_level])
                response = await client.messages.create(
                    model=MODEL_DIRECTOR,
                    max_tokens=EXPLAIN_MAX_TOKENS[resolved_level],
                    system=system,
                    messages=[{"role": "user", "content": _build_user_message(concept, ctx)}],
                )
                _record_llm(MODEL_DIRECTOR, response.usage.input_tokens, response.usage.output_tokens)
                gloss = (response.content[0].text or "").strip()

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass

    return ExplainResult(
        concept=concept,
        level=resolved_level,
        gloss=gloss,
        own_lessons=own_lessons,
        had_context=had_context,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def explain_sync(concept: str, **kwargs: Any) -> ExplainResult:
    return asyncio.run(explain(concept, **kwargs))


def render_explain(result: ExplainResult) -> str:
    """Render an ExplainResult for the CLI — own-lessons first (always), then gloss."""
    lines: list[str] = [f"Concept: {result.concept}  (level: {result.level})"]
    lines.append(f"Cost:    ${result.cost_usd:.4f}  (Claude — no GPU)")

    lines.append("\n── Your own technique lessons (relevant) ────────────")
    if result.own_lessons:
        for note in result.own_lessons:
            lines.append(f"  • {note}")
    else:
        lines.append("  (none recorded yet for this concept)")

    lines.append("\n── Explanation ─────────────────────────────────────")
    lines.append(result.gloss or "(no explanation produced)")
    return "\n".join(lines)
