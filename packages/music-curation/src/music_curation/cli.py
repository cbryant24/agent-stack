"""music-curation CLI.

Usage:
    music-curation generate "<request>"
    music-curation report <gen_id> --reaction <X>
    music-curation review-pending
    music-curation recall "<query>"
    music-curation taste add "<lesson>"
    music-curation fact add "<statement>"
    music-curation chain show <chain_root_id>
    music-curation seed ingest <path>
    music-curation seed review-taste
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click

from music_curation.agent import _get_stores, curate_sync
from music_curation.constants import DEFAULT_BUDGET
from music_curation.retrieval import retrieve_context
from music_curation.seed_ingestion import ingest_seed, review_taste_queue


# ── Top-level group ────────────────────────────────────────────────────────────

@click.group()
def cli() -> None:
    """Music curation agent — craft Suno prompts with persistent memory."""


# ── generate ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("request")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD.")
@click.option("--skip-question", is_flag=True, default=False, help="Skip clarifying question check.")
@click.option("--dry-run", is_flag=True, default=False, help="Retrieve + plan, no LLM generation.")
@click.option("--variants", type=int, default=2, show_default=True, help="Number of prompt variants.")
def generate(request: str, max_cost: float | None, skip_question: bool, dry_run: bool, variants: int) -> None:
    """Generate Suno prompts for the given request."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )

    result = curate_sync(request, budget=budget, skip_question=skip_question, dry_run=dry_run)

    # Show clarifying question if one was raised
    pending_q = result.__dict__.get("_pending_question")
    if pending_q and pending_q.get("ask"):
        click.echo("\n── Clarifying question ──────────────────────────────")
        click.echo(f"Q: {pending_q['question']}")
        click.echo(f"   Suggestion: {pending_q['suggestion']}")
        click.echo(f"   Why: {pending_q['reasoning']}")
        click.echo("")

    click.echo(f"Status:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")

    for i, prompt in enumerate(result.prompts, 1):
        click.echo(f"\n── Prompt {i} ─────────────────────────────────────────")
        if i <= len(result.suggested_titles):
            click.echo(f"Title: {result.suggested_titles[i-1]}")
        click.echo(f"Style ({len(prompt.style_field)} chars):\n{prompt.style_field}")
        if prompt.lyrics_field:
            click.echo(f"\nLyrics:\n{prompt.lyrics_field}")
        if i <= len(result.generation_ids):
            click.echo(f"\nGeneration ID: {result.generation_ids[i-1]}")
            click.echo("(Use 'music-curation report <id> --reaction <X>' after running in Suno)")

    if result.theory_reasoning:
        click.echo(f"\n── Theory Reasoning ─────────────────────────────────")
        click.echo(result.theory_reasoning)

    if result.cross_references:
        click.echo(f"\n── Similar Prior Generations ({len(result.cross_references)}) ──────────")
        for ref in result.cross_references:
            click.echo(f"  [{ref.reaction}] {ref.suggested_track_title or ref.entry_id[:8]}")
            click.echo(f"    {ref.style_field_excerpt}...")

    if result.report_path:
        click.echo(f"\nReport: {result.report_path}")


# ── report ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("gen_id")
@click.option("--reaction", required=True,
              type=click.Choice([
                  "loved", "liked", "liked_with_changes",
                  "disliked", "prompt_failed",
                  "copyright_blocked", "never_ran", "lost_track",
              ]),
              help="Reaction to the Suno output. 'disliked' = rendered correctly but "
                   "not to taste (aesthetic); 'prompt_failed' = Suno didn't render the "
                   "prompt's intent (prompt-engineering issue, territory still open).")
@click.option("--rating", type=click.IntRange(1, 5), default=None,
              help="Optional 1-5 intensity. Meaningful for positive reactions "
                   "(loved/liked/liked_with_changes).")
@click.option("--notes", default=None,
              help="Action-oriented: what to change or do differently next time.")
