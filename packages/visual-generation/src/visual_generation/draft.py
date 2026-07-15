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
from typing import Any, Literal

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    LLMProvider,
    MemoryStore,
    TracePersister,
    get_config,
    get_memory_store,
    get_provider,
    render_run_report,
)

from visual_generation.batch_file import append_spec
from visual_generation.canon import (
    canon_loras_for,
    scene_cast,
    subjects_matching,
)
from visual_generation.chains import craft_spec
from visual_generation.discovery import compile_creative_input, discover_scenes
from visual_generation.constants import (
    AGENT_NAME,
    DRAFT_BUDGET,
    RESEARCH_GAP_THRESHOLD,
)
from visual_generation.identity import derive_identity_bearing
from visual_generation.lora_guard import prune_noncanon_identity
from visual_generation.models import (
    DraftResult,
    LoraRef,
    ProvenanceLeg,
    VisualGeneration,
    VisualSource,
    VisualSpec,
    WorkflowTemplate,
)
from visual_generation.retrieval import RetrievedContext, retrieve_context, summarize_provenance
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


async def _resolve_template(
    store: VisualGenerationStore,
    template_name: str | None,
    ctx: RetrievedContext,
    *,
    source: VisualSource | None = None,
) -> WorkflowTemplate | None:
    """By explicit name, else the top retrieved template matching the spec's MODALITY,
    else None (advisory).

    Modality match matters: retrieval ranks templates by prompt similarity, so a text2img
    prompt about screens/TVs can surface the inpaint template first — but an img2img/inpaint
    graph's init_image/mask slots can't be filled without a source, so it 400s at submit.
    So a sourceless draft prefers a pure txt2img template (no init_image slot), and a source
    draft prefers one that can apply the source (init_image, plus mask when the source is
    masked). Falls back to the top retrieved template when nothing matches."""
    if template_name:
        return await store.get_template_by_name(template_name)
    candidates = [t for _, t in ctx.workflow_templates]
    if not candidates:
        return None
    if source is None:
        txt2img = [t for t in candidates if "init_image" not in t.slot_map]
        return (txt2img or candidates)[0]
    wants_mask = source.mask is not None
    matching = [
        t for t in candidates
        if "init_image" in t.slot_map and (("mask" in t.slot_map) if wants_mask else True)
    ]
    return (matching or candidates)[0]


def _template_modality(template: WorkflowTemplate | None) -> str | None:
    """The graph's modality, read from its slots: inpaint (init_image + mask),
    img2img (init_image), else text2img. None when no template resolved."""
    if template is None:
        return None
    slots = template.slot_map
    if "init_image" in slots and "mask" in slots:
        return "inpaint"
    if "init_image" in slots:
        return "img2img"
    return "text2img"


def _default_batch_path(project: str | None) -> Path:
    stem = project or "default"
    return get_config().agent_data_dir / "visual-generation" / "batches" / f"{stem}.batch.md"


def _pin_canon_loras(
    spec: VisualSpec, project: str | None, store: Any, forced: list[str] | None = None
) -> list[str]:
    """Pin each present (or forced) subject's character LoRA into `spec.lora_stack`,
    then re-derive identity_bearing now that canon may have added an identity asset.

    The one deterministic canon channel: a subject the prompt names by alias — or one
    the director forced via `--canon` — brings its registered character LoRA. Canon is
    authoritative for the pinned LoRA's strength value: if the LLM already put the same
    LoRA in the stack at a guessed strength, the canon value overrides it rather than
    being deduped away. Returns human-readable notes for `canon_applied`."""
    notes: list[str] = []
    canon_loras = canon_loras_for(spec.prompt, project, force=forced or ())
    for lr in canon_loras:
        idx = next((i for i, e in enumerate(spec.lora_stack) if e.name == lr.name), None)
        if idx is None:
            spec.lora_stack.append(lr)
            notes.append(f"pinned canon LoRA '{lr.name}'@{lr.strength}")
        elif spec.lora_stack[idx].strength != lr.strength:
            was = spec.lora_stack[idx].strength
            spec.lora_stack[idx] = lr  # canon strength wins over the LLM's guess
            notes.append(f"canon LoRA '{lr.name}' strength {was}→{lr.strength} (canon override)")

    # Avoid two files carrying the same character: drop identity LoRAs the LLM
    # stacked that duplicate a canon pin (e.g. alternate training checkpoints
    # like '*-2500') — the same-character duplication failure mode.

    def _is_identity(name: str) -> bool:
        asset = store.get_model(name)
        return asset is not None and asset.identity_bearing

    pins = {lr.name for lr in canon_loras}
    spec.lora_stack, dropped = prune_noncanon_identity(
        spec.lora_stack, pins, is_identity=_is_identity
    )
    notes += dropped
    spec.identity_bearing = derive_identity_bearing(spec, store.get_model)
    return notes


