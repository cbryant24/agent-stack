"""orchestrator CLI.

Usage:
    orchestrator chat [--thread <id>]
"""
from __future__ import annotations

import asyncio

import click
from ulid import ULID

from orchestrator.agent import build_app, run_turn
from orchestrator.constants import checkpointer_db_path


@click.group()
def cli() -> None:
    """Orchestrator — the conversational meta-agent over the agent-stack system."""


@cli.command()
@click.option("--thread", "thread", default=None, help="Resume a checkpointed thread by id.")
def chat(thread: str | None) -> None:
    """Start an interactive, checkpointed chat session.

    A new thread is created per launch unless --thread resumes an existing one.
    Conversation state is persisted (LangGraph SqliteSaver) and resumable across
    sessions. The per-session cumulative cost is surfaced as a soft tally — it is
    informational, NOT a hard cap (a checkpointed thread is meant to resume).
    """
    asyncio.run(_chat_repl(thread))


async def _chat_repl(thread: str | None) -> None:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = checkpointer_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()  # library managing its own tables — not the migration runner
        graph = build_app(saver)

        thread_id = thread or str(ULID())
        resumed = thread is not None
        click.echo(f"Orchestrator chat — thread {thread_id}{' (resumed)' if resumed else ''}")
        click.echo("Type a message. Ctrl-D or 'exit' to quit.\n")

        session_cost = 0.0
        while True:
            try:
                message = click.prompt("you", prompt_suffix="> ")
            except (EOFError, click.Abort):
                click.echo("\nGoodbye.")
                break
            if message.strip().lower() in {"exit", "quit"}:
                click.echo("Goodbye.")
                break
            if not message.strip():
                continue

            result = await run_turn(graph, message, thread_id)
            session_cost += result.consumption.cost_usd

            click.echo(f"\norchestrator> {result.response}\n")
            if result.status == "partial":
                click.echo("(partial — per-turn budget was reached)")
            click.echo(
                f"[turn: ${result.consumption.cost_usd:.4f}, "
                f"{result.consumption.tool_calls} tool calls | "
                f"session so far: ${session_cost:.4f}]\n"
            )
