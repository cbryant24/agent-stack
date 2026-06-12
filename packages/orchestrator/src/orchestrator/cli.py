"""orchestrator CLI.

Usage:
    orchestrator chat [--thread <id>]
    orchestrator remediate <report-path> [-y]
"""
from __future__ import annotations

import asyncio
from pathlib import Path

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


@cli.command()
@click.argument("report_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", "-y", "yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
def remediate(report_path: Path, yes: bool) -> None:
    """Delegate a diagnosed report's remediation to its owning agent.

    Loads the diagnostic report, refuses unless it is still `open` and carries a
    remediation spec, shows the spec + target collection, and (after confirmation)
    hands it to the owning agent's registered handler — which performs the Qdrant
    write under its own ownership. The orchestrator never writes to Qdrant; this
    command only triggers the delegation. The report file transitions
    open → delegated → fixed (or back to open if the handler refuses).
    """
    from orchestrator.diagnostics import (
        delegate_remediation,
        get_remediation_handler,
        load_diagnostic_report,
    )
    from orchestrator.tools import register_remediation_handlers

    report = load_diagnostic_report(report_path)

    if report.status != "open":
        raise click.ClickException(
            f"Report status is '{report.status}', not 'open' — nothing to delegate."
        )
    if report.remediation is None:
        raise click.ClickException(
            "Report carries no remediation spec — it is a manual work order, not a "
            "machine-actionable fix."
        )

    spec = report.remediation
    click.echo(f"Report:     {report_path}")
    click.echo(f"Collection: {report.collection} (owner: {report.owning_agent})")
    click.echo(f"Spec:       kind={spec.kind} match={spec.match} set={spec.set}")

    register_remediation_handlers()
    if get_remediation_handler(report.owning_agent) is None:
        raise click.ClickException(
            f"No remediation handler registered for '{report.owning_agent}'."
        )

    if not yes:
        click.confirm("Delegate this remediation (performs a Qdrant write)?", abort=True)

    # Reports live under <vault>/diagnostics/<file>, so the grandparent is the vault;
    # delegate_remediation rewrites the same file at each status transition.
    vault = report_path.parent.parent
    result = asyncio.run(delegate_remediation(report, vault=vault))

    detail = result.evidence.get("remediation", "")
    click.echo(f"\nStatus: {result.status}")
    if detail:
        click.echo(detail)


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
