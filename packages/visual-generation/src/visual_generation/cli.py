"""visual-generation CLI — backend, templates, and the draft→generate→report turn.

Usage:
    visual-generation model sync --endpoint <url> [--yes]
    visual-generation model list
    visual-generation workflow register <exported-api.json> [--name N] [--descriptor D] [--yes]
    visual-generation workflow list
    visual-generation draft "<intent>" [-o batch.md] [--template <name>] [--model sonnet|opus]
    visual-generation redraft <gen_id> "<change>" [-o batch.md] [--project <p>] [--model sonnet|opus]
    visual-generation generate <batch.md> (--section <id> | --all) --endpoint <url>
        [--gpu-rate N] [--max-session-cost N] [--yes]
    visual-generation report <gen_id> --reaction <X> [--rating N] [--notes ...] [--context ...]
    visual-generation quick "<prompt>" --endpoint <url>
        [--video] [--image <seed.png>] [--template N] [--negative-prompt ...] [--seed N]
        [--width N] [--height N] [--length N] [--fps N] [--out PATH] [--yes]
    visual-generation review-pending
    visual-generation chain show <root_id>
    visual-generation batch list <batch.md>
    visual-generation batch rm <batch.md> <spec_id> [--yes]
    visual-generation recall "<query>" [--limit N]
    visual-generation lesson add "<statement>" [--scope ...] [--valence ...]
    visual-generation fact add "<statement>" [--domain ...]
    visual-generation fact ingest-docs <folder> --domain ... [--dry-run] [--yes]
    visual-generation explain "<concept>" [--level full|concise|quiet]
    visual-generation research "<topic>" [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import click

from visual_generation.agent import _get_stores
from visual_generation.batch_file import read_batch
from visual_generation.comfyui_client import ComfyUIClient, ComfyUIError
from visual_generation.constants import (
    DEFAULT_GPU_RATE_USD_PER_HR,
    DEFAULT_POLL_TIMEOUT_SEC,
    EXPLAIN_LEVELS,
    IMG2IMG_TEMPLATE_NAME,
    LESSON_SCOPE_MODEL,
    LESSON_SCOPE_PROMPT,
    LESSON_SCOPE_SETTINGS,
    LESSON_SCOPE_WORKFLOW,
    MECHANICS_DOMAINS,
    POSITIVE_REACTIONS,
    REACTIONS,
)
from visual_generation.canon import ProjectCanon
from visual_generation.curation import (
    CanonEdit,
    add_fact,
    add_lesson,
    commit_workflow,
    edit_canon_subject,
    find_batch_spec,
    find_canon_subject,
    load_graph_file,
    lookup_lesson,
    lookup_model,
    parse_lora,
    plan_workflow,
    remove_batch_spec,
    remove_canon_subject,
    remove_lesson,
    remove_model,
    render_workflow_plan,
    set_canon_subject,
)
from visual_generation.draft import (
    RefinementSourceError,
    batch_project_sync,
    build_refinement_source,
    draft_sync,
    redraft_sync,
)
from visual_generation.explain import explain_sync, render_explain
from visual_generation.generate import plan_generation_sync, spend_generation_sync
from visual_generation.gpu_tracker import GpuLedger
from visual_generation.inspect import (
    get_chain_sync,
    list_pending_sync,
    recall_sync,
    render_chain,
    render_pending,
    render_recall,
)
from visual_generation.lora_guard import strength_warnings
from visual_generation.model_registry import ModelRegistry
from visual_generation.model_sync import parse_object_info, reconcile
from visual_generation.models import LoraRef, VisualSource, WorkflowTemplate
from visual_generation.quick import (
    QuickInvalidSpec,
    QuickLoraUnsafe,
    QuickSeedUnmapped,
    QuickSourceError,
    QuickTemplateNotFound,
    quick_generate_sync,
)
from visual_generation.reads import (
    build_digest,
    list_lessons,
    list_models,
    list_templates,
    render_canon,
    render_digest,
    render_lessons,
    render_models,
    render_provenance,
    render_subject,
    render_templates,
    render_verify,
    show_canon,
)
from visual_generation.report import report_sync
from visual_generation.research import register_delegate_handlers, render_research, research_sync


@click.group()
def cli() -> None:
    """Visual generation agent — ComfyUI backend + workflow templates."""
    # Register the delegate handlers this process uses (idempotent). Done at the
    # group callback so `research` can delegate to tutorial-research for real.
    register_delegate_handlers()


def _echo_lora_strength_warnings(stack: list[LoraRef], *, indent: str = "") -> None:
    """Print LoRA over-strength / dual-identity-stacking advisories for a stack.

    Warn-loudly-allow: surfaced at draft, redraft, and the generate cost gate so
    the operator sees over-strength (which overrides the prompt + bleeds identity)
    before spending GPU. Identity classification comes from the registry.
    """
    if not stack:
        return
    registry = ModelRegistry()

    def _is_identity(name: str) -> bool:
        asset = registry.get_model(name)
        return asset is not None and asset.identity_bearing

    warns = strength_warnings(stack, is_identity=_is_identity)
    if warns:
        click.echo(f"{indent}⚠ LoRA strength advisories:")
        for w in warns:
            click.echo(f"{indent}  • {w}")


def _echo_unmapped_warning(
    unmapped: list[str], template_name: str, *, label: str = "", indent: str = ""
) -> None:
    """Warn that requested values have no slot in the template and never reach the render.

    Advisory only: the render still runs, just without these values. (A missing seed
    slot is not advisory — plan/quick refuse before this is reached.)
    """
    if not unmapped:
        return
    where = f"{label}: " if label else ""
    click.echo(
        f"{indent}⚠ {where}template '{template_name}' has no slot for: {', '.join(unmapped)} "
        "— these will NOT affect the render."
    )


# ── model (registry sync from ComfyUI /object_info) ──────────────────────────


@cli.group()
def model() -> None:
    """Manage the model/LoRA registry."""


@model.command("sync")
@click.option("--endpoint", required=True, help="ComfyUI endpoint URL (the pod you spun up).")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the confirmation prompt.")
def model_sync(endpoint: str, yes: bool) -> None:
    """Sync the registry from a ComfyUI endpoint's /object_info (merge-aware).

    Manual metadata — chiefly identity_bearing — is preserved on assets that
    already exist by name. A manually-registered asset absent from this pod is
    kept and flagged (not present); a previously-synced asset that's gone is dropped.
    """
    registry = ModelRegistry()

    async def _fetch() -> dict:
        return await ComfyUIClient(endpoint).object_info()

    try:
        object_info = asyncio.run(_fetch())
    except ComfyUIError as exc:
        raise click.ClickException(str(exc)) from exc

    synced = parse_object_info(object_info)
    existing = registry.list_models()
    result = reconcile(existing, synced)

    click.echo(f"Endpoint: {endpoint}")
    click.echo(
        f"Sync plan: +{len(result.added)} new, ~{len(result.refreshed)} refreshed, "
        f"{len(result.kept_absent)} kept-absent, -{len(result.dropped)} dropped."
    )
    if result.kept_absent:
        click.echo("  Kept (registered but absent from this pod):")
        for name in result.kept_absent:
            asset = next(a for a in existing if a.name == name)
            flag = " [identity-bearing]" if asset.identity_bearing else ""
            click.echo(f"    - {name}{flag}")
    if result.dropped:
        click.echo(f"  Dropped (previously synced, now absent): {', '.join(result.dropped)}")

    if not yes:
        click.confirm("Write this registry?", abort=True)

    registry.replace(result.merged)
    click.echo(f"Registry written: {len(result.merged)} asset(s) at {registry.path}")


@model.command("list")
def model_list() -> None:
    """List registered model/LoRA assets (identity_bearing and presence shown)."""
    click.echo(render_models(list_models()))


@model.command("rm")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the confirmation prompt.")
def model_rm(name: str, yes: bool) -> None:
    """Unregister a model/LoRA by NAME (registry-only; the pod file is untouched).

    Use this to retire scratch assets — e.g. alternate training checkpoints from a
    bake-off — so `draft` stops surfacing and stacking them. Identity-bearing LoRAs
    left in the registry get pulled into specs by the drafter; removing the entry is
    the clean fix.
    """
    registry = ModelRegistry()
    try:
        asset = lookup_model(name, registry)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    flag = " [identity-bearing]" if asset.identity_bearing else ""
    click.echo(f"Will unregister: [{asset.kind}] {name}{flag}")
    if not yes:
        click.confirm("Remove this entry from the registry?", abort=True)
    remove_model(name, registry)
    click.echo(f"Unregistered {name}. Registry now at {registry.path}")


# ── workflow (template registration from an exported API graph) ──────────────


@cli.group()
def workflow() -> None:
    """Manage reusable ComfyUI workflow templates."""


@workflow.command("register")
@click.argument("graph_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", default=None, help="Template name (default: the file stem).")
@click.option("--descriptor", default=None,
              help="Short descriptor (embedded for retrieval). Prompted if omitted.")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Accept the inferred slot map without interactive confirmation.")
def workflow_register(graph_file: str, name: str | None, descriptor: str | None, yes: bool) -> None:
    """Register an exported API-format ComfyUI GRAPH_FILE as a workflow template.

    Loads the graph, infers candidate slots (propose→confirm), checks required
    models against the registry, and stores the result as a WorkflowTemplate.
    """
    path = Path(graph_file)
    try:
        graph = load_graph_file(path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    name = name or path.stem
    plan = plan_workflow(graph, name)

    # ── Propose ──────────────────────────────────────────────────────────────
    click.echo(render_workflow_plan(plan))

    # ── Confirm / correct ────────────────────────────────────────────────────
    add_negative = False
    if not yes:
        # The one genuinely ambiguous slot the heuristic can offer to correct:
        # a suppressed negative whose placeholder node we actually know.
        if plan.negative_suppressed and plan.negative_candidate is not None:
            add_negative = click.confirm(
                "Negative prompt was suppressed. Add a negative slot at the traced node?",
                default=False,
            )
        if not click.confirm("Accept this slot map?", default=True):
            raise click.ClickException("Aborted — re-export or edit the graph and retry.")

    # ── Required-model advisory (never blocks) ───────────────────────────────
    if plan.required_models:
        click.echo(f"\nRequired models: {', '.join(plan.required_models)}")
    if plan.missing_models:
        click.echo(
            f"  ⚠ Not in registry (run `model sync` against a pod that has them): "
            f"{', '.join(plan.missing_models)}"
        )

    if descriptor is None:
        descriptor = click.prompt("Descriptor (what this template serves)", default=name)

    async def _store() -> WorkflowTemplate:
        store, _ = _get_stores()
        return await commit_workflow(plan, descriptor, store, add_negative=add_negative)

    template = asyncio.run(_store())
    click.echo(
        f"\nRegistered template '{name}' ({template.entry_id[:12]}) with {len(template.slot_map)} slot(s)."
    )


@workflow.command("list")
@click.option("--query", default="", help="Optional semantic query (default: list recent).")
@click.option("--limit", default=20, show_default=True)
def workflow_list(query: str, limit: int) -> None:
    """List registered workflow templates."""

    async def _run() -> None:
        store, _ = _get_stores()
        listing = await list_templates(store, query=query, limit=limit)
        click.echo(render_templates(listing))

    asyncio.run(_run())


# ── draft (Phase A — free prompt-craft) ──────────────────────────────────────


def _echo_provenance(legs: list) -> None:
    """Render the deterministic 'what was surfaced' block (shared by draft/redraft)."""
    if legs:
        click.echo(render_provenance(legs))


_REFINEMENT_FLAG_MESSAGES = {
    "both_origins": "Use only one of --from / --image (a source has one origin).",
    "mask_without_source": "--mask requires a source (--from or --image).",
}


@cli.command()
@click.argument("intent", required=False)
@click.option("--points", "points", multiple=True,
              help="A key point for the image (repeatable). The agent compiles these + the "
                   "project's docs into the prompt — no need to hand-write one.")
@click.option("--scene", "scene", default=None,
              help="Narrow the compiled context to one scene (a heading in directed.md/script.md).")
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Batch file to append to (default: <project>.batch.md under agent-data).")
@click.option("--template", "template_name", default=None,
              help="Workflow template name to target (default: the top retrieved template).")
@click.option("--project", default=None, help="Project tag for the spec (also the doc-discovery slug).")
@click.option("--from", "from_generation", default=None,
              help="Refine a prior generation by id (img2img/inpaint) — its saved frame "
                   "becomes the source. Mutually exclusive with --image.")
@click.option("--image", "image_path", type=click.Path(dir_okay=False), default=None,
              help="Refine from an external image on disk. Mutually exclusive with --from.")
@click.option("--mask", "mask_path", type=click.Path(dir_okay=False), default=None,
              help="Inpaint mask PNG (white = area to change). Requires --from or --image.")
@click.option("--denoise", type=float, default=None,
              help="Refinement denoise (default 0.5; coherent range ~0.4–0.7).")
@click.option("--model", "model", default=None,
              help="Model alias (sonnet|opus) or a concrete id; the provider resolves it.")
@click.option("--provider", "provider", default=None,
              help="LLM provider for the craft (anthropic|openai; default: config).")
@click.option("--canon", "canon_force", multiple=True,
              help="Force a canon subject (by any alias) into the compose-time cast and "
                   "pin its character LoRA even if the prompt doesn't name it. "
                   "Repeatable. Use when the model refers to a subject by other words.")
def draft(intent: str | None, points: tuple[str, ...], scene: str | None,
          output: str | None, template_name: str | None, project: str | None,
          from_generation: str | None, image_path: str | None, mask_path: str | None,
          denoise: float | None, model: str | None, provider: str | None,
          canon_force: tuple[str, ...]) -> None:
    """Craft a settled generation spec and append it to a batch file. Free.

    Give a few key points (INTENT and/or --points) — optionally a --scene — and the
    agent COMPILES the project's own documents (directed.md/brief.md/…) plus retrieved
    knowledge into the prompt; the LLM composes it. No hand-writing prompts.

    With --from/--image the spec becomes a refinement (img2img/inpaint): the points are
    the change to make, the source is resolved + uploaded at `generate`, and the new
    generation records parent lineage.
    """
    try:
        source, template_name = build_refinement_source(
            from_generation, image_path, mask_path, template_name
        )
    except RefinementSourceError as exc:
        raise click.UsageError(_REFINEMENT_FLAG_MESSAGES[exc.code]) from exc

    result = draft_sync(
        intent,
        points=list(points) or None,
        scene=scene,
        batch_path=output,
        template_name=template_name,
        project=project,
        source=source,
        denoise=denoise,
        model=model,
        provider=provider,
        force_canon=list(canon_force) or None,
    )

    if result.status == "failed":
        click.echo("Draft failed (no spec produced).", err=True)
        for w in result.revise_warnings:
            click.echo(f"  • {w}", err=True)
        raise SystemExit(1)

    spec = result.spec
    click.echo(f"Status:   {result.status}")
    click.echo(f"Cost:     ${result.cost_usd:.4f}  (Claude — GPU is spent at `generate`)")
    click.echo(f"Spec:     {spec.spec_id}")
    modality = f"  [{result.template_modality}]" if result.template_modality else ""
    click.echo(f"Template: {result.template_name or '(none — settings are unconstrained)'}{modality}")
    click.echo(f"Model:    {spec.model or '(none chosen)'}"
               + ("  [identity-bearing]" if spec.identity_bearing else ""))
    if spec.source is not None:
        origin = (
            f"generation {spec.source.from_generation}"
            if spec.source.from_generation
            else f"image {spec.source.image_path}"
        )
        mode = "inpaint" if spec.source.mask else "img2img"
        click.echo(f"Refining: {origin}  [{mode}]"
                   + (f"  mask {spec.source.mask}" if spec.source.mask else ""))
        click.echo(f"Denoise:  {spec.settings.get('denoise', '0.5 (runtime default)')}")
    click.echo(f"\nPrompt:   {spec.prompt}")
    if spec.negative_prompt:
        click.echo(f"Negative: {spec.negative_prompt}")
    if spec.settings:
        click.echo(f"Settings: {spec.settings}")
    if spec.lora_stack:
        click.echo("LoRAs:    " + ", ".join(f"{lr.name}@{lr.strength}" for lr in spec.lora_stack))
    _echo_lora_strength_warnings(spec.lora_stack)
    if result.inert_inheritance:
        click.echo("\n⚠ Inherited but not applied (this template lacks the slots):")
        for w in result.inert_inheritance:
            click.echo(f"  • {w}")
    if result.compiled_from:
        click.echo("\n── Compiled from (your project docs) ────────────────")
        for src in result.compiled_from:
            click.echo(f"  • {src}")

    _echo_provenance(result.provenance)

    if result.overall_reasoning:
        click.echo(f"\nRationale: {result.overall_reasoning}")

    if result.canon_applied:
        click.echo("\n── Canon applied (LoRA pins) ────────────────────────")
        for note in result.canon_applied:
            click.echo(f"  • {note}")

    if result.canon_absent:
        click.echo("\n⚠ Canon character(s) named in this scene but ABSENT from the prompt:")
        for note in result.canon_absent:
            click.echo(f"  • {note}")

    if result.tutor_notes:
        click.echo("\n── Your own technique lessons (relevant) ────────────")
        for note in result.tutor_notes:
            click.echo(f"  • {note}")

    if result.missing_models:
        click.echo("\n⚠ Required models NOT in the registry (resolve BEFORE spin-up):")
        click.echo(f"  {', '.join(result.missing_models)}")
        click.echo("  Run `model sync --endpoint <url>` against a pod that has them.")

    if result.research_offer:
        click.echo(
            f"\nKnowledge gap — little local context for this. Consider (Step 5):\n"
            f'  agent visual-generation research "{result.research_offer}"'
        )

    if result.batch_path:
        click.echo(f"\nAppended to: {result.batch_path}")
        click.echo(f"Next: agent visual-generation generate {result.batch_path} --section "
                   f"{spec.spec_id} --endpoint <url>")


# ── redraft (Phase A — prose-only text2img revise) ───────────────────────────


@cli.command()
@click.argument("gen_id")
@click.argument("change")
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Batch file to append to (default: <project>.batch.md under agent-data).")
@click.option("--project", default=None, help="Project tag for the spec (default: the parent's).")
@click.option("--model", "model", default=None,
              help="Model alias (sonnet|opus) or a concrete id; the provider resolves it.")
@click.option("--provider", "provider", default=None,
              help="LLM provider for the craft (anthropic|openai; default: config).")
@click.option("--canon", "canon_force", multiple=True,
              help="Force a canon subject's character LoRA pin onto the revised spec even "
                   "if the prompt doesn't name it (revise mode has no cast). Repeatable.")
def redraft(gen_id: str, change: str, output: str | None, project: str | None,
            model: str | None, provider: str | None, canon_force: tuple[str, ...]) -> None:
    """Revise a prior generation's PROMPT (text2img) by applying CHANGE. Free.

    Inherits the parent's seed, recipe, model, LoRAs, dimensions, and workflow template so
    only the prose changes — continuity can't drift. The new spec is text2img (not an
    img2img edit of the parent's pixels) and records descent via `revised_from`.
    """
    result = redraft_sync(
        gen_id, change, batch_path=output, project=project, model=model, provider=provider,
        force_canon=list(canon_force) or None,
    )

    if result.status == "failed":
        click.echo("Redraft failed:", err=True)
        for w in result.revise_warnings or ["no spec produced."]:
            click.echo(f"  • {w}", err=True)
        raise SystemExit(1)

    spec = result.spec
    click.echo(f"Status:    {result.status}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}  (Claude — GPU is spent at `generate`)")
    click.echo(f"Spec:      {spec.spec_id}")
    click.echo(f"Revised from: {spec.revised_from}")
    modality = f" [{result.template_modality}]" if result.template_modality else ""
    click.echo(f"Template:  {result.template_name}{modality}  (recipe inherited from parent)")
    click.echo(f"Model:     {spec.model or '(none)'}"
               + ("  [identity-bearing]" if spec.identity_bearing else ""))
    click.echo(f"Seed:      {spec.seed}  ({spec.seed_strategy})")
    if spec.settings:
        click.echo(f"Settings:  {spec.settings}")
    if spec.lora_stack:
        click.echo("LoRAs:     " + ", ".join(f"{lr.name}@{lr.strength}" for lr in spec.lora_stack))
    _echo_lora_strength_warnings(spec.lora_stack)
    click.echo(f"\nPrompt:    {spec.prompt}")
    if spec.negative_prompt:
        click.echo(f"Negative:  {spec.negative_prompt}")
    _echo_provenance(result.provenance)

    if result.overall_reasoning:
        click.echo(f"\nRationale: {result.overall_reasoning}")

    if result.canon_applied:
        click.echo("\n── Canon applied (LoRA pins) ────────────────────────")
        for note in result.canon_applied:
            click.echo(f"  • {note}")

    if result.revise_warnings:
        click.echo("\n⚠ Advisories:")
        for w in result.revise_warnings:
            click.echo(f"  • {w}")

    if result.tutor_notes:
        click.echo("\n── Your own technique lessons (relevant) ────────────")
        for note in result.tutor_notes:
            click.echo(f"  • {note}")

    if result.batch_path:
        click.echo(f"\nAppended to: {result.batch_path}")
        click.echo(f"Next: agent visual-generation generate {result.batch_path} --section "
                   f"{spec.spec_id} --endpoint <url>")


def _resolve_anchor(
    from_generation: str | None, image_path: str | None, template_name: str | None
) -> "tuple[VisualSource | None, str | None]":
    """Turn the batch anchor options into (source, template_name).

    Mirrors the single-`draft` source convention: --from / --image are mutually
    exclusive. When an anchor is given but no --template, default to the img2img
    template so the source actually applies (a txt2img graph silently drops it)."""
    if from_generation and image_path:
        raise click.UsageError("Use only one of --from / --image (an anchor has one origin).")
    if not (from_generation or image_path):
        return None, template_name
    source = VisualSource(from_generation=from_generation, image_path=image_path)
    return source, template_name or IMG2IMG_TEMPLATE_NAME


def _run_batch(project: str, output: str | None, model: str | None, provider: str | None,
               *, overwrite: bool, source: "VisualSource | None" = None,
               denoise: float | None = None, template_name: str | None = None) -> None:
    """Shared body for `batch build`/`batch rebuild`: compile one spec per scene of the
    project's directed.md (else script.md) into a single batch file.

    When `source` is set, every scene is compiled as an img2img refinement from that one
    anchor frame (cross-scene continuity); `template_name` defaults to the img2img graph
    so the source actually applies."""
    from visual_generation.draft import _default_batch_path

    out = Path(output) if output else _default_batch_path(project)
    if out.exists() and not overwrite:
        click.echo(
            f"Batch file already exists: {out}\nUse `batch rebuild` to re-create it, or -o "
            "for a new path.",
            err=True,
        )
        raise SystemExit(1)

    if source is not None:
        anchor = source.from_generation or source.image_path
        click.echo(
            f"Anchoring every scene to {anchor!r} via img2img "
            f"(template {template_name!r}, denoise {denoise if denoise is not None else 'default 0.5'})."
        )

    results = batch_project_sync(
        project, batch_path=output, model=model, provider=provider, overwrite=overwrite,
        source=source, denoise=denoise, template_name=template_name,
    )
    if not results:
        click.echo(
            f"No scenes found for {project!r} — needs a directed.md or script.md with `##` "
            "scene headings in ~/agent-projects/<project>/.",
            err=True,
        )
        raise SystemExit(1)

    drafted = [r for r in results if r.status != "failed"]
    click.echo(f"Compiled {len(drafted)}/{len(results)} scene(s) for {project!r}:")
    for r in results:
        if r.status == "failed":
            click.echo(f"  ✗ {r.spec.heading or '(scene)'} — {'; '.join(r.revise_warnings) or 'failed'}")
        else:
            srcs = f"  [from {', '.join(r.compiled_from)}]" if r.compiled_from else ""
            click.echo(f"  • {r.spec.spec_id}  {r.spec.heading}{srcs}")
    if drafted:
        click.echo(f"\nWrote: {drafted[0].batch_path}")
        click.echo(f"Review/edit, then: agent visual-generation generate {drafted[0].batch_path} "
                   "--all --endpoint <url>")


# ── generate (Phase B — GPU spend, soft-inform gate) ─────────────────────────


@cli.command()
@click.argument("batch", type=click.Path(exists=True, dir_okay=False))
@click.option("--section", "section_id", default=None, help="Generate one spec by id.")
@click.option("--all", "all_sections", is_flag=True, default=False, help="Generate every spec.")
@click.option("--endpoint", required=True, help="ComfyUI endpoint URL (the pod you spun up).")
@click.option("--gpu-rate", type=float, default=None,
              help=f"GPU $/hr for cost tracking (default: {DEFAULT_GPU_RATE_USD_PER_HR}).")
@click.option("--max-session-cost", type=float, default=None,
              help="Optional HARD ceiling (USD) — stop draining before it's breached.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the soft-inform gate.")
def generate(batch: str, section_id: str | None, all_sections: bool, endpoint: str,
             gpu_rate: float | None, max_session_cost: float | None, yes: bool) -> None:
    """Generate asset(s) for spec(s) of a BATCH file against a ComfyUI pod. Spends GPU.

    Advisory spin-up (Q4): you spin up the pod and pass its ComfyUI --endpoint; the
    agent issues no RunPod calls. The gate's cost figures are GPU-LOCAL estimates,
    not a live RunPod balance, and uptime is an approximate proxy (real billing
    started at your spin-up, before the agent connected).
    """
    rate = gpu_rate if gpu_rate is not None else DEFAULT_GPU_RATE_USD_PER_HR

    try:
        plan = plan_generation_sync(
            batch, section_id=section_id, all_sections=all_sections, gpu_rate=rate
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    if not plan.plans:
        click.echo("Nothing to generate.", err=True)
        for sid in plan.skipped:
            click.echo(plan.skip_reason(sid), err=True)
        raise SystemExit(1)

    ledger = GpuLedger()
    remaining = ledger.remaining()
    est = plan.estimated_session_cost_usd

    # ── Soft-inform GPU gate ────────────────────────────────────────────────
    click.echo("── GPU cost gate (soft-inform — advises, never blocks) ──")
    click.echo(f"  Specs to generate:  {len(plan.plans)}")
    click.echo(f"  Per-run estimate:   ${plan.per_run_estimate_usd:.4f}  ({plan.estimate_source})")
    click.echo(f"  GPU rate:           ${rate:.2f}/hr (user-supplied)")
    click.echo(f"  Est. session cost:  ${est:.4f}  (≈ uptime proxy; real billing began at spin-up)")
    click.echo(f"  Local cumulative:   ${ledger.cumulative():.4f}")
    if remaining is not None:
        click.echo(f"  Declared budget:    ${remaining:.4f} remaining after this gate")
    if plan.skipped:
        click.echo("  Skipped:")
        for sid in plan.skipped:
            click.echo(f"      • {plan.skip_reason(sid)}")
    plan_warnings = [w for sp in plan.plans for w in sp.warnings]
    if plan_warnings:
        click.echo("  ⚠ Refinement advisories:")
        for w in plan_warnings:
            click.echo(f"      • {w}")
    for sp in plan.plans:
        _echo_lora_strength_warnings(sp.spec.lora_stack, indent="  ")
        _echo_unmapped_warning(sp.unmapped, sp.template.name, label=sp.spec.spec_id, indent="  ")
        if sp.neutralized_loras:
            click.echo(
                f"  ℹ {sp.spec.spec_id}: switched off template-baked LoRA(s) the spec did not ask "
                f"for: {', '.join(sp.neutralized_loras)}"
            )
    if max_session_cost is not None:
        click.echo(f"  Hard ceiling:       ${max_session_cost:.2f} (--max-session-cost)")
        if est > max_session_cost:
            click.echo("  ⚠ estimate exceeds the ceiling — the run will stop early.")

    if not yes:
        click.confirm(f"Spend ~${est:.4f} of GPU time on {len(plan.plans)} generation(s)?", abort=True)

    result = spend_generation_sync(
        plan, endpoint=endpoint, gpu_rate=rate, max_session_cost=max_session_cost
    )

    click.echo(f"\nStatus:       {result.status}")
    click.echo(f"Generated:    {result.items_processed} spec(s)")
    click.echo(f"Session cost: ${result.session_cost_usd:.4f}  (GPU, agent-local)")
    for r in result.results:
        # Full gen id in the header — it's what `report` needs (exact point-id lookup) and
        # equals the asset filename stem. Never truncate it here: a clipped id looks
        # copy-pasteable but Qdrant rejects it as an invalid point id. Spec id goes on its
        # own line below (you don't report a spec).
        click.echo(f"\n── Generation {r.generation_id} ──")
        click.echo(f"Spec:     {r.spec_id}")
        click.echo(f"Asset:    {r.asset_path}" + ("  [identity-bearing → secured path]" if r.identity_bearing else ""))
        click.echo(f"GPU cost: ${r.gpu_cost_usd:.4f}  (running ${r.session_cost_running_usd:.4f})")
        if r.rationale:
            click.echo(f"Recipe:   {r.rationale}")
        click.echo(f"React:    agent visual-generation report {r.generation_id} "
                   f"--reaction <{'|'.join(REACTIONS)}>")
    if result.skip_reasons:
        click.echo("\nSkipped:")
        for reason in result.skip_reasons:
            click.echo(f"  • {reason}")
    elif result.skipped:
        click.echo(f"\nSkipped: {', '.join(result.skipped)}")

    # ── Drain → stop-prompt + idle warning (Q4: advisory; no RunPod stop) ───
    if result.drained:
        click.echo("\n── Batch drained ───────────────────────────────────")
        click.echo("Stop your pod now to stop GPU billing — the agent issues no RunPod stop.")
        click.echo("⚠ Idle warning: every minute the pod stays up keeps billing, even idle.")

    click.echo("\nReview each asset, then run its `React:` command above (the gen id is filled in).")
    if result.report_path:
        click.echo(f"\nReport: {result.report_path}")


# ── report (React) ───────────────────────────────────────────────────────────


@cli.command()
@click.argument("gen_id")
@click.option("--reaction", required=True, type=click.Choice(REACTIONS),
              help="Reaction to the generation. 'disliked' = rendered faithfully but not to "
                   "taste (aesthetic — weighs against the settings); 'render_failed' = the "
                   "intent didn't render (artifacts/ignored prompt — the direction stays open).")
@click.option("--rating", type=click.IntRange(1, 5), default=None,
              help="Optional 1-5 intensity. Meaningful for positive reactions.")
@click.option("--notes", default=None, help="Action-oriented: what to change next time.")
@click.option("--context", default=None,
              help="Reasoning-oriented: why you reacted this way (retrievable signal).")
def report(gen_id: str, reaction: str, rating: int | None,
           notes: str | None, context: str | None) -> None:
    """Record your reaction to a generation, flipping it pending -> complete."""
    if rating is not None and reaction not in POSITIVE_REACTIONS:
        click.echo(
            f"Warning: --rating is unusual for '{reaction}' (ratings are meaningful for "
            "positive reactions). Recording it anyway.",
            err=True,
        )
    gen = report_sync(gen_id, reaction, rating=rating, notes=notes, context=context)
    if gen is None:
        click.echo(
            f"Error: no generation with id '{gen_id}'.\n"
            "  • `report` needs a GENERATION id — from `generate`'s `Gen id:` / `React:` line.\n"
            "  • A SPEC id (from `draft` or `batch list`) is a different id; you can't report a\n"
            "    spec that hasn't been rendered yet — run `generate` first.\n"
            "  • To see rendered generations + their ready report commands:\n"
            "      agent visual-generation review-pending",
            err=True,
        )
        raise SystemExit(1)
    rating_str = f" ★{rating}" if rating is not None else ""
    click.echo(f"Recorded: {gen_id} → {reaction}{rating_str}")


# ── quick (one-off generation — no batch file, no canon, no memory write) ────


@cli.command()
@click.argument("prompt")
@click.option("--endpoint", required=True, help="ComfyUI endpoint URL (the pod you spun up).")
@click.option("--video", is_flag=True, default=False,
              help="Generate a WAN 2.2 video clip instead of a still image.")
@click.option("--image", "image_path", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Seed image for image-to-video (WAN I2V). Requires --video.")
@click.option("--template", "template_name", default=None,
              help="Registered workflow template name (default: picked from --video/--image).")
@click.option("--negative-prompt", default=None)
@click.option("--seed", type=int, default=None, help="Fixed seed; default random.")
@click.option("--width", type=int, default=None)
@click.option("--height", type=int, default=None)
@click.option("--length", type=int, default=None, help="Video frame count (must be 4n+1). Video only.")
@click.option("--fps", type=int, default=None, help="Video playback rate. Video only.")
@click.option("--model", "model_name", default=None, help="Checkpoint/unet override. Stills only.")
@click.option("--steps", type=int, default=None, help="Stills only — WAN's recipe is locked.")
@click.option("--cfg", type=float, default=None, help="Stills only — WAN's recipe is locked.")
@click.option("--sampler", default=None, help="Stills only — WAN's recipe is locked.")
@click.option("--scheduler", default=None, help="Stills only — WAN's recipe is locked.")
@click.option("--lora", "loras", multiple=True, help="NAME[:STRENGTH], repeatable. Stills only.")
@click.option("--out", "out_path", type=click.Path(), default=None,
              help="Save here instead of the default adhoc assets folder.")
@click.option("--gpu-rate", type=float, default=None,
              help=f"GPU $/hr for the printed cost estimate (default: {DEFAULT_GPU_RATE_USD_PER_HR}).")
@click.option("--timeout", "poll_timeout", type=float, default=None,
              help="Seconds to wait for the render (default: longer for --video — cold model loads are slow).")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip the spend confirmation.")
def quick(
    prompt: str,
    endpoint: str,
    video: bool,
    image_path: str | None,
    template_name: str | None,
    negative_prompt: str | None,
    seed: int | None,
    width: int | None,
    height: int | None,
    length: int | None,
    fps: int | None,
    model_name: str | None,
    steps: int | None,
    cfg: float | None,
    sampler: str | None,
    scheduler: str | None,
    loras: tuple[str, ...],
    out_path: str | None,
    gpu_rate: float | None,
    poll_timeout: float | None,
    yes: bool,
) -> None:
    """One-off generation straight from PROMPT to a registered ComfyUI workflow.

    Skips drafting, canon, batch files, and generation memory — nothing about this
    render is recorded to Qdrant. The only Qdrant touch is a read-only lookup of the
    registered workflow template. For production/character-locked shots, or per-run
    control over WAN's settings, use `draft`/`generate` instead.
    """
    if image_path and not video:
        raise click.UsageError("--image requires --video (WAN image-to-video).")

    still_only = {"--model": model_name, "--steps": steps, "--cfg": cfg,
                  "--sampler": sampler, "--scheduler": scheduler}
    used_still_only = [name for name, val in still_only.items() if val is not None]
    if video and used_still_only:
        raise click.UsageError(
            f"{', '.join(used_still_only)} not supported with --video — WAN's recipe is "
            "locked to the proven 4-step lightx2v settings (see the package README)."
        )

    lora_stack = [_parse_lora(tok) for tok in loras]
    if video and lora_stack:
        raise click.UsageError(
            "--lora not supported with --video — WAN's LoRA stack is baked into the template."
        )
    _echo_lora_strength_warnings(lora_stack)

    settings: dict[str, Any] = {}
    if steps is not None:
        settings["steps"] = steps
    if cfg is not None:
        settings["cfg"] = cfg
    if sampler is not None:
        settings["sampler"] = sampler
    if scheduler is not None:
        settings["scheduler"] = scheduler

    rate = gpu_rate if gpu_rate is not None else DEFAULT_GPU_RATE_USD_PER_HR
    timeout = poll_timeout if poll_timeout is not None else (1200.0 if video else DEFAULT_POLL_TIMEOUT_SEC)

    kind = "video" if video else "image"
    click.echo(f"── Quick {kind} generation ── (no batch file, no canon, no memory write)")
    click.echo(f"  Endpoint: {endpoint}")
    if video:
        click.echo("  ⚠ Video renders take a few minutes and cost noticeably more GPU time than a still.")
    if not yes:
        click.confirm(f"Submit 1 {kind} generation to this endpoint?", abort=True)

    try:
        result = quick_generate_sync(
            prompt,
            endpoint=endpoint,
            video=video,
            template_name=template_name,
            negative_prompt=negative_prompt,
            seed=seed,
            width=width,
            height=height,
            length=length,
            fps=fps,
            image_path=image_path,
            model=model_name,
            settings=settings,
            lora_stack=lora_stack,
            out_path=out_path,
            gpu_rate=rate,
            poll_timeout=timeout,
        )
    except (QuickTemplateNotFound, QuickSourceError, QuickSeedUnmapped, QuickLoraUnsafe, QuickInvalidSpec) as exc:
        raise click.ClickException(str(exc)) from exc
    except ComfyUIError as exc:
        raise click.ClickException(str(exc)) from exc

    # quick resolves the template inside the library call, so this lands after the
    # render (no pre-spend gate exists here); a missing seed slot already raised above.
    _echo_unmapped_warning(result.unmapped, result.template_name)
    click.echo(f"\nSaved:     {result.asset_path}")
    click.echo(f"Template:  {result.template_name}")
    click.echo(f"Seed:      {result.seed}")
    click.echo(f"Elapsed:   {result.elapsed_sec:.1f}s  (≈${result.estimated_cost_usd:.4f} at ${rate:.2f}/hr)")
    click.echo("\nNot recorded to visual_generation_memory — quick generations are memory-free.")


# ── chat (conversational front end; needs the optional `chat` extra) ───────────


_CHAT_LIBS = {"agent_shell", "langgraph", "langchain_core", "langchain_anthropic",
              "langchain_openai", "prompt_toolkit", "rich"}


@cli.command("chat")
@click.option("--provider", type=click.Choice(["claude", "openai"]), default="claude",
              show_default=True, help="Which model runs the conversation.")
@click.option("--model", default=None,
              help="Model id (must have a price row). Required for openai.")
@click.option("--project", default=None,
              help="Active project slug (lowercase-kebab). Needed to draft; drafts go to "
                   "<projects>/<slug>/visual-batch.md.")
@click.option("--resume", "resume_id", default=None, help="Resume a chat session id.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Spend tools describe what they would do and run nothing.")
def chat(provider: str, model: str | None, project: str | None, resume_id: str | None,
         dry_run: bool) -> None:
    """Chat with the agent: look things up, craft and revise specs, interpret feedback.

    Read and craft only: no GPU spend and no memory writes. Run under op run:
    `agent visual-generation chat --project <slug>`."""
    try:
        from visual_generation.chat.cli import run_chat
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in _CHAT_LIBS:
            raise
        raise click.ClickException(
            f"chat needs its optional libraries ({exc.name} is missing). "
            "Install them with: uv sync --all-packages --extra chat   (visual-generation[chat])"
        ) from exc
    run_chat(provider, model, project, resume_id, dry_run)


def chat_entry() -> None:
    """The `visual-agent` console script: the same command as `visual-generation chat`."""
    cli(["chat", *sys.argv[1:]])


# ── gate0 (read-only check of a finished Gate 0 run) ───────────────────────────


@cli.group()
def gate0() -> None:
    """Gate 0 (execution truth): verify a finished run. Reads only; spends nothing."""


@gate0.command("verify")
@click.option("--project", default="gate0", show_default=True, help="Project the Gate 0 run used.")
@click.option("--template", "template_name", required=True,
              help="Registered workflow template the run used (also used for the refusal check).")
@click.option("--fixed-seed", type=int, default=12345, show_default=True,
              help="The seed the fixed-seed spec asked for.")
@click.option("--out", "out_path", type=click.Path(dir_okay=False), default=None,
              help="Write the result record (markdown) to this path.")
def gate0_verify(project: str, template_name: str, fixed_seed: int, out_path: str | None) -> None:
    """Check seed truth, random-seed variety, fixed-seed honoring, replay inputs and refusal."""
    from visual_generation.gate0 import render_record, verify_gate0

    async def _run():  # type: ignore[no-untyped-def]
        store, _ = _get_stores()
        return await verify_gate0(project, store=store, template_name=template_name, fixed_seed=fixed_seed)

    report = asyncio.run(_run())
    click.echo(f"Gate 0 for project {project!r}: {len(report.generations)} generation(s)\n")
    for c in report.checks:
        click.echo(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    click.echo(f"\nGate 0 result: {'PASS' if report.passed else 'FAIL'}")
    if out_path:
        Path(out_path).write_text(render_record(report), encoding="utf-8")
        click.echo(f"Record written to {out_path}")
    if not report.passed:
        raise SystemExit(1)


# ── Inspect (review-pending / chain show / recall) — pure reads ───────────────


@cli.command("knowledge-verify")
@click.argument("query")
@click.option("--project", default=None, help="Optional project label (for context).")
@click.option("--limit", default=8, show_default=True, help="Max hits per leg.")
def knowledge_verify(query: str, project: str | None, limit: int) -> None:
    """Prove what the knowledge legs surface for QUERY, and flag gaps. Read-only, no GPU.

    Run this to verify ingested research is actually reachable (e.g. before vs. after
    ingesting z-image canon), and to catch silent gaps — a leg returning nothing, or a
    collection that holds content but surfaced none of it.
    """
    from visual_generation.verify import verify_knowledge

    async def _run() -> None:
        store, ms = _get_stores()
        report = await verify_knowledge(query, store, ms, project=project, limit=limit)
        click.echo(render_verify(report))

    asyncio.run(_run())


@cli.command()
@click.argument("project")
@click.option("--limit", default=8, show_default=True, help="Max recent generations to show.")
def digest(project: str, limit: int) -> None:
    """Session-primer for PROJECT: recent generations + reactions, lessons, pending. Read-only.

    Bounded and on-demand (no context bloat) — the 'where did I leave off?' view so a new
    Claude Code session doesn't start cold. This is the retention loop: draft → generate →
    `report` → memory → digest/recall. Run `report` after each render so this stays useful.
    """

    async def _run() -> None:
        store, _ = _get_stores()
        click.echo(render_digest(await build_digest(project, store, limit=limit)))

    asyncio.run(_run())


@cli.command("review-pending")
def review_pending() -> None:
    """List generations awaiting a reaction (rendered, not yet reacted to)."""
    click.echo(render_pending(list_pending_sync()))


@cli.group()
def chain() -> None:
    """Inspect generation lineage chains."""


@chain.command("show")
@click.argument("root_id")
def chain_show(root_id: str) -> None:
    """Render the lineage chain rooted at ROOT_ID (root → children tree)."""
    click.echo(render_chain(root_id, get_chain_sync(root_id)))


@cli.command()
@click.argument("query")
@click.option("--limit", default=5, show_default=True, help="Max results per kind.")
def recall(query: str, limit: int) -> None:
    """Search YOUR OWN memory — generations, technique lessons, templates. Hits, not answers."""
    gens, lessons, templates = recall_sync(query, limit=limit)
    click.echo(render_recall(gens, lessons, templates))


# ── batch (prune specs in a batch.md) ─────────────────────────────────────────


@cli.group()
def batch() -> None:
    """Compile a whole project into a batch, and inspect/prune its specs."""


_ANCHOR_OPTIONS = [
    click.option("--from", "from_generation", default=None,
                 help="Anchor every scene to a prior generation (img2img) for character "
                      "continuity. Mutually exclusive with --image."),
    click.option("--image", "image_path", type=click.Path(dir_okay=False), default=None,
                 help="Anchor every scene to an external image on disk. Mutually exclusive with --from."),
    click.option("--denoise", type=float, default=None,
                 help="Refinement denoise for the anchor (default 0.5; coherent ~0.4–0.7; "
                      "higher = re-stage more / carry the anchor less)."),
    click.option("--template", "template_name", default=None,
                 help=f"Workflow template (default {IMG2IMG_TEMPLATE_NAME!r} when anchored)."),
]


def _with_anchor_options(fn):  # type: ignore[no-untyped-def]
    for opt in reversed(_ANCHOR_OPTIONS):
        fn = opt(fn)
    return fn


@batch.command("build")
@click.argument("project")
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Batch file to write (default: <project>.batch.md under agent-data).")
@click.option("--model", "model", default=None,
              help="Model alias (sonnet|opus) or a concrete id; the provider resolves it.")
@click.option("--provider", "provider", default=None,
              help="LLM provider for the craft (anthropic|openai; default: config).")
@_with_anchor_options
def batch_build(project: str, output: str | None, model: str | None, provider: str | None,
                from_generation: str | None, image_path: str | None,
                denoise: float | None, template_name: str | None) -> None:
    """Compile one spec per scene of PROJECT's directed.md into a batch file. Free.

    Reads the project's narrative doc (directed.md, else script.md) and, for each `##`
    scene, compiles the project's docs + retrieved knowledge into a prompt (canon
    enforced). Refuses to overwrite an existing batch — use `batch rebuild` for that.
    You feed nothing but the project slug.

    For cross-scene CHARACTER CONTINUITY, anchor with --from <gen_id> (or --image <path>):
    every scene is then composed as an img2img refinement from that one frame, so the
    narrator carries across scenes instead of being re-rolled per scene.
    """
    source, template_name = _resolve_anchor(from_generation, image_path, template_name)
    _run_batch(project, output, model, provider, overwrite=False,
               source=source, denoise=denoise, template_name=template_name)


@batch.command("rebuild")
@click.argument("project")
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Batch file to re-create (default: <project>.batch.md under agent-data).")
@click.option("--model", "model", default=None,
              help="Model alias (sonnet|opus) or a concrete id; the provider resolves it.")
@click.option("--provider", "provider", default=None,
              help="LLM provider for the craft (anthropic|openai; default: config).")
@_with_anchor_options
def batch_rebuild(project: str, output: str | None, model: str | None, provider: str | None,
                  from_generation: str | None, image_path: str | None,
                  denoise: float | None, template_name: str | None) -> None:
    """Re-create PROJECT's batch from scratch (overwrites the existing batch file). Free.

    Accepts the same --from/--image/--denoise anchor options as `batch build` for
    cross-scene character continuity."""
    source, template_name = _resolve_anchor(from_generation, image_path, template_name)
    _run_batch(project, output, model, provider, overwrite=True,
               source=source, denoise=denoise, template_name=template_name)


def _resolve_batch_path(batch_file: str | None, project: str | None) -> Path:
    """Locate the batch file from an explicit path OR a --project slug (the default
    `<project>.batch.md`, same as draft/generate), so you can manage a batch by the same
    slug you drafted it with instead of typing the full path."""
    from visual_generation.draft import _default_batch_path

    if batch_file:
        path = Path(batch_file)
    elif project:
        path = _default_batch_path(project)
    else:
        raise click.UsageError("Give a BATCH_FILE path or --project <slug>.")
    if not path.is_file():
        hint = "Check the path." if batch_file else f"Has '{project}' been drafted yet?"
        raise click.UsageError(f"No batch file at {path}. {hint}")
    return path


@batch.command("list")
@click.argument("batch_file", required=False, type=click.Path(dir_okay=False))
@click.option("--project", "-p", default=None,
              help="Resolve the default <project>.batch.md instead of passing a path.")
def batch_list(batch_file: str | None, project: str | None) -> None:
    """List the specs in a batch (spec_id, section title, workflow_ref).

    Target it by BATCH_FILE path or by --project <slug> (the same default batch file
    draft/generate use)."""
    parsed = read_batch(_resolve_batch_path(batch_file, project))
    if not parsed.specs:
        click.echo("No specs in this batch file.")
        return
    click.echo(f"{len(parsed.specs)} spec(s):\n")
    for s in parsed.specs:
        title = s.heading or (s.prompt[:60] if s.prompt else "(untitled)")
        click.echo(f"  {s.spec_id}  [{s.workflow_ref or 'no template'}]  {title}")


@batch.command("rm")
@click.argument("spec_id")
@click.argument("batch_file", required=False, type=click.Path(dir_okay=False))
@click.option("--project", "-p", default=None,
              help="Resolve the default <project>.batch.md instead of passing a path.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Delete without the confirmation prompt.")
def batch_rm(spec_id: str, batch_file: str | None, project: str | None, yes: bool) -> None:
    """Remove the spec with SPEC_ID from a batch (other specs are untouched).

    Target the batch by --project <slug> (recommended) or a trailing BATCH_FILE path:

        agent visual-generation batch rm <spec_id> --project celeste-you-dangerous
    """
    path = _resolve_batch_path(batch_file, project)
    try:
        _, target = find_batch_spec(path, spec_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if not yes:
        title = target.heading or (target.prompt[:60] if target.prompt else spec_id)
        click.confirm(f"Remove spec {spec_id} ({title})?", abort=True)
    _, remaining = remove_batch_spec(path, spec_id)
    click.echo(f"Removed spec {spec_id}. {remaining} spec(s) remain.")


# ── Project canon (deterministic, file-backed) ───────────────────────────────


def _parse_lora(spec: str) -> LoraRef:
    """Parse a NAME[:STRENGTH] CLI token into a LoraRef (strength defaults to 1.0)."""
    try:
        return parse_lora(spec)
    except ValueError as exc:
        raise click.BadParameter(
            str(exc).replace("a lora needs", "--lora needs").replace("lora strength", "--lora strength")
        ) from exc


@cli.group()
def canon() -> None:
    """Manage a project's canon subjects (asset references + pinned character LoRAs;
    LoRAs are pinned deterministically at draft/redraft)."""


@canon.command("set")
@click.argument("project")
@click.option("--alias", "aliases", multiple=True, required=True,
              help="A name the subject is called by (repeatable). aliases[0] is the key.")
@click.option("--id", "subject_id", default=None,
              help="Versioned asset id for the subject (e.g. celeste_v1) — aligns with "
                   "docs/shared-shot-schema.md.")
@click.option("--reference-pack", "reference_pack", default=None,
              help="Versioned reference bundle id (e.g. celeste_refs_v1).")
@click.option("--wardrobe", "wardrobe", default=None,
              help="Versioned wardrobe asset id (e.g. black_bar_uniform_v1).")
@click.option("--hair", "hair", default=None,
              help="Versioned hair asset id (e.g. bun_front_curl_v1).")
@click.option("--region", "region", default=None,
              help="Named region mask for this subject (e.g. celeste_mask).")
@click.option("--lora", "lora", default=None,
              help="Character LoRA pinned whenever this subject appears, as "
                   "NAME[:STRENGTH] (strength defaults to 1.0). The NAME must key into "
                   "the model registry; flag it identity_bearing there.")
def canon_set(
    project: str, aliases: tuple[str, ...], subject_id: str | None,
    reference_pack: str | None, wardrobe: str | None, hair: str | None,
    region: str | None, lora: str | None,
) -> None:
    """Upsert a canon subject for PROJECT (keyed by its first alias).

    REPLACES the whole subject — legacy locked/forbid fields on a replaced subject
    are dropped. Use `canon edit` for surgical changes that preserve them."""
    lora_ref = _parse_lora(lora) if lora else None
    store = ProjectCanon(project)
    change = set_canon_subject(
        project, list(aliases), lora=lora_ref, id=subject_id, reference_pack=reference_pack,
        wardrobe=wardrobe, hair=hair, region=region, canon=store,
    )
    subject = change.after
    assert subject is not None
    verb = "replaced" if change.existed else "set"
    click.echo(f"Canon {verb} for {project!r} (subject '{subject.aliases[0]}'):")
    _echo_subject(subject, indent="  ")
    if change.existed:
        click.echo(
            "\nNote: `canon set` REPLACES the whole subject (legacy locked/forbid are "
            "dropped). To change just one field without restating the rest, use `canon edit`."
        )
    click.echo(f"\nStored at: {store.path}")


def selector_matches(subject: object, alias: str) -> bool:
    return alias.lower() in [a.lower() for a in subject.aliases]  # type: ignore[attr-defined]


def _echo_subject(s: object, *, indent: str = "  ") -> None:
    """Print one canon subject's fields (shared by set/edit/show)."""
    for line in render_subject(s, indent=indent):
        click.echo(line)


