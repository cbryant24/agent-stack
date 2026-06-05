"""voiceover-direction CLI.

Usage:
    voiceover-direction direct <script.md> [--output <path>] [--dry-run]
    voiceover-direction generate <script.directed.md> (--section <id> | --all) [--yes]
    voiceover-direction report <take_id> --reaction <X> [--rating N] [--notes ...] [--context ...]
    voiceover-direction review-pending
    voiceover-direction recall "<query>"
"""

from __future__ import annotations

import asyncio
import sys

import click

from voiceover_direction.agent import _get_stores, direct_sync
from voiceover_direction.constants import (
    DEFAULT_BUDGET,
    ELEVENLABS_MECHANICS_DOMAIN,
    GENERATE_BUDGET,
    POSITIVE_REACTIONS,
    REACTIONS,
)
from voiceover_direction.docs_ingest import ingest_docs_sync
from voiceover_direction.generation import plan_generation_sync, spend_generation_sync
from voiceover_direction.models import CharacterUsage, DirectionLesson


@click.group()
def cli() -> None:
    """Voiceover direction agent — direct a script for ElevenLabs narration."""


@cli.command()
@click.argument("script", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", "output", type=click.Path(dir_okay=False), default=None,
              help="Where to write the directed-script file (default: <script>.directed.md).")
@click.option("--project-id", default=None, help="Project id (default: the script's filename stem).")
@click.option("--domain", default=None, help="Optional domain tag for the directed script.")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD for the run.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Parse + retrieve only; no LLM call, no file written.")
def direct(
    script: str,
    output: str | None,
    project_id: str | None,
    domain: str | None,
    max_cost: float | None,
    dry_run: bool,
) -> None:
    """Direct SCRIPT (a markdown file) into an editable directed-script file. Free, re-runnable."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )

    result = direct_sync(
        script,
        budget=budget,
        output_path=output,
        project_id=project_id,
        domain=domain,
        dry_run=dry_run,
    )

    click.echo(f"Status:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")
    click.echo(f"Sections:  {len(result.directed_script.sections)}")
    if result.output_path:
        click.echo(f"Written:   {result.output_path}")
    elif dry_run:
        click.echo("(dry run — no file written)")

    if result.overall_reasoning:
        click.echo("\n── Direction notes ──────────────────────────────────")
        click.echo(result.overall_reasoning)

    if result.report_path:
        click.echo(f"\nReport: {result.report_path}")


async def _query_usage() -> CharacterUsage | None:
    """Fresh vendor read for the gate (source of truth). None if it can't be reached."""
    from voiceover_direction.elevenlabs_client import ElevenLabsClient

    try:
        return await ElevenLabsClient().get_usage()
    except Exception as exc:  # noqa: BLE001 — degrade to "unknown", still let the user decide
        click.echo(f"(could not query ElevenLabs usage: {exc})", err=True)
        return None


@cli.command()
@click.argument("directed", type=click.Path(exists=True, dir_okay=False))
@click.option("--section", "section_id", default=None, help="Generate one section by id.")
@click.option("--all", "all_sections", is_flag=True, default=False,
              help="Generate every section (trusted direction).")
@click.option("--raw", is_flag=True, default=False,
              help="Generate the file's section markup verbatim — skip the fold-in "
                   "re-direction (the hand-edit branch).")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Skip the cost gate and spend without confirming.")
@click.option("--max-cost", type=float, default=None,
              help="Override the re-direction cost cap (USD) for this run.")
