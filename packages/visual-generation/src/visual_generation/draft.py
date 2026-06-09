"""draft — Phase A, the free prompt-craft loop.

Crafts a settled generation spec from a creative intent (Claude + the
three-collection retrieval), advises on missing required models BEFORE any
spin-up, surfaces the user's own technique lessons inline (concise tutor dial),
OFFERS research on a knowledge gap (never runs it — `research` is Step 5), and
appends the spec to an editable batch file. Carries only the Claude cost.
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

from visual_generation.batch_file import append_spec
from visual_generation.chains import craft_spec
from visual_generation.constants import AGENT_NAME, DRAFT_BUDGET, RESEARCH_GAP_THRESHOLD
from visual_generation.identity import derive_identity_bearing
from visual_generation.models import DraftResult, LoraRef, VisualSpec, WorkflowTemplate
from visual_generation.retrieval import RetrievedContext, retrieve_context
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


async def _resolve_template(
    store: VisualGenerationStore,
    template_name: str | None,
    ctx: RetrievedContext,
) -> WorkflowTemplate | None:
    """By explicit name, else the top retrieved template, else None (advisory)."""
    if template_name:
        return await store.get_template_by_name(template_name)
    if ctx.workflow_templates:
        return ctx.workflow_templates[0][1]
    return None


def _default_batch_path(project: str | None) -> Path:
    stem = project or "batch"
    return get_config().agent_data_dir / "visual-generation" / "batches" / f"{stem}.batch.md"


async def draft(
    intent: str,
    *,
    batch_path: str | Path | None = None,
    template_name: str | None = None,
    project: str | None = None,
    budget: BudgetEnvelope | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: AsyncAnthropic | None = None,
) -> DraftResult:
    """Craft a spec from `intent` and append it to the batch file."""
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    out_path = Path(batch_path) if batch_path else _default_batch_path(project)

    status = "completed"
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    spec: VisualSpec | None = None
    template: WorkflowTemplate | None = None
    tutor_notes: list[str] = []
    missing_models: list[str] = []
    research_offer: str | None = None
    overall_reasoning = ""
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or DRAFT_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                ctx = await retrieve_context(intent, store, memory_store)
                template = await _resolve_template(store, template_name, ctx)
                models = store.list_models()

                client = llm_client or AsyncAnthropic(api_key=get_config().anthropic_api_key)
                crafted = await craft_spec(intent, ctx, template, models, client)

                spec = VisualSpec(
                    heading=(crafted["prompt"] or intent)[:60],
                    prompt=crafted["prompt"],
                    negative_prompt=crafted["negative_prompt"],
                    settings=crafted["settings"],
                    model=crafted["model"],
                    seed=crafted["seed"],
                    seed_strategy=crafted["seed_strategy"],
                    width=crafted["width"],
                    height=crafted["height"],
                    lora_stack=[LoraRef(**lr) for lr in crafted["lora_stack"]],
                    workflow_ref=template.name if template else None,
                    project=project,
                    rationale=crafted["rationale"],
                )
                # Pre-fill identity_bearing honestly from the registry (the same
                # derivation generate re-runs authoritatively at spend time).
                spec.identity_bearing = derive_identity_bearing(spec, store.get_model)

                overall_reasoning = crafted["rationale"]
                tutor_notes = [le.statement for _, le in ctx.technique_lessons]

                if template is not None:
                    known = {a.name for a in models}
                    missing_models = [m for m in template.required_models if m not in known]

                # Research is OFFERED on a gap, never run here (Step 5 owns `research`).
                if ctx.is_empty() or ctx.max_local_score() < RESEARCH_GAP_THRESHOLD:
                    research_offer = intent

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    # Append outside the tracker so a budget-truncated craft still persists nothing partial:
    # only a fully-crafted spec is written.
    if spec is not None:
        append_spec(out_path, spec, project=project)

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass

    return DraftResult(
        spec=spec if spec is not None else VisualSpec(prompt="", heading=""),
        batch_path=out_path if spec is not None else None,
        template_name=template.name if template else None,
        tutor_notes=tutor_notes,
        missing_models=missing_models,
        research_offer=research_offer,
        overall_reasoning=overall_reasoning,
        run_id=run_id,
        status=status if spec is not None else "failed",
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def draft_sync(intent: str, **kwargs: Any) -> DraftResult:
    """Synchronous wrapper for draft()."""
    return asyncio.run(draft(intent, **kwargs))
