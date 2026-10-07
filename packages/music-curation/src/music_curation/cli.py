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
    music-curation chat
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
from music_curation.curation import add_fact, add_taste, rating_warning, record_reaction
from music_curation.reads import render_chain, render_pending, render_recall, render_result
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
    click.echo(render_result(result))


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
    warning = rating_warning(reaction, rating)
    if warning:
        click.echo(warning, err=True)

    async def _run():
        curation_store, _, _ = _get_stores()
        gen = await record_reaction(
            gen_id, reaction, store=curation_store, rating=rating, notes=notes, context=context
        )
        if gen is None:
            click.echo(f"Error: generation '{gen_id}' not found.", err=True)
            sys.exit(1)
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
        click.echo(render_pending(await curation_store.list_pending()))

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
        click.echo(render_recall(ctx))

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
    async def _run():
        curation_store, _, _ = _get_stores()
        await add_taste(lesson, valence, scope, store=curation_store)
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
        entry_id = await add_fact(statement, domain, confidence, uks=UserKnowledgeStore(get_memory_store()))
        click.echo(f"Added fact to {domain}: {statement[:60]}")
        click.echo(f"Entry ID: {entry_id}")

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
        click.echo(render_chain(chain_root_id, await curation_store.get_chain(chain_root_id)))

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


# ── chat (conversational front end; needs the optional `chat` extra) ───────────

_CHAT_LIBS = {"agent_shell", "langgraph", "langchain_core", "langchain_anthropic",
              "langchain_openai", "prompt_toolkit", "rich"}


@cli.command("chat")
@click.option("--provider", type=click.Choice(["claude", "openai"]), default="claude",
              show_default=True, help="Which model runs the conversation.")
@click.option("--model", default=None, help="Model id (must have a price row). Required for openai.")
@click.option("--resume", "resume_id", default=None, help="Resume a chat session id.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Paid and writing tools describe what they would do and run nothing.")
def chat(provider: str, model: str | None, resume_id: str | None, dry_run: bool) -> None:
    """Chat with the agent: look things up, write prompts, record reactions, curate taste.

    Every memory write is confirmed first. Run under op run: `agent music-curation chat`."""
    try:
        from music_curation.chat.cli import run_chat
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in _CHAT_LIBS:
            raise
        raise click.ClickException(
            f"chat needs its optional libraries ({exc.name} is missing). "
            "Install them with: uv sync --all-packages --extra chat   (music-curation[chat])"
        ) from exc
    run_chat(provider, model, resume_id, dry_run)
