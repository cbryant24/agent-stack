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
import hashlib
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
    DEFAULT_DENOISE,
    DEFAULT_GPU_RATE_USD_PER_HR,
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_POLL_TIMEOUT_SEC,
    DEFAULT_POLL_TIMEOUT_SEC_VIDEO,
    DENOISE_COHERENCE_WARN,
    GENERATE_BUDGET,
    GPU_COST_SPAN_ATTR,
    GPU_SECONDS_SPAN_ATTR,
    POSITIVE_REACTIONS,
    SESSION_COST_SPAN_ATTR,
)
from visual_generation.graph_build import apply_source_filenames, build_prompt_graph, write_slot
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
    warnings: list[str] = field(default_factory=list)  # advisory (e.g. high denoise)


@dataclass
class SourceProvision:
    """Result of resolving + uploading a spec's source(s) before submit."""

    parent_id: str | None
    chain_root_id: str | None
    source_image_path: str | None
    source_mask_path: str | None
    parent_last_id: str | None = None  # flf2v last-frame boundary lineage


@dataclass
class GenerationPlan:
    project: str | None
    plans: list[SpecPlan] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # spec ids skipped (no template, gate, etc.)
    skip_reasons: list[str] = field(default_factory=list)  # plain reason per plan-time skip
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


def _effective_settings(spec: VisualSpec) -> dict[str, Any]:
    """Settings as actually run: a copy of the spec's settings with the refinement
    denoise default merged in when a source is set and denoise is unset. The spec
    (and the saved batch file) are never mutated — this is recorded on the
    generation and used to drive the graph at runtime only."""
    settings = dict(spec.settings)
    if spec.source is not None and "denoise" not in settings:
        settings["denoise"] = DEFAULT_DENOISE
    return settings


def _settings_recipe(sp: SpecPlan) -> dict[str, Any]:
    return {
        "model": sp.spec.model,
        "seed": sp.resolved_seed,
        "width": sp.spec.width,
        "height": sp.spec.height,
        "settings": _effective_settings(sp.spec),
        "lora_stack": [lr.model_dump() for lr in sp.spec.lora_stack],
        "workflow_ref": sp.spec.workflow_ref,
    }