@click.option("--context", default=None,
              help="Reasoning-oriented: why you reacted this way (used for retrieval "
                   "and pattern-finding over time).")
def report(gen_id: str, reaction: str, rating: int | None,
           notes: str | None, context: str | None) -> None:
    """Record your reaction to a generated prompt after running it in Suno."""
    from music_curation.constants import POSITIVE_REACTIONS

    if rating is not None and reaction not in POSITIVE_REACTIONS:
        click.echo(
            f"Warning: --rating is unusual for '{reaction}' (ratings are meaningful "
            f"for positive reactions). Recording it anyway.",
            err=True,
        )

    async def _run():
        curation_store, _, _ = _get_stores()
        await curation_store.ensure_collection()
        gen = await curation_store.get_generation(gen_id)
        if gen is None:
            click.echo(f"Error: generation '{gen_id}' not found.", err=True)
            sys.exit(1)
        await curation_store.update_generation_reaction(
            gen_id, reaction, notes=notes, context=context, rating=rating
        )
        rating_str = f" ★{rating}" if rating is not None else ""
        click.echo(f"Recorded: {gen.suggested_track_title or gen_id[:12]} → {reaction}{rating_str}")

    asyncio.run(_run())


# ── review-pending ─────────────────────────────────────────────────────────────

@cli.command("review-pending")
def review_pending() -> None:
    """Show all pending generations (run in Suno but reaction not yet recorded)."""
    async def _run():
        curation_store, _, _ = _get_stores()
        await curation_store.ensure_collection()
        pending = await curation_store.list_pending()
        if not pending:
            click.echo("No pending generations.")
            return
        click.echo(f"{len(pending)} pending generation(s):\n")
        for gen in pending:
            title = gen.suggested_track_title or gen.entry_id[:12]
            click.echo(f"  {gen.entry_id}")
            click.echo(f"  Title: {title}")
            click.echo(f"  Style: {gen.style_field[:80]}...")
            click.echo(f"  Created: {gen.created_at}")
            click.echo("  Use: music-curation report <id> --reaction <X>")
            click.echo("")

    asyncio.run(_run())


# ── recall ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--limit", default=5, show_default=True, help="Max results per collection.")
def recall(query: str, limit: int) -> None:
    """Search memory for prior generations, taste lessons, and Suno facts."""
    async def _run():
        curation_store, memory_store, _ = _get_stores()
        await curation_store.ensure_collection()
        ctx = await retrieve_context(
            query, curation_store, memory_store,
            generation_limit=limit, taste_limit=limit, suno_fact_limit=limit,
        )

        if ctx.is_empty():
            click.echo("No results found.")
            return

        if ctx.prior_generations:
            click.echo(f"\n── Prior Generations ({len(ctx.prior_generations)}) ────────────────")
            for score, gen in ctx.prior_generations:
                title = gen.suggested_track_title or gen.entry_id[:12]
                rating_str = f" ★{gen.rating}" if gen.rating is not None else ""
                click.echo(f"  [{score:.3f}] {title} (reaction={gen.reaction}{rating_str})")
                click.echo(f"    {gen.style_field[:100]}...")

        if ctx.taste_lessons:
            click.echo(f"\n── Taste Lessons ({len(ctx.taste_lessons)}) ─────────────────────")
            for score, lesson in ctx.taste_lessons:
                click.echo(f"  [{score:.3f}][{lesson.valence}/{lesson.scope}] {lesson.statement[:80]}")

        if ctx.suno_facts:
            click.echo(f"\n── Suno Facts ({len(ctx.suno_facts)}) ──────────────────────────")
            for score, statement, _ in ctx.suno_facts:
                click.echo(f"  [{score:.3f}] {statement[:80]}")

        if ctx.tutorial_hits:
            click.echo(f"\n── Tutorial Knowledge ({len(ctx.tutorial_hits)}) ─────────────────")
            for score, content in ctx.tutorial_hits:
                if content:
                    click.echo(f"  [{score:.3f}] {content[:100]}")

    asyncio.run(_run())