@canon.command("show")
@click.argument("project")
def canon_show(project: str) -> None:
    """Show PROJECT's canon subjects."""
    click.echo(render_canon(show_canon(project, ProjectCanon(project))))


@canon.command("edit")
@click.argument("project")
@click.argument("subject")
@click.option("--add-alias", "add_alias", multiple=True, help="Add an alias (repeatable).")
@click.option("--rm-alias", "rm_alias", multiple=True, help="Remove an alias (repeatable).")
@click.option("--id", "subject_id", default=None,
              help="Set the versioned asset id (pass an empty string to clear).")
@click.option("--reference-pack", "reference_pack", default=None,
              help="Set the reference bundle id (empty string clears).")
@click.option("--wardrobe", "wardrobe", default=None,
              help="Set the wardrobe asset id (empty string clears).")
@click.option("--hair", "hair", default=None,
              help="Set the hair asset id (empty string clears).")
@click.option("--region", "region", default=None,
              help="Set the region mask name (empty string clears).")
@click.option("--lora", "lora", default=None,
              help="Set/replace the pinned character LoRA as NAME[:STRENGTH] (registry name).")
@click.option("--clear-lora", "clear_lora", is_flag=True, default=False,
              help="Remove the pinned character LoRA.")
def canon_edit(
    project: str, subject: str,
    add_alias: tuple[str, ...], rm_alias: tuple[str, ...],
    subject_id: str | None, reference_pack: str | None, wardrobe: str | None,
    hair: str | None, region: str | None,
    lora: str | None, clear_lora: bool,
) -> None:
    """Edit ONE subject of PROJECT's canon in place, selected by SUBJECT (any of its aliases).

    Surgical alternative to `canon set` (which replaces the whole subject): change just
    an alias, an asset reference, or the pinned LoRA without restating the rest. Legacy
    locked/forbid fields on the stored subject are preserved untouched.

        canon edit celeste-you-dangerous "the narrator" \\
          --id narrator_v1 --reference-pack narrator_refs_v1
    """
    edit = CanonEdit(
        add_aliases=list(add_alias), remove_aliases=list(rm_alias),
        lora=_parse_lora(lora) if lora else None, clear_lora=clear_lora, id=subject_id,
        reference_pack=reference_pack, wardrobe=wardrobe, hair=hair, region=region,
    )
    if edit.is_empty():
        raise click.UsageError(
            "Nothing to edit. Pass at least one of --add-alias / --rm-alias / --id / "
            "--reference-pack / --wardrobe / --hair / --region / --lora / --clear-lora."
        )
    if lora and clear_lora:
        raise click.UsageError("Pass either --lora or --clear-lora, not both.")
    store = ProjectCanon(project)
    before = find_canon_subject(project, subject, store)
    if before is not None:
        click.echo("Before:")
        _echo_subject(before, indent="  ")
    try:
        updated = edit_canon_subject(project, subject, edit, canon=store).after
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("\nAfter:")
    _echo_subject(updated, indent="  ")
    click.echo(f"\nStored at: {store.path}")


