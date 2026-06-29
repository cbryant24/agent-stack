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
import json
from pathlib import Path

import click

from visual_generation.agent import _get_stores
from visual_generation.batch_file import read_batch, remove_spec, write_batch
from visual_generation.comfyui_client import ComfyUIClient, ComfyUIError
from visual_generation.constants import (
    DEFAULT_GPU_RATE_USD_PER_HR,
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
from visual_generation.draft import batch_project_sync, draft_sync, redraft_sync
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
from visual_generation.model_registry import ModelRegistry
from visual_generation.model_sync import parse_object_info, reconcile
from visual_generation.models import LoraRef, TechniqueLesson, VisualSource, WorkflowTemplate
from visual_generation.report import report_sync
from visual_generation.research import register_delegate_handlers, render_research, research_sync
from visual_generation.slot_inference import infer_slots


@click.group()
def cli() -> None:
    """Visual generation agent — ComfyUI backend + workflow templates."""
    # Register the delegate handlers this process uses (idempotent). Done at the
    # group callback so `research` can delegate to tutorial-research for real.
    register_delegate_handlers()


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
    registry = ModelRegistry()
    assets = registry.list_models()
    if not assets:
        click.echo("No models registered. Run: agent visual-generation model sync --endpoint <url>")
        return
    click.echo(f"{len(assets)} registered asset(s):\n")
    for a in sorted(assets, key=lambda x: (x.kind, x.name)):
        flags = []
        if a.identity_bearing:
            flags.append("identity-bearing")
        if not a.present_on_endpoint:
            flags.append("absent-from-last-sync")
        flag_str = f"  ({', '.join(flags)})" if flags else ""
        click.echo(f"  [{a.kind:10}] {a.name}  <{a.source}>{flag_str}")


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
        graph = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Not valid JSON: {exc}") from exc
    if not isinstance(graph, dict) or not graph:
        raise click.ClickException(
            "Expected an API-format graph (node_id → {class_type, inputs}). "
            "Export with ComfyUI's 'Export Workflow (API)'."
        )

    name = name or path.stem
    inferred = infer_slots(graph)
    slot_map = dict(inferred.slot_map)

    # ── Propose ──────────────────────────────────────────────────────────────
    click.echo(f"── Inferred slots for '{name}' ──────────────────────")
    if slot_map:
        for slot, target in slot_map.items():
            click.echo(f"  {slot:14} → node {target['node_id']}.{target['input_key']}")
    else:
        click.echo("  (none inferred)")
    if inferred.notes:
        click.echo("\nNotes:")
        for note in inferred.notes:
            click.echo(f"  • {note}")

    # ── Confirm / correct ────────────────────────────────────────────────────
    if not yes:
        # The one genuinely ambiguous slot the heuristic can offer to correct:
        # a suppressed negative whose placeholder node we actually know.
        if inferred.negative_suppressed and inferred.negative_candidate is not None:
            if click.confirm(
                "Negative prompt was suppressed. Add a negative slot at the traced node?",
                default=False,
            ):
                slot_map["negative"] = inferred.negative_candidate
        if not click.confirm("Accept this slot map?", default=True):
            raise click.ClickException("Aborted — re-export or edit the graph and retry.")

    # ── Required-model advisory (never blocks) ───────────────────────────────
    registry = ModelRegistry()
    known = {a.name for a in registry.list_models()}
    missing = [m for m in inferred.required_models if m not in known]
    if inferred.required_models:
        click.echo(f"\nRequired models: {', '.join(inferred.required_models)}")
    if missing:
        click.echo(
            f"  ⚠ Not in registry (run `model sync` against a pod that has them): "
            f"{', '.join(missing)}"
        )

    if descriptor is None:
        descriptor = click.prompt("Descriptor (what this template serves)", default=name)

    template = WorkflowTemplate(
        name=name,
        descriptor=descriptor,
        graph=graph,
        slot_map=slot_map,
        required_models=inferred.required_models,
    )

    async def _store() -> str:
        store, _ = _get_stores()
        await store.ensure_collection()
        await store.upsert_template(template)
        return template.entry_id

    entry_id = asyncio.run(_store())
    click.echo(f"\nRegistered template '{name}' ({entry_id[:12]}) with {len(slot_map)} slot(s).")


@workflow.command("list")
@click.option("--query", default="", help="Optional semantic query (default: list recent).")
@click.option("--limit", default=20, show_default=True)
def workflow_list(query: str, limit: int) -> None:
    """List registered workflow templates."""

    async def _run() -> None:
        store, _ = _get_stores()
        await store.ensure_collection()
        results = await store.search_templates(query or "workflow template", limit=limit)
        if not results:
            click.echo("No workflow templates registered.")
            return
        registry = ModelRegistry()
        known = {a.name for a in registry.list_models()}
        click.echo(f"{len(results)} template(s):\n")
        for _id, _score, tmpl in results:
            click.echo(f"  {tmpl.name}  ({len(tmpl.slot_map)} slots)")
            click.echo(f"    {tmpl.descriptor[:80]}")
            if tmpl.required_models:
                missing = [m for m in tmpl.required_models if m not in known]
                status = "all present" if not missing else f"missing: {', '.join(missing)}"
                click.echo(f"    requires: {', '.join(tmpl.required_models)}  [{status}]")

    asyncio.run(_run())


# ── draft (Phase A — free prompt-craft) ──────────────────────────────────────


def _echo_provenance(legs: list) -> None:
    """Render the deterministic 'what was surfaced' block (shared by draft/redraft)."""
    if not legs:
        return
    click.echo("\n── Knowledge surfaced (deterministic) ───────────────")
    for leg in legs:
        click.echo(
            f"  [{leg.tier}] {leg.label} ({leg.collection}): "
            f"{leg.count} hit(s), top {leg.top_score:.2f}"
        )
        for snip in leg.snippets:
            click.echo(f"      ↳ {snip}")


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
def draft(intent: str | None, points: tuple[str, ...], scene: str | None,
          output: str | None, template_name: str | None, project: str | None,
          from_generation: str | None, image_path: str | None, mask_path: str | None,
          denoise: float | None, model: str | None, provider: str | None) -> None:
    """Craft a settled generation spec and append it to a batch file. Free.

    Give a few key points (INTENT and/or --points) — optionally a --scene — and the
    agent COMPILES the project's own documents (directed.md/brief.md/…) plus retrieved
    knowledge into the prompt; the LLM composes it. No hand-writing prompts.

    With --from/--image the spec becomes a refinement (img2img/inpaint): the points are
    the change to make, the source is resolved + uploaded at `generate`, and the new
    generation records parent lineage.
    """
    if from_generation and image_path:
        raise click.UsageError("Use only one of --from / --image (a source has one origin).")
    if mask_path and not (from_generation or image_path):
        raise click.UsageError("--mask requires a source (--from or --image).")

    source: VisualSource | None = None
    if from_generation or image_path:
        source = VisualSource(
            from_generation=from_generation, image_path=image_path, mask=mask_path
        )

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
    click.echo(f"Template: {result.template_name or '(none — settings are unconstrained)'}")
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
        click.echo("\n── Canon enforced (deterministic) ───────────────────")
        for note in result.canon_applied:
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
def redraft(gen_id: str, change: str, output: str | None, project: str | None,
            model: str | None, provider: str | None) -> None:
    """Revise a prior generation's PROMPT (text2img) by applying CHANGE. Free.

    Inherits the parent's seed, recipe, model, LoRAs, dimensions, and workflow template so
    only the prose changes — continuity can't drift. The new spec is text2img (not an
    img2img edit of the parent's pixels) and records descent via `revised_from`.
    """
    result = redraft_sync(
        gen_id, change, batch_path=output, project=project, model=model, provider=provider
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
    click.echo(f"Template:  {result.template_name}  (recipe inherited from parent)")
    click.echo(f"Model:     {spec.model or '(none)'}"
               + ("  [identity-bearing]" if spec.identity_bearing else ""))
    click.echo(f"Seed:      {spec.seed}  ({spec.seed_strategy})")
    if spec.settings:
        click.echo(f"Settings:  {spec.settings}")
    if spec.lora_stack:
        click.echo("LoRAs:     " + ", ".join(f"{lr.name}@{lr.strength}" for lr in spec.lora_stack))
    click.echo(f"\nPrompt:    {spec.prompt}")
    if spec.negative_prompt:
        click.echo(f"Negative:  {spec.negative_prompt}")
    _echo_provenance(result.provenance)

    if result.overall_reasoning:
        click.echo(f"\nRationale: {result.overall_reasoning}")

    if result.canon_applied:
        click.echo("\n── Canon enforced (deterministic) ───────────────────")
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
        if plan.skipped:
            click.echo(f"Skipped (no resolvable workflow template): {', '.join(plan.skipped)}", err=True)
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
        click.echo(f"  Skipped (no template): {', '.join(plan.skipped)}")
    plan_warnings = [w for sp in plan.plans for w in sp.warnings]
    if plan_warnings:
        click.echo("  ⚠ Refinement advisories:")
        for w in plan_warnings:
            click.echo(f"      • {w}")
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
        click.echo(f"\n── Generation {r.generation_id[:12]} (spec {r.spec_id}) ──")
        click.echo(f"Asset:    {r.asset_path}" + ("  [identity-bearing → secured path]" if r.identity_bearing else ""))
        click.echo(f"GPU cost: ${r.gpu_cost_usd:.4f}  (running ${r.session_cost_running_usd:.4f})")
        if r.rationale:
            click.echo(f"Recipe:   {r.rationale}")
        click.echo(f"Gen id:   {r.generation_id}")
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
    click.echo(f"Recorded: {gen_id[:12]} → {reaction}{rating_str}")


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

        click.echo(f"Query: {report.query}")
        if report.project:
            click.echo(f"Project: {report.project}")

        click.echo("\n── Collection sizes ─────────────────────────────────")
        for name, n in report.collection_counts.items():
            click.echo(f"  {name}: {'unreachable/absent' if n < 0 else n}")

        if report.legs:
            _echo_provenance(report.legs)
        else:
            click.echo("\n⚠ Nothing surfaced for this query.")

        if report.gaps:
            click.echo("\n⚠ Gaps (knowledge that may be getting ignored):")
            for g in report.gaps:
                click.echo(f"  • {g}")
        else:
            click.echo("\n✓ No gaps flagged — relevant knowledge is reachable for this query.")

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
        await store.ensure_collection()
        gens = await store.list_generations(project=project)
        lessons = await store.list_lessons(confirmed_only=True)
        pending = [g for g in await store.list_pending() if g.project == project]

        click.echo(f"Digest for {project!r}")
        click.echo(f"\n── Recent generations ({min(len(gens), limit)} of {len(gens)}) ──────────")
        if not gens:
            click.echo("  (none yet — draft → generate → report to build memory)")
        for g in gens[-limit:][::-1]:
            reaction = g.reaction.upper().replace("_", " ")
            rating = f" ★{g.rating}" if g.rating is not None else ""
            click.echo(f"  {g.entry_id[:12]}  [{reaction}{rating}]  {(g.caption or g.prompt or '')[:70]}")

        if pending:
            click.echo(f"\n── Awaiting your reaction ({len(pending)}) ───────────────")
            for g in pending:
                click.echo(f"  {(g.caption or g.prompt or '')[:66]}")
                click.echo(f"    agent visual-generation report {g.entry_id} "
                           f"--reaction <{'|'.join(REACTIONS)}>")

        if lessons:
            click.echo(f"\n── Confirmed technique lessons ({len(lessons)}) ──────────")
            for le in lessons:
                click.echo(f"  [{le.valence}/{le.scope}] {le.statement[:80]}")

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


@batch.command("list")
@click.argument("batch_file", type=click.Path(exists=True, dir_okay=False))
def batch_list(batch_file: str) -> None:
    """List the specs in BATCH_FILE (spec_id, section title, workflow_ref)."""
    parsed = read_batch(Path(batch_file))
    if not parsed.specs:
        click.echo("No specs in this batch file.")
        return
    click.echo(f"{len(parsed.specs)} spec(s):\n")
    for s in parsed.specs:
        title = s.heading or (s.prompt[:60] if s.prompt else "(untitled)")
        click.echo(f"  {s.spec_id}  [{s.workflow_ref or 'no template'}]  {title}")


@batch.command("rm")
@click.argument("batch_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("spec_id")
@click.option("--yes", "-y", is_flag=True, default=False, help="Delete without the confirmation prompt.")
def batch_rm(batch_file: str, spec_id: str, yes: bool) -> None:
    """Remove the spec with SPEC_ID from BATCH_FILE (other specs are untouched)."""
    path = Path(batch_file)
    parsed = read_batch(path)
    target = next((s for s in parsed.specs if s.spec_id == spec_id), None)
    if target is None:
        known = ", ".join(s.spec_id for s in parsed.specs) or "(none)"
        raise click.ClickException(f"No spec with id {spec_id} in this batch. Known: {known}")
    if not yes:
        title = target.heading or (target.prompt[:60] if target.prompt else spec_id)
        click.confirm(f"Remove spec {spec_id} ({title})?", abort=True)
    remove_spec(parsed, spec_id)
    write_batch(parsed, path)
    click.echo(f"Removed spec {spec_id}. {len(parsed.specs)} spec(s) remain.")


# ── Project canon (deterministic, file-backed) ───────────────────────────────


def _parse_lora(spec: str) -> LoraRef:
    """Parse a NAME[:STRENGTH] CLI token into a LoraRef (strength defaults to 1.0)."""
    name, _, strength = spec.partition(":")
    name = name.strip()
    if not name:
        raise click.BadParameter("--lora needs a registry name (NAME[:STRENGTH])")
    if not strength:
        return LoraRef(name=name)
    try:
        return LoraRef(name=name, strength=float(strength))
    except ValueError as exc:
        raise click.BadParameter(f"--lora strength {strength!r} is not a number") from exc


@cli.group()
def canon() -> None:
    """Manage a project's LOCKED canon (deterministically enforced at draft/redraft)."""


@canon.command("set")
@click.argument("project")
@click.option("--alias", "aliases", multiple=True, required=True,
              help="A name the subject is called by (repeatable). Prefix with @ for a "
                   "token that expands in place (e.g. @narrator). aliases[0] is the key.")
@click.option("--locked", required=True,
              help="The canonical descriptor that must appear whenever the subject is named.")
@click.option("--forbid", "forbid", multiple=True,
              help="A phrasing that contradicts canon and is stripped (repeatable).")
@click.option("--lora", "lora", default=None,
              help="Character LoRA pinned whenever this subject appears, as "
                   "NAME[:STRENGTH] (strength defaults to 1.0). The NAME must key into "
                   "the model registry; flag it identity_bearing there.")
def canon_set(
    project: str, aliases: tuple[str, ...], locked: str, forbid: tuple[str, ...],
    lora: str | None,
) -> None:
    """Upsert a locked subject for PROJECT (keyed by its first alias)."""
    lora_ref = _parse_lora(lora) if lora else None
    store = ProjectCanon(project)
    subject = store.set_subject(list(aliases), locked, list(forbid), lora=lora_ref)
    click.echo(f"Canon set for {project!r} (subject '{subject.aliases[0]}'):")
    click.echo(f"  aliases: {', '.join(subject.aliases)}")
    click.echo(f"  locked:  {subject.locked}")
    if subject.forbid:
        click.echo(f"  forbid:  {', '.join(subject.forbid)}")
    if subject.lora:
        click.echo(f"  lora:    {subject.lora.name}@{subject.lora.strength}")
    click.echo(f"\nStored at: {store.path}")


@canon.command("show")
@click.argument("project")
def canon_show(project: str) -> None:
    """Show PROJECT's locked canon subjects."""
    store = ProjectCanon(project)
    subjects = store.load()
    if not subjects:
        click.echo(f"No canon for {project!r} (looked at {store.path}).")
        return
    click.echo(f"Canon for {project!r} ({len(subjects)} subject(s)):")
    for s in subjects:
        click.echo(f"\n  • aliases: {', '.join(s.aliases)}")
        click.echo(f"    locked:  {s.locked}")
        if s.forbid:
            click.echo(f"    forbid:  {', '.join(s.forbid)}")
        if s.lora:
            click.echo(f"    lora:    {s.lora.name}@{s.lora.strength}")


@canon.command("rm")
@click.argument("project")
@click.argument("alias")
def canon_rm(project: str, alias: str) -> None:
    """Remove the canon subject that any of whose aliases match ALIAS."""
    store = ProjectCanon(project)
    if store.remove(alias):
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
        await store.ensure_collection()
        le = TechniqueLesson(statement=statement, scope=scope, valence=valence, confirmed=True)
        await store.upsert_lesson(le)
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
        await store.ensure_collection()
        lessons = await store.list_lessons(
            confirmed_only=not include_unconfirmed, scope=scope, valence=valence)
        if not lessons:
            click.echo("No technique lessons.")
            return
        click.echo(f"Technique lessons ({len(lessons)}):")
        for le in lessons:
            conf = "" if le.confirmed else " (unconfirmed)"
            click.echo(f"  {le.entry_id}  [{le.valence}/{le.scope}]{conf} {le.statement[:80]}")

    asyncio.run(_run())


@lesson.command("rm")
@click.argument("entry_id")
@click.option("--yes", is_flag=True, default=False,
              help="Delete without the confirmation prompt.")
def lesson_rm(entry_id: str, yes: bool) -> None:
    """Delete the technique lesson with ENTRY_ID (refuses non-lesson ids)."""

    async def _run() -> None:
        store, _ = _get_stores()
        await store.ensure_collection()
        try:
            le = await store.get_lesson(entry_id)
        except ValueError as exc:
            raise click.ClickException(
                f"Entry {entry_id} is a {exc}, not a technique_lesson; refusing to delete.")
        if le is None:
            raise click.ClickException(f"No technique lesson with id {entry_id}.")
        if not yes:
            click.confirm(
                f"Remove [{le.valence}/{le.scope}] {le.statement[:60]}?", abort=True)
        await store.delete_lesson(entry_id)
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
        await uks.ensure_collection()
        entry_ids = await uks.bulk_load_verified(
            [{"statement": statement, "domain": domain,
              "source_type": "user_verified", "confidence": confidence}],
            source_ref="manual:cli",
        )
        click.echo(f"Added fact to {domain}: {statement[:60]}")
        click.echo(f"Entry ID: {entry_ids[0]}")

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