def generate(directed: str, section_id: str | None, all_sections: bool,
             raw: bool, yes: bool, max_cost: float | None) -> None:
    """Generate audio for section(s) of a DIRECTED script. Spends ElevenLabs characters.

    If a section's last take carries a `report` note, the note is folded into a section-scoped
    re-direction (a Claude call) and the revised markup is shown at the gate before spending.
    `--raw` skips that and speaks the file's markup verbatim.
    """
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=GENERATE_BUDGET.max_items,
        max_depth=GENERATE_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else GENERATE_BUDGET.max_cost_usd,
        max_wall_time_sec=GENERATE_BUDGET.max_wall_time_sec,
    )

    # Plan phase — resolves each section (folding in notes unless --raw). Carries the Claude cost.
    try:
        plan = plan_generation_sync(
            directed, section_id=section_id, all_sections=all_sections, raw=raw, budget=budget
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    if not plan.plans:
        click.echo("Nothing to generate: no targeted section has a voice_id set.", err=True)
        if plan.skipped:
            click.echo(f"Sections without a voice: {', '.join(plan.skipped)}", err=True)
        raise SystemExit(1)

    total_chars = sum(p.char_count for p in plan.plans)
    usage = asyncio.run(_query_usage())

    # ── Soft-inform cost gate (shows the revised markup before any spend) ───────
    click.echo("── Cost gate (soft-inform) ──────────────────────────")
    for p in plan.plans:
        click.echo(f"  {p.section_id}: {p.char_count} chars  (voice {p.voice_id})")
        if p.was_redirected:
            click.echo(f'    ↻ re-directed (folded in note: "{p.note}")')
            click.echo(f"    revised: {p.text}")
    if plan.skipped:
        click.echo(f"  skipping (no voice): {', '.join(plan.skipped)}")
    click.echo(f"Total to spend: {total_chars} characters")
    if usage is not None:
        click.echo(f"Vendor remaining: {usage.characters_remaining} / {usage.character_limit}")
    else:
        click.echo("Vendor remaining: unknown")
    if plan.cost_usd:
        click.echo(f"Re-direction cost: ${plan.cost_usd:.4f}")

    if not yes:
        click.confirm(f"Spend {total_chars} characters?", abort=True)

    # Spend phase — TTS + pending takes. No Claude cost; characters never in the budget.
    result = spend_generation_sync(
        plan,
        usage_remaining=usage.characters_remaining if usage is not None else None,
    )

    click.echo(f"\nStatus:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Generated: {result.items_processed} section(s)")
    for r in result.results:
        click.echo(f"\n── Take {r.take_id} ─────────────────────────────────")
        click.echo(f"Audio:     {r.audio_path}")
        click.echo(f"Cost:      {r.character_cost} characters")
        if r.remaining_characters is not None:
            click.echo(f"Remaining: {r.remaining_characters}")
    if result.skipped:
        click.echo(f"\nSkipped (no voice): {', '.join(result.skipped)}")
    click.echo("\nListen, then: voiceover-direction report <take_id> --reaction <X>  (Step 4)")

    if result.report_path:
        click.echo(f"\nReport: {result.report_path}")


# ── report (React) ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("take_id")
@click.option("--reaction", required=True, type=click.Choice(REACTIONS),
              help="Reaction to the take's audio. 'disliked' = rendered faithfully but not "
                   "to taste (aesthetic — weighs against the direction); 'render_failed' = "
                   "ElevenLabs didn't render the intent (tags ignored / mispronunciation — "
                   "the direction was fine, territory still open).")
@click.option("--rating", type=click.IntRange(1, 5), default=None,
              help="Optional 1-5 intensity. Meaningful for positive reactions "
                   "(loved/liked/liked_with_changes).")
@click.option("--notes", default=None,
              help="Action-oriented: what to change or do differently next time.")
@click.option("--context", default=None,
              help="Reasoning-oriented: why you reacted this way (becomes retrievable signal).")
def report(take_id: str, reaction: str, rating: int | None,
           notes: str | None, context: str | None) -> None:
    """Record your reaction to a take after listening, flipping it pending -> complete."""
    if rating is not None and reaction not in POSITIVE_REACTIONS:
        click.echo(
            f"Warning: --rating is unusual for '{reaction}' (ratings are meaningful for "
            "positive reactions). Recording it anyway.",
            err=True,
        )

    async def _run() -> None:
        store, _, _ = _get_stores()
        await store.ensure_collection()
        take = await store.get_take(take_id)
        if take is None:
            click.echo(f"Error: take '{take_id}' not found.", err=True)
            sys.exit(1)
        await store.update_take_reaction(
            take_id, reaction, rating=rating, notes=notes, context=context
        )
        rating_str = f" ★{rating}" if rating is not None else ""
        click.echo(f"Recorded: {take.section_id} ({take_id[:12]}) → {reaction}{rating_str}")

    asyncio.run(_run())


# ── review-pending (Inspect) ─────────────────────────────────────────────────


@cli.command("review-pending")
def review_pending() -> None:
    """Show takes awaiting a reaction (generated but not yet reacted to)."""

    async def _run() -> None:
        store, _, _ = _get_stores()
        await store.ensure_collection()
        pending = await store.list_pending()
        if not pending:
            click.echo("No pending takes.")
            return
        click.echo(f"{len(pending)} pending take(s):\n")
        for take in pending:
            click.echo(f"  {take.entry_id}")
            click.echo(f"  Section: {take.section_id}  (project {take.project_id})")
            click.echo(f"  Voice: {take.voice_id} | Model: {take.model}")
            click.echo(f"  Created: {take.created_at}")
            click.echo(f"  Text: {take.text[:80]}")
            click.echo("  Use: voiceover-direction report <id> --reaction <X>")
            click.echo("")

    asyncio.run(_run())


# ── recall (Inspect) ─────────────────────────────────────────────────────────


@cli.command()
@click.argument("query")
@click.option("--limit", default=5, show_default=True, help="Max results per kind.")
def recall(query: str, limit: int) -> None:
    """Search prior takes and direction lessons. Returns hits, not answers."""

    async def _run() -> None:
        store, _, _ = _get_stores()
        await store.ensure_collection()
        takes, lessons = await asyncio.gather(
            store.search_takes(query, exclude_pending=True, limit=limit),
            store.search_lessons(query, confirmed_only=False, limit=limit),
        )

        if not takes and not lessons:
            click.echo("No results found.")
            return

        if takes:
            click.echo(f"\n── Prior Takes ({len(takes)}) ──────────────────────────")
            for _id, score, take in takes:
                rating_str = f" ★{take.rating}" if take.rating is not None else ""
                click.echo(
                    f"  [{score:.3f}] {take.section_id} (reaction={take.reaction}{rating_str}) "
                    f"— {take.text[:80]}"
                )
                if take.context:
                    click.echo(f"      context: {take.context[:120]}")

        if lessons:
            click.echo(f"\n── Direction Lessons ({len(lessons)}) ──────────────────")
            for _id, score, lesson in lessons:
                click.echo(f"  [{score:.3f}][{lesson.valence}/{lesson.scope}] {lesson.statement[:80]}")

    asyncio.run(_run())


# ── lesson (direct write) ────────────────────────────────────────────────────


@cli.group()
def lesson() -> None:
    """Manage direction lessons."""


@lesson.command("add")
@click.argument("statement")
@click.option("--valence", type=click.Choice(["positive", "negative"]), default="positive",
              show_default=True)
@click.option("--scope", type=click.Choice(["voice", "pacing", "tone", "general"]),
              default="general", show_default=True)
def lesson_add(statement: str, valence: str, scope: str) -> None:
    """Add a confirmed direction lesson (running the command is the confirmation)."""

    async def _run() -> None:
        store, _, _ = _get_stores()
        await store.ensure_collection()
        le = DirectionLesson(statement=statement, valence=valence, scope=scope, confirmed=True)
        await store.upsert_lesson(le)
        click.echo(f"Added direction lesson [{valence}/{scope}]: {statement[:60]}")

    asyncio.run(_run())


# ── fact (direct write to user_knowledge) ────────────────────────────────────


@cli.group()
def fact() -> None:
    """Manage ElevenLabs mechanics facts in user_knowledge."""


@fact.command("add")
@click.argument("statement")
@click.option("--domain", default=ELEVENLABS_MECHANICS_DOMAIN, show_default=True)
@click.option("--confidence", type=click.Choice(["high", "medium", "low"]), default="high",
              show_default=True)
def fact_add(statement: str, domain: str, confidence: str) -> None:
    """Add a verified fact directly to user_knowledge."""
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


# ── voice (registry sync from ElevenLabs) ────────────────────────────────────


@cli.group()
def voice() -> None:
    """Manage the voice registry."""


@voice.command("sync")
def voice_sync() -> None:
    """Sync available voices from ElevenLabs into the registry (wholesale overwrite)."""
    from voiceover_direction.elevenlabs_client import ElevenLabsClient

    async def _run() -> None:
        store, _, _ = _get_stores()
        voices = await ElevenLabsClient().list_voices()
        store.sync_voices(voices)
        stock = sum(1 for v in voices if v.category == "stock")
        cloned = len(voices) - stock
        click.echo(f"Synced {len(voices)} voices ({stock} stock, {cloned} cloned).")

    asyncio.run(_run())


# ── knowledge (ingest local ElevenLabs docs) ─────────────────────────────────


@cli.group()
def knowledge() -> None:
    """Ingest knowledge into user_knowledge."""


@knowledge.command("ingest-docs")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, default=False,
              help="Parse and show candidate counts without writing.")
@click.option("--yes", is_flag=True, default=False,
              help="Confirm and write every candidate without prompting.")
def knowledge_ingest_docs(folder: str, dry_run: bool, yes: bool) -> None:
    """Parse local ElevenLabs docs in FOLDER into verified user_knowledge (y/n/edit/defer)."""
    ingest_docs_sync(folder, dry_run=dry_run, auto_confirm=yes)