# ── taste ──────────────────────────────────────────────────────────────────────

@cli.group()
def taste() -> None:
    """Manage taste lessons."""


@taste.command("add")
@click.argument("lesson")
@click.option("--valence", type=click.Choice(["positive", "negative"]), required=True)
@click.option("--scope", type=click.Choice(["genre", "production", "instrumentation", "vocal", "arrangement", "general"]), default="general")
def taste_add(lesson: str, valence: str, scope: str) -> None:
    """Add an explicit confirmed taste lesson."""
    from music_curation.models import TasteLesson

    async def _run():
        curation_store, _, _ = _get_stores()
        await curation_store.ensure_collection()
        t = TasteLesson(statement=lesson, valence=valence, scope=scope, confirmed=True)
        await curation_store.upsert_taste(t)
        click.echo(f"Added taste lesson [{valence}/{scope}]: {lesson[:60]}")

    asyncio.run(_run())


# ── fact ───────────────────────────────────────────────────────────────────────

@cli.group()
def fact() -> None:
    """Manage Suno facts in user_knowledge."""


@fact.command("add")
@click.argument("statement")
@click.option("--domain", default="suno_mechanics", show_default=True)
@click.option("--confidence", type=click.Choice(["high", "medium", "low"]), default="high")
def fact_add(statement: str, domain: str, confidence: str) -> None:
    """Add a verified Suno fact directly to user_knowledge."""
    from agent_runtime import UserKnowledgeStore, get_memory_store

    async def _run():
        ms = get_memory_store()
        uks = UserKnowledgeStore(ms)
        await uks.ensure_collection()
        entry_id = await uks.bulk_load_verified(
            [{"statement": statement, "domain": domain, "confidence": confidence}],
            source_ref="manual:cli",
        )
        click.echo(f"Added fact to {domain}: {statement[:60]}")
        click.echo(f"Entry ID: {entry_id[0]}")

    asyncio.run(_run())


# ── chain ──────────────────────────────────────────────────────────────────────

@cli.group()
def chain() -> None:
    """Inspect generation evolution chains."""


@chain.command("show")
@click.argument("chain_root_id")
def chain_show(chain_root_id: str) -> None:
    """Show the full evolution chain for a generation."""
    async def _run():
        curation_store, _, _ = _get_stores()
        await curation_store.ensure_collection()
        entries = await curation_store.get_chain(chain_root_id)
        if not entries:
            click.echo(f"No chain found for root_id: {chain_root_id}")
            return
        click.echo(f"Chain ({len(entries)} entries):\n")
        for i, gen in enumerate(entries):
            indent = "  " * (1 if gen.parent_id else 0)
            title = gen.suggested_track_title or gen.entry_id[:12]
            click.echo(f"{indent}[{gen.reaction}] {title}")
            if gen.change_summary:
                click.echo(f"{indent}  Changes: {gen.change_summary[:80]}")
            click.echo(f"{indent}  Style: {gen.style_field[:80]}...")
            click.echo(f"{indent}  ID: {gen.entry_id}")
            click.echo("")

    asyncio.run(_run())


# ── seed group ─────────────────────────────────────────────────────────────────

@cli.group()
def seed() -> None:
    """Seed music-curation memory from session files."""


@seed.command("ingest")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False, help="Parse and show counts without writing.")
@click.option("--yes", is_flag=True, default=False, help="Skip all confirmations (write everything).")
def seed_ingest(path: Path, dry_run: bool, yes: bool) -> None:
    """Ingest seed files from PATH (file or directory) into music-curation memory."""
    asyncio.run(ingest_seed(path, dry_run=dry_run, auto_confirm=yes))


@seed.command("review-taste")
def seed_review_taste() -> None:
    """Interactively review and confirm deferred taste lessons."""
    asyncio.run(review_taste_queue())
