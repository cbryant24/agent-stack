"""feedback-iteration CLI.

Usage:
    feedback-iteration revise BRIEF.md "feedback text" [--feedback FILE] \
        [--max-cost N] [--dry-run]

`--dry-run` is the one free op: parse + validate the brief (anchors, frontmatter,
version state, snapshot plan) and echo the parsed feedback items — no LLM call,
no writes, nothing spent.
"""
from __future__ import annotations

from pathlib import Path

import click

from feedback_iteration.agent import revise_sync
from feedback_iteration.constants import DEFAULT_BUDGET
from feedback_iteration.models import RevisionResult


@click.group()
def cli() -> None:
    """Feedback & iteration agent — natural-language feedback → a state-preserving brief revision."""


@cli.command()
@click.argument("brief", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("feedback", required=False, default=None)
@click.option("--feedback", "feedback_file", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="A feedback file (session notes) — combined with any inline feedback.")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD for the run.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Parse + validate + echo the feedback; no LLM call, no writes.")
def revise(
    brief: Path,
    feedback: str | None,
    feedback_file: Path | None,
    max_cost: float | None,
    dry_run: bool,
) -> None:
    """Revise BRIEF.md from natural-language feedback."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )

    result = revise_sync(
        brief,
        feedback,
        feedback_file=str(feedback_file) if feedback_file else None,
        max_cost=max_cost,
        dry_run=dry_run,
        budget=budget,
    )

    if dry_run:
        _print_dry_run(result)
        return
    _print_run(result)


def _print_feedback_echo(result: RevisionResult) -> None:
    click.echo(f"\n── Revise: {result.project_id or '(unknown project)'} ───────────────────────")
    click.echo(f"  Brief:    {result.brief_path}")
    click.echo(f"  Sections: {len(result.section_ids)} anchors")
    click.echo(f"  Version:  {result.version_from} → {result.version_to} (planned)")
    click.echo("\n  Feedback items:")
    if result.feedback_items:
        for i, item in enumerate(result.feedback_items):
            click.echo(f"    [{i}] {item}")
    else:
        click.echo("    (none provided)")
    if result.validation_findings:
        click.echo("\n  Validation:")
        for f in result.validation_findings:
            click.echo(f"    - {f}")


def _print_dry_run(result: RevisionResult) -> None:
    _print_feedback_echo(result)
    click.echo(f"\n  Snapshot plan: {result.snapshot_path}")
    click.echo("\n(dry run — parsed + validated, no writes, nothing spent)")


def _print_run(result: RevisionResult) -> None:
    _print_feedback_echo(result)

    if result.applied:
        click.echo("\n  Applied:")
        for a in result.applied:
            click.echo(f"    - {a}")
    if result.unresolved:
        click.echo("\n  Unresolved (unapplied):")
        for u in result.unresolved:
            click.echo(f"    - {u}")
    if result.invalidated_checks:
        click.echo("\n  Invalidated checked steps:")
        for i in result.invalidated_checks:
            click.echo(f"    - {i}")
    if result.lesson_draft_ids:
        click.echo("\n  Lesson drafts proposed (confirm out of band):")
        for d in result.lesson_draft_ids:
            click.echo(f"    - {d}")

    click.echo(f"\nStatus:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")
    click.echo(f"Version:   {result.version_from} → {result.version_to}")
    if result.brief_path:
        click.echo(f"Brief:     {result.brief_path}")
    if result.snapshot_path:
        click.echo(f"Snapshot:  {result.snapshot_path}")
    if result.report_run_path:
        click.echo(f"Run report: {result.report_run_path}")


if __name__ == "__main__":
    cli()