async def draft(
    intent: str | None = None,
    *,
    points: list[str] | None = None,
    scene: str | None = None,
    projects_dir: str | Path | None = None,
    batch_path: str | Path | None = None,
    template_name: str | None = None,
    project: str | None = None,
    source: VisualSource | None = None,
    denoise: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    force_canon: list[str] | None = None,
    budget: BudgetEnvelope | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_provider: LLMProvider | None = None,
) -> DraftResult:
    """Craft a spec and append it to the batch file.

    The creative input is COMPILED from a small list of key points (`intent` and/or
    `points`) plus the project's own upstream documents (`directed.md`/`brief.md`/…
    discovered by `project`, optionally narrowed to one `--scene`). The director need
    not hand-write a prompt — the LLM composes it from the compiled context + the
    retrieved knowledge.

    When `source` is set, the crafted spec becomes a refinement (img2img / inpaint):
    the compiled input describes the change, and the source — a prior generation or an
    external image, plus an optional mask — is attached so `generate` resolves + uploads
    it and records the parent lineage."""
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    out_path = Path(batch_path) if batch_path else _default_batch_path(project)

    # Compile the creative input from key points + the project's own documents. The
    # director supplies a small list of points (and/or a scene); the agent assembles
    # the context the LLM composes the prompt from.
    compiled = compile_creative_input(
        intent, points, project, scene,
        projects_dir=Path(projects_dir) if projects_dir else None,
    )
    if not compiled.text:
        return DraftResult(
            spec=VisualSpec(prompt="", heading=""),
            status="failed",
            revise_warnings=[
                "Nothing to draft: provide key points (INTENT or --points), or a --scene "
                "of a project with a directed.md/script.md."
            ],
        )

    status: Literal["completed", "partial", "failed"] = "completed"
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    spec: VisualSpec | None = None
    template: WorkflowTemplate | None = None
    compiled_from: list[str] = compiled.sources
    provenance: list[ProvenanceLeg] = []
    tutor_notes: list[str] = []
    missing_models: list[str] = []
    inert_inheritance: list[str] = []
    canon_applied: list[str] = []
    canon_absent: list[str] = []
    # Canon characters this scene names (from the scene body, not the whole brief) — fed
    # into composition so the LLM renders them, and checked again after craft so a
    # silently-dropped lead is surfaced rather than ignored. Subjects the director FORCED
    # via --canon are merged in (deduped) so they're composed in too, and their character
    # LoRAs are pinned regardless of whether the prompt names them.
    forced = list(force_canon or [])
    cast = scene_cast(compiled.focus, project)
    for subj in subjects_matching(forced, project):
        if subj.aliases[0] not in {c.aliases[0] for c in cast}:
            cast.append(subj)
    research_offer: str | None = None
    overall_reasoning = ""
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or DRAFT_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                # Retrieval is queried on the short key points (the full compiled docs
                # would dilute the embedding); the craft sees the full compiled brief.
                ctx = await retrieve_context(compiled.query or compiled.text, store, memory_store)
                provenance = summarize_provenance(ctx)
                template = await _resolve_template(store, template_name, ctx, source=source)
                models = store.list_models()

                # Edit-mode refinement: seed from the parent generation so the draft
                # preserves the source's style/composition rather than rewriting it.
                parent: VisualGeneration | None = None
                if source is not None and source.from_generation:
                    parent = await store.get_generation(source.from_generation)

                prov = llm_provider or get_provider(provider)
                crafted = await craft_spec(
                    compiled.text, ctx, template, models, prov,
                    parent=parent, refinement=(source is not None),
                    model=model, cast=(cast if source is None else None),
                )

                spec = VisualSpec(
                    heading=(crafted["prompt"] or compiled.query or "untitled")[:60],
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
                    source=source,
                    project=project,
                    rationale=crafted["rationale"],
                )
                # Explicit refinement denoise overrides the crafted settings (persisted
                # in the spec; generate's runtime default only applies when unset).
                if denoise is not None:
                    spec.settings["denoise"] = denoise

                # Pre-fill identity_bearing honestly from the registry (the same
                # derivation generate re-runs authoritatively at spend time).
                spec.identity_bearing = derive_identity_bearing(spec, store.get_model)

                # Deterministic canon: pin each present (or --canon forced) subject's
                # character LoRA — the one canon channel that doesn't depend on LLM
                # discretion. Re-derives identity_bearing inside, superseding the
                # pre-fill above.
                canon_applied = _pin_canon_loras(spec, project, store, forced=forced)

                # Did every scene-named canon character actually land in the prompt? A lead
                # the scene features but the shot omitted is surfaced as an advisory (never
                # blocks — an establishing shot may intentionally have no figure).
                if cast:
                    present = {s.aliases[0] for s in scene_cast(spec.prompt, project)}
                    where = f"scene '{scene}'" if scene else "the compiled scene"
                    for subj in cast:
                        if subj.aliases[0] not in present:
                            canon_absent.append(
                                f"'{subj.aliases[0]}' is named in {where} but absent from the "
                                "drafted prompt — re-draft with a point naming them, or proceed "
                                "if this shot intentionally omits them."
                            )

                overall_reasoning = crafted["rationale"]
                tutor_notes = [le.statement for _, le in ctx.technique_lessons]

                if template is not None:
                    known = {a.name for a in models}
                    missing_models = [m for m in template.required_models if m not in known]

                # Warn when the resolved template has no slot for an attribute on the spec
                # (advisory only — the values stay on the spec to future-proof for a
                # template that can apply them). The LoRA check covers any source — parent
                # inheritance *or* a canon-pinned character LoRA — since a missing loader
                # slot silently drops the identity LoRA either way.
                if template is not None:
                    slots = template.slot_map
                    if spec.lora_stack and not any(k.startswith("lora_") for k in slots):
                        inert_inheritance.append(
                            f"{len(spec.lora_stack)} LoRA(s) won't apply: "
                            "this template has no LoRA loader slots."
                        )
                    if (
                        parent is not None
                        and (spec.width is not None or spec.height is not None)
                        and "width" not in slots
                        and "height" not in slots
                    ):
                        inert_inheritance.append(
                            "Inherited dimensions are ignored for this template; "
                            "img2img output size follows the init image."
                        )
                    # Modality vs. source mismatch — caught here, before any GPU spend.
                    modality = _template_modality(template)
                    if source is None and modality in ("img2img", "inpaint"):
                        inert_inheritance.append(
                            f"Template is {modality} but this spec has no source image — "
                            "`generate` will skip it. Re-draft without forcing a refine template."
                        )
                    elif source is not None and modality == "text2img":
                        inert_inheritance.append(
                            "Template is text2img but this spec has a source — it can't img2img; "
                            "`generate` will skip it. Pass --template <img2img/inpaint>."
                        )

                # Research is OFFERED on a gap, never run here (Step 5 owns `research`).
                if ctx.is_empty() or ctx.max_local_score() < RESEARCH_GAP_THRESHOLD:
                    research_offer = compiled.query or compiled.text[:80]

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
        template_modality=_template_modality(template),
        compiled_from=compiled_from,
        provenance=provenance,
        tutor_notes=tutor_notes,
        missing_models=missing_models,
        inert_inheritance=inert_inheritance,
        canon_applied=canon_applied,
        canon_absent=canon_absent,
        research_offer=research_offer,
        overall_reasoning=overall_reasoning,
        run_id=run_id,
        status=status if spec is not None else "failed",
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def draft_sync(intent: str | None = None, **kwargs: Any) -> DraftResult:
    """Synchronous wrapper for draft()."""
    return asyncio.run(draft(intent, **kwargs))