@canon.command("rm")
@click.argument("project")
@click.argument("alias")
def canon_rm(project: str, alias: str) -> None:
    """Remove the canon subject that any of whose aliases match ALIAS."""
    if remove_canon_subject(project, alias) is not None:
        click.echo(f"Removed canon subject matching {alias!r} from {project!r}.")
    else:
        click.echo(f"No canon subject matching {alias!r} in {project!r}.", err=True)
        raise SystemExit(1)


# ── Direct writes (lesson add / fact add) ─────────────────────────────────────


@cli.group()
def lesson() -> None:
    """Manage technique lessons (learned-by-doing)."""


@lesson.command("add")
@click.argument("statement")
@click.option("--scope", type=click.Choice(
    [LESSON_SCOPE_PROMPT, LESSON_SCOPE_SETTINGS, LESSON_SCOPE_WORKFLOW, LESSON_SCOPE_MODEL]),
    default=LESSON_SCOPE_SETTINGS, show_default=True)
@click.option("--valence", type=click.Choice(["positive", "negative"]), default="positive",
              show_default=True)
def lesson_add(statement: str, scope: str, valence: str) -> None:
    """Add a CONFIRMED technique lesson (running the command is the confirmation)."""

    async def _run() -> None:
        store, _ = _get_stores()
        await add_lesson(statement, scope, valence, store=store)
        click.echo(f"Added technique lesson [{valence}/{scope}]: {statement[:60]}")

    asyncio.run(_run())