class _SourceSkip(Exception):
    """A source spec could not be provisioned — carries the user-facing reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def _advise_ref_exists(
    store: VisualGenerationStore,
    from_generation: str | None,
    image_path: str | None,
    label: str,
) -> list[str]:
    """Advisory (no raise): does a (from_generation | image_path) origin resolve locally?"""
    if from_generation:
        gen = await store.get_generation(from_generation)
        if gen is None:
            return [f"{label} generation {from_generation} not found in memory."]
        if not gen.asset_path or not Path(gen.asset_path).exists():
            return [f"{label} generation {from_generation} has no readable image on disk."]
    elif image_path and not Path(image_path).exists():
        return [f"{label} image {image_path} does not exist."]
    return []


async def _plan_source_advisories(
    spec: VisualSpec, graph: dict[str, Any], slot_map: dict[str, Any], store: VisualGenerationStore
) -> list[str]:
    """Plan-time (no upload) advisories for a source spec, per modality: inject the
    runtime denoise default + coherence warn for img2img/inpaint; warn when an FLF2V
    spec is missing its last frame; and check every referenced origin resolves locally.
    Returns warning strings; never raises (spend re-checks authoritatively)."""
    warnings: list[str] = []
    src = spec.source
    assert src is not None
    is_flf2v = "last_frame" in slot_map
    is_edit = "edit_image_1" in slot_map
    is_img_refine = "init_image" in slot_map and not is_flf2v

    # denoise default + coherence warn is an img2img/inpaint (Z-Image) concern only.
    if is_img_refine:
        denoise = spec.settings.get("denoise")
        if denoise is None:
            denoise = DEFAULT_DENOISE
            write_slot(graph, slot_map, "denoise", denoise)  # runtime graph only
        if isinstance(denoise, (int, float)) and denoise > DENOISE_COHERENCE_WARN:
            warnings.append(
                f"denoise {denoise} > {DENOISE_COHERENCE_WARN}: Z-Image-Turbo loses "
                "coherence past ~0.85 — expect the source frame to wash out."
            )

    warnings += await _advise_ref_exists(store, src.from_generation, src.image_path, "source")

    if is_flf2v:
        if not src.last_frame_ref:
            warnings.append(
                "flf2v spec has no last frame — pass --last-from/--last-image, "
                "or generate will skip it."
            )
        else:
            warnings += await _advise_ref_exists(
                store, src.last_from_generation, src.last_image_path, "last-frame"
            )

    if is_edit:
        for i, ref in enumerate(src.references, start=1):
            warnings += await _advise_ref_exists(
                store, ref.from_generation, ref.image_path, f"reference {i}"
            )

    if src.mask and not Path(src.mask).exists():
        warnings.append(f"mask {src.mask} does not exist.")
    return warnings


def _pod_name(local: Path) -> str:
    """Collision-proof, source-STABLE pod filename: a hash of the resolved local path
    plus the basename. Stable by source identity (not spec id) so the same frame used
    by two clips resolves to the same input-dir name — belt-and-suspenders with the
    session upload cache keyed on the same identity."""
    h = hashlib.sha1(str(local.resolve()).encode()).hexdigest()[:12]
    return f"{h}_{local.name}"


async def _resolve_ref_local(
    store: VisualGenerationStore,
    *,
    from_generation: str | None,
    image_path: str | None,
    spec_id: str,
    label: str,
) -> tuple[Path, str | None, str | None]:
    """Resolve a (from_generation | image_path) origin to a local Path.

    Returns (local_path, gen_id, chain_root_id) — gen_id/chain_root are None for an
    external image path. Raises `_SourceSkip` (plain reason) when it can't resolve."""
    if from_generation:
        gen = await store.get_generation(from_generation)
        local = Path(gen.asset_path) if (gen and gen.asset_path) else None
        if gen is None or local is None or not local.exists():
            raise _SourceSkip(
                f"Skipped {spec_id}: {label} generation {from_generation} "
                "not found / its image is missing"
            )
        return local, from_generation, (gen.chain_root_id or from_generation)
    local = Path(image_path or "")
    if not image_path or not local.exists():
        raise _SourceSkip(f"Skipped {spec_id}: {label} image {image_path} does not exist")
    return local, None, None


def _edit_slot_count(slot_map: dict[str, Any]) -> int:
    return sum(1 for k in slot_map if k.startswith("edit_image_"))


def _is_video_template(slot_map: dict[str, Any]) -> bool:
    """True for a video-OUTPUT template (Wan I2V/FLF2V): a frame slot plus fps/length,
    so its output is an mp4 read via videos_from_history. A Qwen edit template has
    edit_image slots but produces a STILL, so it stays on the image path."""
    return "first_frame" in slot_map and ("fps" in slot_map or "length" in slot_map)