async def batch_project(
    project: str,
    *,
    scenes: list[str] | None = None,
    projects_dir: str | Path | None = None,
    batch_path: str | Path | None = None,
    template_name: str | None = None,
    source: VisualSource | None = None,
    denoise: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_provider: LLMProvider | None = None,
    overwrite: bool = True,
) -> list[DraftResult]:
    """Compile one spec per scene of a project's narrative doc into a single batch file.

    Discovers the scene headings from `directed.md` (else `script.md`), then runs the
    full compile→retrieve→craft→canon `draft` for each scene, appending to one batch
    file. `overwrite` clears an existing file first (so `rebatch` re-creates cleanly).

    When `source` is set (an anchor frame), EVERY scene is compiled as an img2img
    refinement from that one anchor — the lever for cross-scene character continuity.
    The caller is responsible for targeting an img2img `template_name` so the source
    actually applies (see IMG2IMG_TEMPLATE_NAME)."""
    out = Path(batch_path) if batch_path else _default_batch_path(project)
    headings = scenes if scenes is not None else discover_scenes(
        project, projects_dir=Path(projects_dir) if projects_dir else None
    )
    if overwrite and out.exists():
        out.unlink()

    results: list[DraftResult] = []
    for heading in headings:
        results.append(
            await draft(
                None,
                scene=heading,
                project=project,
                projects_dir=projects_dir,
                batch_path=out,
                template_name=template_name,
                source=source,
                denoise=denoise,
                model=model,
                provider=provider,
                store=store,
                memory_store=memory_store,
                llm_provider=llm_provider,
            )
        )
    return results


