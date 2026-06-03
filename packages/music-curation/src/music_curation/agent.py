"""music-curation agent entry point."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
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
    record_llm_call,
    render_run_report,
)
from agent_runtime.tracing.decorators import record_memory_write

from music_curation.chains import DelegationTrigger, check_for_question, generate_prompts
from music_curation.constants import DEFAULT_BUDGET, MODEL_GENERATOR
from music_curation.models import (
    Generation,
    GenerationRef,
    MusicResult,
    SunoPrompt,
)
from music_curation.retrieval import RetrievedContext, retrieve_context
from music_curation.store import MusicCurationStore

logger = logging.getLogger(__name__)


def _get_stores() -> tuple[MusicCurationStore, MemoryStore, UserKnowledgeStore]:
    ms = get_memory_store()
    curation = MusicCurationStore(ms)
    knowledge = UserKnowledgeStore(ms)
    return curation, ms, knowledge


async def curate(
    request: str,
    *,
    budget: BudgetEnvelope | None = None,
    dry_run: bool = False,
    skip_question: bool = False,
) -> MusicResult:
    """Main entry point for music curation.

    Retrieves context, optionally asks one clarifying question, generates
    Suno prompts, logs them as pending generations, and returns MusicResult.
    """
    config = get_config()
    effective_budget = budget or DEFAULT_BUDGET
    client = AsyncAnthropic(api_key=config.anthropic_api_key)

    curation_store, memory_store, knowledge_store = _get_stores()

    # Ensure collection exists
    await curation_store.ensure_collection()

    status = "completed"
    tracker_ref: BudgetTracker | None = None
    run_id = ""
    cost_usd = 0.0
    items_processed = 0
    wall_time_sec = 0.0
    start_time = time.monotonic()

    prompts: list[SunoPrompt] = []
    suggested_titles: list[str] = []
    theory_reasoning = ""
    cross_references: list[GenerationRef] = []
    generation_ids: list[str] = []
    question_result: dict | None = None

    try:
        async with BudgetTracker(effective_budget, "music-curation") as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            with TracePersister(agent="music-curation", run_id=run_id):
                # Step 1: Retrieve context
                tracker.check_budget()
                ctx = await retrieve_context(
                    request, curation_store, memory_store, include_tutorial=True
                )

                # Step 2: Check delegation triggers
                delegation_trigger = DelegationTrigger(curation_store, memory_store)
                delegation_decision = await delegation_trigger.check(request, ctx)

                if delegation_decision in ("retrieve", "ingest") and not dry_run:
                    ctx = await _run_delegation(
                        request, delegation_decision, ctx, memory_store, tracker, config
                    )

                # Step 3: Optionally ask one clarifying question
                if not skip_question and not dry_run:
                    question_result = await check_for_question(request, ctx, client)

                # Step 4: Generate prompts
                tracker.check_budget()
                if dry_run:
                    prompts = [SunoPrompt(style_field="(dry run — no generation performed)")]
                    theory_reasoning = "Dry run: would have generated prompts for: " + request
                    suggested_titles = ["Dry Run Prompt"]
                else:
                    prompts, theory_reasoning, suggested_titles = await generate_prompts(
                        request, ctx, client
                    )

                # Step 5: Build cross-references from prior loved/liked generations
                for score, gen in ctx.prior_generations:
                    if score >= 0.7:
                        cross_references.append(curation_store.to_generation_ref(gen))

                # Step 6: Log pending generations
                if not dry_run:
                    generations = _make_pending_generations(
                        request, prompts, suggested_titles, run_id
                    )
                    await curation_store.upsert_generations_bulk(generations)
                    generation_ids = [g.entry_id for g in generations]
                    record_memory_write("music_curation_memory", len(generations))
                    tracker.add_item_processed()
                    items_processed = 1

    except BudgetExhaustedError:
        status = "partial"

    # Finalize stats after context exit (same pattern as tutorial-research)
    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, "music-curation")
        except FileNotFoundError:
            pass
        notify_run_complete("music-curation", run_id, status, cost_usd)

    result = MusicResult(
        prompts=prompts,
        suggested_titles=suggested_titles,
        theory_reasoning=theory_reasoning,
        references=[],
        cross_references=cross_references,
        generation_ids=generation_ids,
        run_id=run_id,
        status=status,
        cost_usd=cost_usd,
        items_processed=items_processed,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )

    # Attach question to result for CLI display
    if question_result:
        result.__dict__["_pending_question"] = question_result

    return result


def _make_pending_generations(
    request: str,
    prompts: list[SunoPrompt],
    suggested_titles: list[str],
    run_id: str,
) -> list[Generation]:
    """Build pending Generation entries from the generated prompts."""
    from music_curation.constants import REACTION_PENDING
    gens = []
    for i, (prompt, title) in enumerate(
        zip(prompts, suggested_titles + ["Generated Prompt"] * len(prompts))
    ):
        gen = Generation(
            session_id=run_id,
            style_field=prompt.style_field,
            lyrics_field=prompt.lyrics_field,
            goal=request[:200],
            suggested_track_title=title[:50],
            reaction=REACTION_PENDING,
        )
        gens.append(gen)
    return gens


async def _run_delegation(
    request: str,
    decision: str,
    existing_ctx: RetrievedContext,
    memory_store: MemoryStore,
    tracker: BudgetTracker,
    config: Any,
) -> RetrievedContext:
    """Delegate to tutorial-research if local context is insufficient.

    For 'retrieve' decision: runs in retrieve mode (near-free — embedding only).
    For 'ingest' decision: runs in research mode (more expensive — ingestion + synthesis).
    """
    try:
        from tutorial_research import research
        from agent_runtime import BudgetEnvelope, delegate

        request_type = "retrieve" if decision == "retrieve" else "research"
        child_budget = BudgetEnvelope(
            max_items=2,
            max_depth=max(0, tracker._envelope.max_depth - 1),
            max_cost_usd=min(0.50, tracker._envelope.max_cost_usd * 0.3),
            max_wall_time_sec=min(180, tracker._envelope.max_wall_time_sec * 0.4),
        )

        result = await delegate(
            "tutorial-research",
            {"request": request, "request_type": request_type, "synthesize": False},
            child_budget,
            parent_tracker=tracker,
        )

        # tutorial-research's synthesized result doesn't directly update existing_ctx,
        # but the Qdrant collection is refreshed so the next retrieve_context call gets it.
        # For this run, we re-query tutorial_research collection with the updated data.
        from music_curation.retrieval import _fetch_tutorial
        new_tutorial_hits = await _fetch_tutorial(request, memory_store, limit=5)
        existing_ctx.tutorial_hits = new_tutorial_hits

    except Exception as exc:
        logger.warning("Delegation to tutorial-research failed (degrading gracefully): %s", exc)

    return existing_ctx


def curate_sync(request: str, **kwargs: Any) -> MusicResult:
    """Synchronous wrapper for curate()."""
    return asyncio.run(curate(request, **kwargs))