@lesson.command("list")
@click.option("--include-unconfirmed", is_flag=True, default=False,
              help="Also list unconfirmed lessons (confirmed-only by default).")
@click.option("--scope", type=click.Choice(
    [LESSON_SCOPE_PROMPT, LESSON_SCOPE_SETTINGS, LESSON_SCOPE_WORKFLOW, LESSON_SCOPE_MODEL]),
    default=None, help="Filter by scope.")
@click.option("--valence", type=click.Choice(["positive", "negative"]), default=None,
              help="Filter by valence.")
def lesson_list(include_unconfirmed: bool, scope: str | None, valence: str | None) -> None:
    """List technique lessons with their entry_ids (target one with `lesson rm`)."""

    async def _run() -> None:
        store, _ = _get_stores()
        lessons = await list_lessons(
            store, include_unconfirmed=include_unconfirmed, scope=scope, valence=valence)
        click.echo(render_lessons(lessons))

    asyncio.run(_run())


@lesson.command("rm")
@click.argument("entry_id")
@click.option("--yes", is_flag=True, default=False,
              help="Delete without the confirmation prompt.")
def lesson_rm(entry_id: str, yes: bool) -> None:
    """Delete the technique lesson with ENTRY_ID (refuses non-lesson ids)."""

    async def _run() -> None:
        store, _ = _get_stores()
        try:
            le = await lookup_lesson(entry_id, store)
        except ValueError as exc:
            raise click.ClickException(
                f"Entry {entry_id} is a {exc}, not a technique_lesson; refusing to delete.")
        except LookupError as exc:
            raise click.ClickException(str(exc))
        if not yes:
            click.confirm(
                f"Remove [{le.valence}/{le.scope}] {le.statement[:60]}?", abort=True)
        await remove_lesson(entry_id, store, lesson=le)
        click.echo(f"Removed technique lesson {entry_id}: {le.statement[:60]}")

    asyncio.run(_run())