async def _provision_sources(
    client: ComfyUIClient,
    store: VisualGenerationStore,
    sp: SpecPlan,
    *,
    upload_cache: dict[str, str] | None = None,
) -> SourceProvision | None:
    """Resolve + upload a spec's source(s) before submit, writing the pod-side filenames
    into the graph slots for the template's modality:
      img2img/inpaint → init_image (+ mask); FLF2V → first_frame (+ last_frame);
      Qwen edit → edit_image_1..N (base first, then references).
    Returns None for a sourceless (txt2img) spec. `upload_cache` (path→pod filename) is
    a per-session cache so a frame shared by two clips uploads once. Raises `_SourceSkip`
    when a source can't be honored."""
    cache = upload_cache if upload_cache is not None else {}
    src = sp.spec.source
    slots = sp.template.slot_map
    spec_id = sp.spec.spec_id
    has_first = "first_frame" in slots
    has_last = "last_frame" in slots
    has_edit = "edit_image_1" in slots
    has_init = "init_image" in slots

    if src is None:
        # Sourceless (text2img) spec against a graph whose image slots can't be filled
        # without a source — it would 400 at the pod. Skip with a clear reason.
        if has_first or has_edit or has_init:
            need = "first_frame" if has_first else ("edit_image_1" if has_edit else "init_image")
            raise _SourceSkip(
                f"Skipped {spec_id}: no source image, but its template "
                f"'{sp.template.name}' needs {need}. Re-draft with a source "
                "(--from/--image), or pass a text2img --template."
            )
        return None

    async def _upload(local: Path) -> str:
        key = str(local.resolve())
        if key in cache:
            return cache[key]
        pod = await client.upload_image(local.read_bytes(), _pod_name(local))
        cache[key] = pod
        return pod

    # First/base frame (the validator guarantees exactly one origin is set).
    first_local, parent_id, chain_root_id = await _resolve_ref_local(
        store, from_generation=src.from_generation, image_path=src.image_path,
        spec_id=spec_id, label="source",
    )
    first_pod = await _upload(first_local)

    # FLF2V last frame.
    parent_last_id: str | None = None
    last_pod: str | None = None
    if has_last:
        if not src.last_frame_ref:
            raise _SourceSkip(
                f"Skipped {spec_id}: FLF2V template '{sp.template.name}' needs a last "
                "frame — pass --last-from <gen_id> or --last-image <path>."
            )
        last_local, parent_last_id, _ = await _resolve_ref_local(
            store, from_generation=src.last_from_generation, image_path=src.last_image_path,
            spec_id=spec_id, label="last-frame",
        )
        last_pod = await _upload(last_local)

    # Inpaint mask.
    pod_mask: str | None = None
    mask_path: str | None = None
    if src.mask:
        mask_local = Path(src.mask)
        if not mask_local.exists():
            raise _SourceSkip(f"Skipped {spec_id}: mask {src.mask} does not exist")
        pod_mask = await _upload(mask_local)
        mask_path = str(mask_local)

    # Qwen edit images: base is edit_image_1, references follow, capped at slot count.
    edit_images: list[str] | None = None
    if has_edit:
        pods = [first_pod]
        room = max(0, _edit_slot_count(slots) - 1)
        for ref in src.references[:room]:
            ref_local, _, _ = await _resolve_ref_local(
                store, from_generation=ref.from_generation, image_path=ref.image_path,
                spec_id=spec_id, label="reference",
            )
            pods.append(await _upload(ref_local))
        edit_images = pods

    # Write the resolved pod filenames into the template's slots for this modality.
    if has_first:
        unmapped = apply_source_filenames(
            sp.graph, slots, first_frame=first_pod, last_frame=last_pod
        )
    elif has_edit:
        unmapped = apply_source_filenames(sp.graph, slots, edit_images=edit_images)
    else:
        unmapped = apply_source_filenames(sp.graph, slots, init_image=first_pod, mask=pod_mask)

    if "init_image" in unmapped or "first_frame" in unmapped or "edit_image_1" in unmapped:
        raise _SourceSkip(
            f"Skipped {spec_id}: this workflow can't accept the source (no image slot) "
            "— use an img2img/inpaint/video/edit template as appropriate"
        )
    if "mask" in unmapped:
        raise _SourceSkip(
            f"Skipped {spec_id}: this workflow has no mask slot for inpaint "
            "— use an inpaint template or drop the mask"
        )
    if "last_frame" in unmapped:
        raise _SourceSkip(
            f"Skipped {spec_id}: this workflow has no last_frame slot — use an FLF2V template"
        )

    return SourceProvision(
        parent_id=parent_id,
        chain_root_id=chain_root_id,
        source_image_path=str(first_local),
        source_mask_path=mask_path,
        parent_last_id=parent_last_id,
    )


