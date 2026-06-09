"""research — the explicit, deliberate delegation to tutorial-research (Q9).

`draft` only OFFERS research on a knowledge gap; this is the command that runs it.
A standard `delegate()` to tutorial-research with a CHILD BudgetEnvelope that is
Claude-cost-only — research touches no GPU, so the agent-local GPU tracker is never
imported or entered on this path.

Two-step with a cheap fallback: tutorial-research writes to the `tutorial_research`
collection, which is already one of this agent's three retrieval legs. So once a
topic is researched, subsequent draft/explain/recall retrieve it cheaply with no
re-delegation. After delegating, this module re-queries that collection to confirm
the result landed and to preview it.

Delegate-handler registration: nothing else in the stack registers the
tutorial-research handler, so each process that delegates registers what it needs
at startup. `register_delegate_handlers()` is idempotent (guarded via list_agents)
and is the bootstrap the CLI calls; `research()` also calls it defensively.
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
    delegate,
    get_memory_store,
    list_agents,
    register_agent,
    render_run_report,
)
from pydantic import BaseModel, Field

from visual_generation.constants import (
    AGENT_NAME,
    DELEGATE_TARGET_TUTORIAL_RESEARCH,
    RESEARCH_BUDGET,
    RESEARCH_CHILD_BUDGET,
)
from visual_generation.retrieval import _fetch_tutorial

logger = logging.getLogger(__name__)


async def _tutorial_research_handler(request: dict[str, Any], budget: BudgetEnvelope) -> dict[str, Any]:
    """delegate() handler contract → tutorial_research.research() invocation shape.

    delegate() calls `handler(request_dict, child_budget)`; tutorial_research.research
    takes a positional `request: str` plus keyword args. Adapt the dict, and return a
    plain dict (DelegationResult.result is dict-typed) summarising the run.
    """
    from tutorial_research import research as tutorial_research

    result = await tutorial_research(
        request["request"],
        budget=budget,
        request_type=request.get("request_type"),
        synthesize=request.get("synthesize", False),
    )
    return {
        "status": result.status,
        "request_type": result.request_type,
        "items_processed": result.items_processed,
        "retrieved_count": len(result.retrieved),
        "synthesis": result.synthesis,
        "run_id": result.run_id,
    }


def register_delegate_handlers() -> None:
    """Register the delegate handlers this agent uses (idempotent bootstrap)."""
    if DELEGATE_TARGET_TUTORIAL_RESEARCH not in list_agents():
        register_agent(DELEGATE_TARGET_TUTORIAL_RESEARCH, _tutorial_research_handler)


class ResearchOutcome(BaseModel):
    """The result of a `research` run: the delegation outcome plus the cheap
    follow-up retrieval (the two-step fallback's confirmation)."""

    topic: str
    delegation_status: str = "failed"
    items_processed: int = 0
    synthesis: str | None = None
    tutorial_hits: list[tuple[float, str]] = Field(default_factory=list)  # the cheap re-retrieval
    run_id: str = ""
    status: str = "completed"
    cost_usd: float = 0.0  # Claude axis only — GPU never enters this path
    wall_time_sec: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


async def research(
    topic: str,
    *,
    budget: BudgetEnvelope | None = None,
    child_budget: BudgetEnvelope | None = None,
    memory_store: MemoryStore | None = None,
) -> ResearchOutcome:
    """Delegate `topic` to tutorial-research, then re-query the collection cheaply."""
    register_delegate_handlers()
    memory_store = memory_store or get_memory_store()

    status = "completed"
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    delegation_status = "failed"
    items_processed = 0
    synthesis: str | None = None
    tutorial_hits: list[tuple[float, str]] = []
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or RESEARCH_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                result = await delegate(
                    DELEGATE_TARGET_TUTORIAL_RESEARCH,
                    {"request": topic, "request_type": "research", "synthesize": False},
                    child_budget or RESEARCH_CHILD_BUDGET,
                    parent_tracker=tracker,
                )
                delegation_status = result.status
                if result.result:
                    items_processed = result.result.get("items_processed", 0)
                    synthesis = result.result.get("synthesis")

                # Two-step cheap fallback: the result now lives in tutorial_research,
                # already a retrieval leg. Re-query it (cheap — embedding only) to
                # confirm/preview; no second delegation.
                tutorial_hits = await _fetch_tutorial(topic, memory_store, limit=5)

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd  # includes the delegated child cost (Claude axis)
        wall_time_sec = snap.wall_time_sec

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass

    return ResearchOutcome(
        topic=topic,
        delegation_status=delegation_status,
        items_processed=items_processed,
        synthesis=synthesis,
        tutorial_hits=tutorial_hits,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def research_sync(topic: str, **kwargs: Any) -> ResearchOutcome:
    return asyncio.run(research(topic, **kwargs))


def render_research(outcome: ResearchOutcome) -> str:
    lines = [
        f"Topic:      {outcome.topic}",
        f"Delegation: {outcome.delegation_status}  ({outcome.items_processed} item(s) ingested)",
        f"Cost:       ${outcome.cost_usd:.4f}  (Claude — research touches no GPU)",
    ]
    if outcome.synthesis:
        lines.append(f"\nSynthesis:\n{outcome.synthesis}")
    if outcome.tutorial_hits:
        lines.append("\n── Now retrievable (tutorial_research) ──────────────")
        for score, content in outcome.tutorial_hits:
            if content:
                lines.append(f"  [{score:.3f}] {content[:100]}")
        lines.append("\nFuture draft/explain/recall retrieve this cheaply — no re-research.")
    elif outcome.delegation_status == "completed":
        lines.append("\n(No retrievable chunks surfaced yet — try `recall` or `explain` shortly.)")
    return "\n".join(lines)
