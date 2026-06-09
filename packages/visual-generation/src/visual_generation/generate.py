"""generate — Phase B, the deliberate GPU spend.

Split into plan → spend so the soft-inform GPU gate can show the estimated
session cost before anything is submitted (the voiceover plan/spend boundary):

- `plan_generation` — read the batch, select target specs, resolve each spec's
  workflow template, build the concrete prompt graph (slot_map), resolve seeds,
  and compute the gate estimate (per-run estimate × batch size). No network, no
  Claude, no GPU.
- `spend_generation` — open a warm ComfyUI session and drain the plan: submit →
  poll history → fetch the image → write the asset (identity_bearing RE-DERIVED
  from the registry, never trusted from the batch file) → upsert a PENDING
  generation (multimodal embed) → record per-run GPU seconds + cost. The GPU
  cost is agent-local; it never enters the Claude BudgetEnvelope.

Pod start/stop stays Tier-1 advisory (Q4): the agent talks only to the ComfyUI
endpoint the user provides — no RunPod credential, no RunPod stop.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    MemoryStore,
    TracePersister,
    get_memory_store,
    notify_run_complete,
    render_run_report,
)
from opentelemetry import trace

from visual_generation.assets import write_asset
from visual_generation.batch_file import read_batch
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.constants import (
    AGENT_NAME,
    DEFAULT_ASSET_EXT,
    DEFAULT_GPU_RATE_USD_PER_HR,
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_POLL_TIMEOUT_SEC,
    GENERATE_BUDGET,
    GPU_COST_SPAN_ATTR,
    GPU_SECONDS_SPAN_ATTR,
    SESSION_COST_SPAN_ATTR,
)
from visual_generation.graph_build import build_prompt_graph
from visual_generation.gpu_tracker import GpuLedger, SessionMeter, estimate_per_run_cost
from visual_generation.identity import derive_identity_bearing
from visual_generation.models import (
    GenerationBatch,
    GenerationResult,
    VisualGeneration,
    VisualResult,
    VisualSpec,
    WorkflowTemplate,
    _new_id,
)
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


# ── Plan structures ──────────────────────────────────────────────────────────


@dataclass
class SpecPlan:
    """One spec resolved to a concrete graph, ready to submit."""

    spec: VisualSpec
    template: WorkflowTemplate
    graph: dict[str, Any]
    resolved_seed: int | None
    unmapped: list[str] = field(default_factory=list)


@dataclass
class GenerationPlan:
    project: str | None
    plans: list[SpecPlan] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # spec ids skipped (no template, etc.)
    per_run_estimate_usd: float = 0.0
    estimate_source: str = "default"
    gpu_rate_usd_per_hr: float = DEFAULT_GPU_RATE_USD_PER_HR

    @property
    def estimated_session_cost_usd(self) -> float:
        return self.per_run_estimate_usd * len(self.plans)


# ── Helpers ──────────────────────────────────────────────────────────────────


def select_specs(
    batch: GenerationBatch, *, section_id: str | None = None, all_sections: bool = False
) -> list[VisualSpec]:
    """Resolve target specs. Raises ValueError on an unknown id or no selection."""
    if all_sections:
        return list(batch.specs)
    if section_id is not None:
        match = [s for s in batch.specs if s.spec_id == section_id]
        if not match:
            known = ", ".join(s.spec_id for s in batch.specs) or "(none)"
            raise ValueError(f"Unknown section id {section_id!r}. Known specs: {known}")
        return match
    raise ValueError("Specify a spec (--section <id>) or --all.")


def _resolve_seed(spec: VisualSpec) -> int | None:
    if spec.seed_strategy == "random":
        return random.randint(0, 2**32 - 1)
    return spec.seed


def _ext_for(filename: str) -> str:
    suffix = Path(filename).suffix.lstrip(".").lower()
    return suffix or DEFAULT_ASSET_EXT


def _caption_for(spec: VisualSpec) -> str:
    return (spec.prompt or spec.heading or "generation")[:300]


def _settings_recipe(sp: SpecPlan) -> dict[str, Any]:
    return {
        "model": sp.spec.model,
        "seed": sp.resolved_seed,
        "width": sp.spec.width,
        "height": sp.spec.height,
        "settings": sp.spec.settings,
        "lora_stack": [lr.model_dump() for lr in sp.spec.lora_stack],
        "workflow_ref": sp.spec.workflow_ref,
    }


def _record_gpu(per_run_seconds: float, per_run_cost: float, session_cost: float) -> None:
    span = trace.get_current_span()
    span.set_attribute(GPU_SECONDS_SPAN_ATTR, per_run_seconds)
    span.set_attribute(GPU_COST_SPAN_ATTR, per_run_cost)
    span.set_attribute(SESSION_COST_SPAN_ATTR, session_cost)


# ── Plan phase ───────────────────────────────────────────────────────────────


async def plan_generation(
    batch_path: str | Path,
    *,
    section_id: str | None = None,
    all_sections: bool = False,
    gpu_rate: float = DEFAULT_GPU_RATE_USD_PER_HR,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> GenerationPlan:
    """Resolve target specs to concrete graphs and compute the gate estimate."""
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    batch = read_batch(Path(batch_path))
    targets = select_specs(batch, section_id=section_id, all_sections=all_sections)

    plans: list[SpecPlan] = []
    skipped: list[str] = []
    for spec in targets:
        template = (
            await store.get_template_by_name(spec.workflow_ref) if spec.workflow_ref else None
        )
        if template is None:
            skipped.append(spec.spec_id)
            continue
        graph, unmapped = build_prompt_graph(spec, template)
        plans.append(
            SpecPlan(
                spec=spec,
                template=template,
                graph=graph,
                resolved_seed=_resolve_seed(spec),
                unmapped=unmapped,
            )
        )

    prior_costs = await store.recent_generation_costs()
    per_run, source = estimate_per_run_cost(prior_costs, gpu_rate)

    return GenerationPlan(
        project=batch.project,
        plans=plans,
        skipped=skipped,
        per_run_estimate_usd=per_run,
        estimate_source=source,
        gpu_rate_usd_per_hr=gpu_rate,
    )


# ── Spend phase ──────────────────────────────────────────────────────────────


async def spend_generation(
    plan: GenerationPlan,
    *,
    endpoint: str,
    gpu_rate: float = DEFAULT_GPU_RATE_USD_PER_HR,
    max_session_cost: float | None = None,
    budget: BudgetEnvelope | None = None,
    store: VisualGenerationStore | None = None,
    client: ComfyUIClient | None = None,
    ledger: GpuLedger | None = None,
    clock: Callable[[], float] = time.monotonic,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SEC,
    poll_timeout: float = DEFAULT_POLL_TIMEOUT_SEC,
) -> GenerationResult:
    """Drain the plan against a warm ComfyUI session, writing pending generations.

    `--max-session-cost` (if set) is an optional HARD ceiling: once the running
    session cost plus the next per-run estimate would exceed it, the drain stops
    (status `partial`, `drained=False`). GPU spend never enters the budget.
    """
    store = store or VisualGenerationStore(get_memory_store())
    await store.ensure_collection()
    client = client or ComfyUIClient(endpoint)
    ledger = ledger or GpuLedger()
    meter = SessionMeter(gpu_rate, clock=clock)

    status = "completed"
    drained = True
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    results: list[VisualResult] = []
    skipped = list(plan.skipped)
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or GENERATE_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                meter.begin()
                for sp in plan.plans:
                    tracker.check_budget()
                    # Hard ceiling: stop before spending if it would breach.
                    if max_session_cost is not None and (
                        meter.running_cost() + plan.per_run_estimate_usd
                    ) > max_session_cost:
                        status = "partial"
                        drained = False
                        break

                    t0 = clock()
                    prompt_id = await client.submit(sp.graph)
                    record = await _poll_history(
                        client, prompt_id, poll_interval, poll_timeout, clock
                    )
                    images = client.images_from_history(record)
                    if not images:
                        # No output produced — leave it for the user to re-run; don't fabricate.
                        skipped.append(sp.spec.spec_id)
                        continue

                    img = images[0]
                    data = await client.view(
                        img["filename"], subfolder=img.get("subfolder", ""), type=img.get("type", "output")
                    )

                    # Security decision: re-derive from the registry (never the file).
                    identity = derive_identity_bearing(sp.spec, store.get_model)
                    gen_id = _new_id()
                    asset_path = write_asset(
                        data,
                        project=sp.spec.project,
                        gen_id=gen_id,
                        identity_bearing=identity,
                        ext=_ext_for(img["filename"]),
                    )

                    per_run_seconds = clock() - t0
                    per_run_cost = meter.per_run_cost(per_run_seconds)
                    meter.add_run(per_run_seconds)
                    running_cost = meter.running_cost()

                    gen = VisualGeneration(
                        entry_id=gen_id,
                        caption=_caption_for(sp.spec),
                        asset_path=str(asset_path),
                        prompt=sp.spec.prompt,
                        negative_prompt=sp.spec.negative_prompt,
                        settings=sp.spec.settings,
                        model=sp.spec.model,
                        lora_stack=sp.spec.lora_stack,
                        workflow_ref=sp.spec.workflow_ref,
                        seed=sp.resolved_seed,
                        width=sp.spec.width,
                        height=sp.spec.height,
                        cost_usd=per_run_cost,
                        identity_bearing=identity,
                        project=sp.spec.project,
                    )
                    await store.upsert_generation(gen)
                    _record_gpu(per_run_seconds, per_run_cost, running_cost)
                    tracker.add_item_processed()

                    results.append(
                        VisualResult(
                            generation_id=gen_id,
                            spec_id=sp.spec.spec_id,
                            asset_path=str(asset_path),
                            identity_bearing=identity,
                            settings_recipe=_settings_recipe(sp),
                            rationale=sp.spec.rationale,
                            gpu_cost_usd=per_run_cost,
                            session_cost_running_usd=running_cost,
                        )
                    )
                meter.end()

    except BudgetExhaustedError:
        status = "partial"
        drained = False

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    session_cost = meter.session_cost()
    ledger.record_session(session_cost)

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass
        notify_run_complete(AGENT_NAME, run_id, status, cost_usd)

    return GenerationResult(
        results=results,
        skipped=skipped,
        run_id=run_id,
        status=status,
        items_processed=len(results),
        session_cost_usd=session_cost,
        gpu_rate_usd_per_hr=gpu_rate,
        drained=drained,
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


async def _poll_history(
    client: ComfyUIClient,
    prompt_id: str,
    poll_interval: float,
    poll_timeout: float,
    clock: Callable[[], float],
) -> dict[str, Any]:
    """Poll /history until the run produces outputs or the timeout elapses.

    A mocked client that returns the record immediately exits on the first pass
    (no sleep). `clock` is the injected time source so the deadline is deterministic.
    """
    deadline = clock() + poll_timeout
    while True:
        record = await client.history(prompt_id)
        if record and record.get("outputs"):
            return record
        if clock() >= deadline:
            return record or {}
        await asyncio.sleep(poll_interval)


# ── Combined entry (prompt-free; library convenience) ─────────────────────────


async def generate(
    batch_path: str | Path,
    *,
    section_id: str | None = None,
    all_sections: bool = False,
    endpoint: str,
    gpu_rate: float = DEFAULT_GPU_RATE_USD_PER_HR,
    max_session_cost: float | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    client: ComfyUIClient | None = None,
    **spend_kwargs: Any,
) -> GenerationResult:
    """Plan then spend in one call (no gate — the soft-inform gate is the CLI's job)."""
    plan = await plan_generation(
        batch_path,
        section_id=section_id,
        all_sections=all_sections,
        gpu_rate=gpu_rate,
        store=store,
        memory_store=memory_store,
    )
    return await spend_generation(
        plan,
        endpoint=endpoint,
        gpu_rate=gpu_rate,
        max_session_cost=max_session_cost,
        store=store,
        client=client,
        **spend_kwargs,
    )


def plan_generation_sync(batch_path: str | Path, **kwargs: Any) -> GenerationPlan:
    return asyncio.run(plan_generation(batch_path, **kwargs))


def spend_generation_sync(plan: GenerationPlan, **kwargs: Any) -> GenerationResult:
    return asyncio.run(spend_generation(plan, **kwargs))


def generate_sync(batch_path: str | Path, **kwargs: Any) -> GenerationResult:
    return asyncio.run(generate(batch_path, **kwargs))
