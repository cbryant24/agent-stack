"""visual-generation CLI — backend, templates, and the draft→generate→report turn.

Usage:
    visual-generation model sync --endpoint <url> [--yes]
    visual-generation model list
    visual-generation workflow register <exported-api.json> [--name N] [--descriptor D] [--yes]
    visual-generation workflow list
    visual-generation draft "<intent>" [-o batch.md] [--template <name>]
    visual-generation generate <batch.md> (--section <id> | --all) --endpoint <url>
        [--gpu-rate N] [--max-session-cost N] [--yes]
    visual-generation report <gen_id> --reaction <X> [--rating N] [--notes ...] [--context ...]
    visual-generation review-pending
    visual-generation chain show <root_id>
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
from visual_generation.comfyui_client import ComfyUIClient, ComfyUIError
from visual_generation.constants import (
    DEFAULT_GPU_RATE_USD_PER_HR,
    EXPLAIN_LEVELS,
    LESSON_SCOPE_MODEL,
    LESSON_SCOPE_PROMPT,
    LESSON_SCOPE_SETTINGS,
    LESSON_SCOPE_WORKFLOW,
    MECHANICS_DOMAINS,
    POSITIVE_REACTIONS,
    REACTIONS,
)
from visual_generation.draft import draft_sync
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
from visual_generation.models import TechniqueLesson, VisualSource, WorkflowTemplate
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
        click.echo("No models registered. Run: visual-generation model sync --endpoint <url>")
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


@cli.command()
@click.argument("intent")
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Batch file to append to (default: <project>.batch.md under agent-data).")
@click.option("--template", "template_name", default=None,
              help="Workflow template name to target (default: the top retrieved template).")
@click.option("--project", default=None, help="Project tag for the spec.")
@click.option("--from", "from_generation", default=None,
              help="Refine a prior generation by id (img2img/inpaint) — its saved frame "
                   "becomes the source. Mutually exclusive with --image.")
@click.option("--image", "image_path", type=click.Path(dir_okay=False), default=None,
              help="Refine from an external image on disk. Mutually exclusive with --from.")
@click.option("--mask", "mask_path", type=click.Path(dir_okay=False), default=None,
              help="Inpaint mask PNG (white = area to change). Requires --from or --image.")
@click.option("--denoise", type=float, default=None,
              help="Refinement denoise (default 0.5; coherent range ~0.4–0.7).")
def draft(intent: str, output: str | None, template_name: str | None, project: str | None,
          from_generation: str | None, image_path: str | None, mask_path: str | None,
          denoise: float | None) -> None:
    """Craft a settled generation spec from INTENT and append it to a batch file. Free.

    With --from/--image the spec becomes a refinement (img2img/inpaint): INTENT is the
    change to make, the source is resolved + uploaded at `generate`, and the new
    generation records parent lineage. No hand-editing of the batch JSON needed.
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
        batch_path=output,
        template_name=template_name,
        project=project,
        source=source,
        denoise=denoise,
    )

    if result.status == "failed":
        click.echo("Draft failed (no spec produced).", err=True)
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
    if result.overall_reasoning:
        click.echo(f"\nRationale: {result.overall_reasoning}")

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
            f'  visual-generation research "{result.research_offer}"'
        )

    if result.batch_path:
        click.echo(f"\nAppended to: {result.batch_path}")
        click.echo(f"Next: visual-generation generate {result.batch_path} --section "
                   f"{spec.spec_id} --endpoint <url>")


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

    click.echo("\nReview, then: visual-generation report <gen_id> --reaction <X>")
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
        click.echo(f"Error: generation '{gen_id}' not found.", err=True)
        raise SystemExit(1)
    rating_str = f" ★{rating}" if rating is not None else ""
    click.echo(f"Recorded: {gen_id[:12]} → {reaction}{rating_str}")


# ── Inspect (review-pending / chain show / recall) — pure reads ───────────────


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