@cli.group()
def fact() -> None:
    """Manage documented platform/vendor facts in user_knowledge (vs. learned-by-doing lessons)."""


@fact.command("add")
@click.argument("statement")
@click.option("--domain", type=click.Choice(MECHANICS_DOMAINS), required=True,
              help="comfyui_mechanics (backend) or runpod_mechanics (platform).")
@click.option("--confidence", type=click.Choice(["high", "medium", "low"]), default="high",
              show_default=True)
def fact_add(statement: str, domain: str, confidence: str) -> None:
    """Add a documented platform fact directly to user_knowledge."""
    from agent_runtime import UserKnowledgeStore, get_memory_store

    async def _run() -> None:
        uks = UserKnowledgeStore(get_memory_store())
        entry_id = await add_fact(statement, domain, uks=uks, confidence=confidence)
        click.echo(f"Added fact to {domain}: {statement[:60]}")
        click.echo(f"Entry ID: {entry_id}")

    asyncio.run(_run())


@fact.command("ingest-docs")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--domain", type=click.Choice(MECHANICS_DOMAINS), required=True,
              help="comfyui_mechanics (backend) or runpod_mechanics (platform).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Parse and show candidate counts without writing.")
@click.option("--yes", is_flag=True, default=False,
              help="Confirm and write every candidate without prompting.")