async def _approval_skip_reason(
    spec: VisualSpec,
    template: WorkflowTemplate,
    store: VisualGenerationStore,
    *,
    allow_unapproved: bool,
) -> str | None:
    """The approval gate (G6): a video/edit spec may only build on APPROVED keyframes.

    For every `from_generation` source ref (first frame, FLF2V last frame, Qwen
    references), the referenced generation's reaction must be in POSITIVE_REACTIONS —
    otherwise the spec is skipped (unless `allow_unapproved`). This is the single guard
    that makes FLF2V's "every boundary is an approved still" promise real: it stops a
    clip from being generated against an unapproved (or drifted) keyframe. External
    image sources (no gen id) are not gated — there's no reaction to check. Returns a
    skip reason, or None to proceed."""
    if allow_unapproved or spec.source is None:
        return None
    slots = template.slot_map
    if not ("first_frame" in slots or "edit_image_1" in slots):  # only flf2v/i2v/edit
        return None
    src = spec.source
    refs: list[tuple[str, str]] = []
    if src.from_generation:
        refs.append(("first frame", src.from_generation))
    if src.last_from_generation:
        refs.append(("last frame", src.last_from_generation))
    for i, r in enumerate(src.references, start=1):
        if r.from_generation:
            refs.append((f"reference {i}", r.from_generation))
    for label, gid in refs:
        gen = await store.get_generation(gid)
        if gen is None:
            return (
                f"Skipped {spec.spec_id}: {label} {gid} not found — can't verify "
                "approval (pass --allow-unapproved to override)."
            )
        if gen.reaction not in POSITIVE_REACTIONS:
            return (
                f"Skipped {spec.spec_id}: {label} {gid} is not approved "
                f"(reaction={gen.reaction!r}) — approve it, or pass --allow-unapproved."
            )
    return None


