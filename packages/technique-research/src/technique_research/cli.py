"""technique-research CLI.

Usage:
    technique-research identify "<goal>" [--image <path>]... [--url <video-url>] \
        [--ref <report.md>] [--scope editing|generation|both] [-o report.md] \
        [--plan-only] [--max-cost N] [-y]
    technique-research recall "<query>" [--limit N]
"""
from __future__ import annotations

from pathlib import Path

import click

from technique_research.agent import identify_sync, recall_sync
from technique_research.constants import DEFAULT_BUDGET
from technique_research.models import CheckOutcome, IdentificationInput, TechniqueDomain


@click.group()
def cli() -> None:
    """Technique research agent — goal → prioritized techniques, curated."""


def _validate_output(ctx, param, value):
    """Fail-fast validation of -o at PARSE time, before any identification, gate,
    or paid delegation runs — so a bad output path can never cost a run.

    An existing directory is accepted (the report's default filename is written
    into it). Otherwise the parent must exist or be creatable; if not, error now.
    """
    if value is None:
        return None
    path = Path(value)
    if path.is_dir():
        return path  # directory → default filename written into it (see _write_report)
    parent = path.parent if str(path.parent) else Path(".")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise click.BadParameter(
            f"cannot write a report at {path} — its directory is unusable: {exc}"
        ) from exc
    return path


def _interactive_gate(
    domains: list[TechniqueDomain], outcomes: list[CheckOutcome]
) -> set[str]:
    """The identify→delegate gate: show the technique list + delegation plan and
    let the director prune per-domain. Returns the approved delegate-domain names.
    Declining all is NOT an abort — the run curates from existing knowledge only.
    """
    decision_by_name = {o.domain_name: o.decision for o in outcomes}
    score_by_name = {o.domain_name: o for o in outcomes}

    click.echo("\n── Identified techniques ────────────────────────────")
    for d in domains:
        decision = decision_by_name.get(d.name, "delegate")
        o = score_by_name.get(d.name)
        scores = (
            f"own={o.technique_outputs_score:.2f} tut={o.tutorial_score:.2f} uk={o.user_knowledge_score:.2f}"
            if o else ""
        )
        tag = "KNOWN" if decision == "local" else "GAP → would delegate"
        click.echo(f"  [{d.priority}] {d.name}  ({tag})")
        click.echo(f"        why: {d.why_it_matters}")
        if scores:
            click.echo(f"        check: {scores}")

    candidates = [d for d in domains if decision_by_name.get(d.name) == "delegate"]
    if not candidates:
        click.echo("\nNo gaps — everything is already known. Curating from existing knowledge.")
        return set()

    est = len(candidates) * 2.00
    click.echo(
        f"\n{len(candidates)} gap(s) would each delegate to tutorial-research "
        f"(est. up to ~${est:.2f} total)."
    )
    approved: set[str] = set()
    for d in candidates:
        if click.confirm(f"  Delegate gathering for '{d.name}'?", default=True):
            approved.add(d.name)
    if not approved:
        click.echo("Declined all — curating from existing knowledge only.")
    return approved


@cli.command()
@click.argument("goal")
@click.option("--image", "images", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Reference image(s) of the look. Repeatable.")
@click.option("--url", default=None, help="Reference video URL (yt-dlp metadata only).")
@click.option("--ref", "ref_report", default=None, type=click.Path(path_type=Path),
              help="A prior TechniqueReport to anchor on ('like that project, but…').")
@click.option("--scope", type=click.Choice(["editing", "generation", "both"]), default=None,
              help="Override scope inference.")
@click.option("--domain", default=None, help="Video type/domain (AMV, game review, …).")
@click.option("-o", "--output", "output", default=None, type=click.Path(path_type=Path),
              callback=_validate_output,
              help="Where to write the TechniqueReport markdown (a directory writes the default filename into it).")
@click.option("--plan-only", is_flag=True, default=False,
              help="Stop at the gate — preview only, no delegation, no writes.")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD.")
@click.option("-y", "--yes", is_flag=True, default=False,
              help="Skip the interactive gate (auto-approve all gaps).")
def identify(
    goal: str, images: tuple[Path, ...], url: str | None, ref_report: Path | None,
    scope: str | None, domain: str | None, output: Path | None,
    plan_only: bool, max_cost: float | None, yes: bool,
) -> None:
    """Identify the techniques a creative goal needs, check what's known, and curate."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )
    inp = IdentificationInput(
        goal=goal, images=list(images), url=url, ref_report=ref_report,
        scope=scope, domain=domain,
    )
    approval = None if (yes or plan_only) else _interactive_gate

    result = identify_sync(
        inp, budget=budget, approval=approval, plan_only=plan_only, output_path=output,
    )

    click.echo(f"\nStatus:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")
    click.echo(f"Scope:     {result.report.scope}")
    click.echo(f"Findings:  {len(result.report.techniques)}")
    if result.report_path:
        click.echo(f"Report:    {result.report_path}")
    if result.report_run_path:
        click.echo(f"Run report: {result.report_run_path}")

    for i, t in enumerate(result.report.techniques, 1):
        click.echo(f"\n── {i}. {t.technique} ─────────────────────────")
        if t.why_it_matters:
            click.echo(f"  why:   {t.why_it_matters}")
        if t.application_notes:
            click.echo(f"  apply: {t.application_notes}")
        if t.upgrade_flag:
            click.echo(f"  ⬆ paid/Studio: {t.upgrade_flag}")


@cli.command()
@click.argument("query")
@click.option("--limit", type=int, default=8, show_default=True)
def recall(query: str, limit: int) -> None:
    """Retrieve prior technique findings semantically."""
    results = recall_sync(query, limit=limit)
    if not results:
        click.echo(f"No findings for: {query}")
        return
    for score, f in results:
        click.echo(f"\n[{score:.3f}] {f.technique}")
        click.echo(f"  {f.description}")
        if f.why_it_matters:
            click.echo(f"  why: {f.why_it_matters}")
        if f.source_refs:
            click.echo(f"  refs: {', '.join(f.source_refs)}")


if __name__ == "__main__":
    cli()