def fact_ingest_docs(folder: str, domain: str, dry_run: bool, yes: bool) -> None:
    """Parse local ComfyUI/RunPod docs in FOLDER into verified user_knowledge (y/n/edit/defer)."""
    from agent_runtime import ingest_docs_sync

    ingest_docs_sync(folder, domain=domain, dry_run=dry_run, auto_confirm=yes)


# ── Tutor (explain / research) ────────────────────────────────────────────────


@cli.command()
@click.argument("concept")
@click.option("--level", type=click.Choice(EXPLAIN_LEVELS), default=None,
              help="Verbosity dial (default: config / concise). Only changes generic gloss "
                   "volume — your own technique lessons are always surfaced.")
def explain(concept: str, level: str | None) -> None:
    """Grounded tutor deep-dive on CONCEPT (Claude — no GPU)."""
    click.echo(render_explain(explain_sync(concept, level=level)))


@cli.command()
@click.argument("topic")
@click.option("--dry-run", "dry_run", is_flag=True, default=False,
              help="Plan only: score and rank candidate videos without ingesting "
                   "(low-but-nonzero cost — a scoring Claude call still runs).")
def research(topic: str, dry_run: bool) -> None:
    """Delegate TOPIC to tutorial-research (Claude — no GPU). Two-step: retrieved cheaply after.

    With --dry-run, preview the ranked candidates that WOULD be ingested without paying
    for the full ingest (Whisper + Claude chain). Nothing is written.
    """
    click.echo(render_research(research_sync(topic, dry_run=dry_run)))
