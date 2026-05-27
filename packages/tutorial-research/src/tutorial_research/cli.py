from __future__ import annotations

import click

from tutorial_research.agent import research_sync
from tutorial_research.constants import DEFAULT_BUDGET


@click.command()
@click.argument("request")
@click.option(
    "--type",
    "request_type",
    type=click.Choice(["research", "ingest", "retrieve"]),
    default=None,
    help="Override request type classification.",
)
@click.option(
    "--synthesize/--no-synthesize",
    "synthesize",
    default=None,
    help="Force synthesis on or off (default: on for research, off for others).",
)
@click.option(
    "--max-items",
    type=int,
    default=None,
    help=f"Max videos to ingest (default: {DEFAULT_BUDGET.max_items}).",
)
@click.option(
    "--max-cost",
    type=float,
    default=None,
    help=f"Max cost in USD (default: {DEFAULT_BUDGET.max_cost_usd}).",
)
@click.option(
    "--plan-only",
    is_flag=True,
    default=False,
    help="Build the ingestion plan and exit without processing videos.",
)
@click.option(
    "--collection",
    default="tutorial_research",
    show_default=True,
    help="Qdrant collection name.",
)
def cli(
    request: str,
    request_type: str | None,
    synthesize: bool | None,
    max_items: int | None,
    max_cost: float | None,
    plan_only: bool,
    collection: str,
) -> None:
    """Research, ingest, or retrieve YouTube tutorials."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=max_items if max_items is not None else DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )

    result = research_sync(
        request,
        budget=budget,
        request_type=request_type,  # type: ignore[arg-type]
        synthesize=synthesize,
        dry_run=plan_only,
        collection=collection,
    )

    click.echo(f"Status:       {result.status}")
    click.echo(f"Type:         {result.request_type}")
    click.echo(f"Run ID:       {result.run_id}")
    click.echo(f"Cost:         ${result.cost_usd:.4f}")
    click.echo(f"Items:        {result.items_processed}")
    click.echo(f"Wall time:    {result.wall_time_sec:.1f}s")

    if result.plan:
        click.echo(f"\nPlan: {result.plan.estimated_items} video(s) selected")
        for c in result.plan.selected:
            click.echo(f"  [{c.score}/5] {c.title[:60]} — {c.rationale[:80]}")

    if result.ingested:
        click.echo(f"\nIngested {len(result.ingested)} video(s):")
        for v in result.ingested:
            click.echo(f"  {v.source_id}")

    if result.synthesis:
        click.echo(f"\nSynthesis:\n{result.synthesis}")

    if result.report_path:
        click.echo(f"\nReport: {result.report_path}")