def _primary_workflow_ref(plans: list[SpecPlan]) -> str | None:
    """The most common workflow_ref among planned specs — the template the session's
    cost estimate should be learned from (a sequence render is all one template)."""
    counts: dict[str, int] = {}
    for p in plans:
        ref = p.spec.workflow_ref
        if ref:
            counts[ref] = counts.get(ref, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else None


def _poll_timeout_for(sp: SpecPlan, session_timeout: float) -> float:
    """Per-spec poll ceiling: an explicit `settings["poll_timeout"]` wins; else video
    templates get the longer video ceiling (max with the session value); else the
    session default. Video runs are minutes, not seconds."""
    override = sp.spec.settings.get("poll_timeout")
    if isinstance(override, (int, float)) and override > 0:
        return float(override)
    if _is_video_template(sp.template.slot_map):
        return max(DEFAULT_POLL_TIMEOUT_SEC_VIDEO, session_timeout)
    return session_timeout


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
    allow_unapproved: bool = False,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> GenerationPlan:
    """Resolve target specs to concrete graphs and compute the gate estimate.

    The approval gate (G6) runs here: a video/edit spec building on an unapproved
    source keyframe is skipped with a reason unless `allow_unapproved`. The per-run
    cost estimate is per-template (learned from prior runs of the batch's dominant
    workflow_ref; cold-start is per-modality) so a video session shows an honest total.
    """
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    batch = read_batch(Path(batch_path))
    targets = select_specs(batch, section_id=section_id, all_sections=all_sections)

    plans: list[SpecPlan] = []
    skipped: list[str] = []
    skip_reasons: list[str] = []
    for spec in targets:
        template = (
            await store.get_template_by_name(spec.workflow_ref) if spec.workflow_ref else None
        )
        if template is None:
            skipped.append(spec.spec_id)
            skip_reasons.append(
                f"Skipped {spec.spec_id}: no resolvable workflow template (set "
                "workflow_ref to a registered template)"
            )
            continue
        # Approval gate: don't build a clip/keyframe on an unapproved source keyframe.
        gate = await _approval_skip_reason(
            spec, template, store, allow_unapproved=allow_unapproved
        )
        if gate is not None:
            skipped.append(spec.spec_id)
            skip_reasons.append(gate)
            continue
        graph, unmapped = build_prompt_graph(spec, template)
        warnings: list[str] = []
        if spec.source is not None:
            warnings = await _plan_source_advisories(spec, graph, template.slot_map, store)
        plans.append(
            SpecPlan(
                spec=spec,
                template=template,
                graph=graph,
                resolved_seed=_resolve_seed(spec),
                unmapped=unmapped,
                warnings=warnings,
            )
        )

    # Per-template cost estimate: learn only from the dominant template's prior runs
    # (a video estimate must not be diluted by cheap image runs), with a per-modality
    # cold-start default when there's no history yet.
    primary_ref = _primary_workflow_ref(plans)
    is_video = any(
        _is_video_template(p.template.slot_map)
        for p in plans
        if p.spec.workflow_ref == primary_ref
    )
    prior_costs = await store.recent_generation_costs(workflow_ref=primary_ref)
    per_run, source = estimate_per_run_cost(prior_costs, gpu_rate, is_video=is_video)

    return GenerationPlan(
        project=batch.project,
        plans=plans,
        skipped=skipped,
        skip_reasons=skip_reasons,
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
    # Plan-time skips (no template, approval gate) already carry their reasons.
    skip_reasons: list[str] = list(plan.skip_reasons)
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or GENERATE_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                meter.begin()
                # Per-session upload cache (resolved local path → pod filename): a frame
                # shared by two clips (a scene boundary) uploads once, referenced twice.
                upload_cache: dict[str, str] = {}
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
                    # Source refinement: resolve + upload the init image (and mask),
                    # writing the pod-side filenames into the graph before submit.
                    try:
                        provision = await _provision_sources(
                            client, store, sp, upload_cache=upload_cache
                        )
                    except _SourceSkip as skip:
                        skipped.append(sp.spec.spec_id)
                        skip_reasons.append(skip.reason)
                        continue

                    prompt_id = await client.submit(sp.graph)
                    record = await _poll_history(
                        client, prompt_id, poll_interval, _poll_timeout_for(sp, poll_timeout), clock
                    )
                    is_video = _is_video_template(sp.template.slot_map)
                    outputs = (
                        client.videos_from_history(record)
                        if is_video
                        else client.images_from_history(record)
                    )
                    if not outputs:
                        # No output produced — leave it for the user to re-run; don't fabricate.
                        kind = "video" if is_video else "image"
                        skipped.append(sp.spec.spec_id)
                        skip_reasons.append(
                            f"Skipped {sp.spec.spec_id}: the pod produced no {kind} "
                            "output (re-run, or check the graph/endpoint)"
                        )
                        continue

                    out = outputs[0]
                    data = await client.view(
                        out["filename"], subfolder=out.get("subfolder", ""), type=out.get("type", "output")
                    )

                    # Security decision: re-derive from the registry (never the file).
                    identity = derive_identity_bearing(sp.spec, store.get_model)
                    gen_id = _new_id()
                    asset_path = write_asset(
                        data,
                        project=sp.spec.project,
                        gen_id=gen_id,
                        identity_bearing=identity,
                        ext=_ext_for(out["filename"]),
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
                        settings=_effective_settings(sp.spec),
                        model=sp.spec.model,
                        lora_stack=sp.spec.lora_stack,
                        workflow_ref=sp.spec.workflow_ref,
                        seed=sp.resolved_seed,
                        width=sp.spec.width,
                        height=sp.spec.height,
                        cost_usd=per_run_cost,
                        identity_bearing=identity,
                        project=sp.spec.project,
                        # Lineage: parent_id + inherited chain root for from_generation;
                        # resolved source paths for provenance/repro. None for txt2img.
                        parent_id=provision.parent_id if provision else None,
                        parent_last_id=provision.parent_last_id if provision else None,
                        chain_root_id=(provision.chain_root_id or "") if provision else "",
                        source_image_path=provision.source_image_path if provision else None,
                        source_mask_path=provision.source_mask_path if provision else None,
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
        skip_reasons=skip_reasons,
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
    allow_unapproved: bool = False,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    client: ComfyUIClient | None = None,
    **spend_kwargs: Any,
) -> GenerationResult:
    """Plan then spend in one call (no soft-inform cost gate — that's the CLI's job; the
    approval gate DOES run, inside plan_generation)."""
    plan = await plan_generation(
        batch_path,
        section_id=section_id,
        all_sections=all_sections,
        gpu_rate=gpu_rate,
        allow_unapproved=allow_unapproved,
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