def batch_project_sync(project: str, **kwargs: Any) -> list[DraftResult]:
    """Synchronous wrapper for batch_project()."""
    return asyncio.run(batch_project(project, **kwargs))


def _failed_redraft(warnings: list[str]) -> DraftResult:
    """A redraft that resolved nothing to revise (no parent / no recipe to preserve)."""
    return DraftResult(
        spec=VisualSpec(prompt="", heading=""),
        status="failed",
        revise_warnings=warnings,
    )


async def redraft(
    gen_id: str,
    change: str,
    *,
    batch_path: str | Path | None = None,
    project: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    force_canon: list[str] | None = None,
    budget: BudgetEnvelope | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
    llm_provider: LLMProvider | None = None,
) -> DraftResult:
    """Prose-only TEXT2IMG revise of a prior generation.

    Loads the parent generation, re-runs the three-collection retrieval (queried on the
    parent's prose + the change, so scene-level priors/lessons surface), and crafts a spec
    that applies ONLY `change` to the parent's prompt. The recipe — seed (re-pinned fixed),
    settings, model, LoRAs, dimensions, and the workflow template — is inherited from the
    parent so continuity can't drift. The spec carries `source=None` (so `generate` renders
    it as text2img, NOT an img2img edit) and records descent via `revised_from=gen_id`."""
    memory_store = memory_store or get_memory_store()
    store = store or VisualGenerationStore(memory_store)
    await store.ensure_collection()

    parent = await store.get_generation(gen_id)
    if parent is None:
        return _failed_redraft([f"generation {gen_id} not found in memory."])

    out_path = Path(batch_path) if batch_path else _default_batch_path(project or parent.project)

    revise_warnings: list[str] = []
    if parent.source_image_path or parent.source_mask_path:
        revise_warnings.append(
            "Parent was an img2img/inpaint result; redraft targets text2img parents — the "
            "revised spec renders fresh from text, it does not edit the parent's pixels."
        )

    # The template must resolve by the parent's name so the recipe/slots are preserved
    # exactly (no semantic re-resolution that could pick a different template).
    if not parent.workflow_ref:
        return _failed_redraft(
            revise_warnings + ["Parent has no workflow_ref; can't preserve the recipe."]
        )
    template = await store.get_template_by_name(parent.workflow_ref)
    if template is None:
        return _failed_redraft(
            revise_warnings
            + [f"Parent's workflow template {parent.workflow_ref!r} is not registered; "
               "can't preserve the recipe."]
        )

    status: Literal["completed", "partial", "failed"] = "completed"
    run_id = ""
    cost_usd = 0.0
    wall_time_sec = 0.0
    spec: VisualSpec | None = None
    tutor_notes: list[str] = []
    canon_applied: list[str] = []
    provenance: list[ProvenanceLeg] = []
    overall_reasoning = ""
    tracker_ref: BudgetTracker | None = None

    try:
        async with BudgetTracker(budget or DRAFT_BUDGET, AGENT_NAME) as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id
            with TracePersister(agent=AGENT_NAME, run_id=run_id):
                ctx = await retrieve_context(f"{parent.prompt}\n\n{change}", store, memory_store)
                provenance = summarize_provenance(ctx)
                models = store.list_models()

                prov = llm_provider or get_provider(provider)
                crafted = await craft_spec(
                    change, ctx, template, models, prov,
                    parent=parent, revise=True, model=model,
                )

                spec = VisualSpec(
                    heading=(crafted["prompt"] or change)[:60],
                    prompt=crafted["prompt"],
                    negative_prompt=crafted["negative_prompt"],
                    settings=crafted["settings"],
                    model=crafted["model"],
                    seed=crafted["seed"],
                    seed_strategy=crafted["seed_strategy"],
                    width=crafted["width"],
                    height=crafted["height"],
                    lora_stack=[LoraRef(**lr) for lr in crafted["lora_stack"]],
                    workflow_ref=template.name,
                    source=None,
                    project=project or parent.project,
                    revised_from=gen_id,
                    rationale=crafted["rationale"],
                )
                # Honest pre-fill from the registry (re-derived authoritatively at generate).
                spec.identity_bearing = derive_identity_bearing(spec, store.get_model)

                # Model-level canon continuity across a redraft: pin the present (or
                # --canon forced) subjects' character LoRAs onto the revised spec.
                canon_applied = _pin_canon_loras(
                    spec, project or parent.project, store, forced=list(force_canon or [])
                )

                overall_reasoning = crafted["rationale"]
                tutor_notes = [le.statement for _, le in ctx.technique_lessons]

    except BudgetExhaustedError:
        status = "partial"

    if tracker_ref is not None:
        snap = tracker_ref._consumption
        cost_usd = snap.cost_usd
        wall_time_sec = snap.wall_time_sec

    if spec is not None:
        append_spec(out_path, spec, project=project or parent.project)

    report_path: Path | None = None
    if run_id:
        try:
            report_path = render_run_report(run_id, AGENT_NAME)
        except FileNotFoundError:
            pass

    return DraftResult(
        spec=spec if spec is not None else VisualSpec(prompt="", heading=""),
        batch_path=out_path if spec is not None else None,
        template_name=template.name,
        template_modality=_template_modality(template),
        tutor_notes=tutor_notes,
        revise_warnings=revise_warnings,
        canon_applied=canon_applied,
        provenance=provenance,
        overall_reasoning=overall_reasoning,
        run_id=run_id,
        status=status if spec is not None else "failed",
        cost_usd=cost_usd,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def redraft_sync(gen_id: str, change: str, **kwargs: Any) -> DraftResult:
    """Synchronous wrapper for redraft()."""
    return asyncio.run(redraft(gen_id, change, **kwargs))
