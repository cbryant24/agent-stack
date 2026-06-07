"""concept-script CLI.

Usage:
    concept-script draft --seeds seeds.md [--ref prior-script.md] [-o script.md]
    concept-script draft "inline seed text" [-o script.md]
    concept-script shape transcript.txt [-o script.md]

Both verbs emit a single editable script.md that `voiceover-direction direct`
consumes unchanged.
"""
from __future__ import annotations

from pathlib import Path

import click

from agent_runtime import BudgetEnvelope

from concept_script.agent import draft_sync, shape_sync
from concept_script.constants import DEFAULT_BUDGET
from concept_script.models import ConceptResult


@click.group()
def cli() -> None:
    """Concept & Script agent — turn seeds or a transcript into an editable script.md."""


def _budget(max_cost: float | None) -> BudgetEnvelope:
    return BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )


def _report(result: ConceptResult) -> None:
    click.echo(f"Status:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")
    if result.script_path:
        click.echo(f"Script:    {result.script_path}")
    click.echo(f"\nLogline: {result.brief.logline}")
    click.echo(f"Sections: {len(result.brief.sections)}")
    for s in result.brief.sections:
        click.echo(f"  # {s.heading}")
    if result.brief.cut_trailer:
        click.echo("\nDirector-note cuts applied:")
        for c in result.brief.cut_trailer:
            click.echo(f"  - {c}")
    click.echo(
        "\n(Edit the file you own, then: voiceover-direction direct "
        f"{result.script_path or 'script.md'})"
    )


# ── draft (generative) ──────────────────────────────────────────────────────

@cli.command()
@click.argument("seeds_text", required=False)
@click.option("--seeds", "-s", "seeds_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Path to a seeds file (theme, mood, duration, references).")
@click.option("--ref", "-r", "ref_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Optional prior-script.md to use as a stylistic reference.")
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Where to write the script (default: ./script.md).")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD.")
@click.option("--dry-run", is_flag=True, default=False, help="Plan only; no LLM call, no file written.")
def draft(
    seeds_text: str | None,
    seeds_file: Path | None,
    ref_file: Path | None,
    output: Path | None,
    max_cost: float | None,
    dry_run: bool,
) -> None:
    """Generate an editable script.md from sparse creative seeds."""
    if seeds_file is not None:
        seeds = seeds_file.read_text(encoding="utf-8")
    elif seeds_text:
        seeds = seeds_text
    else:
        raise click.UsageError("Provide seeds inline or via --seeds <file>.")

    prior_script = ref_file.read_text(encoding="utf-8") if ref_file else None

    result = draft_sync(
        seeds,
        prior_script=prior_script,
        budget=_budget(max_cost),
        output=output,
        dry_run=dry_run,
    )
    _report(result)


# ── shape (curation) ────────────────────────────────────────────────────────

@cli.command()
@click.argument("transcript", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Where to write the script (default: ./script.md).")
@click.option("--clean", is_flag=True, default=False,
              help="Resolve self-corrections into clean final prose "
                   "(default: preserve them verbatim as content).")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD.")
@click.option("--dry-run", is_flag=True, default=False, help="Plan only; no LLM call, no file written.")
def shape(
    transcript: Path,
    output: Path | None,
    clean: bool,
    max_cost: float | None,
    dry_run: bool,
) -> None:
    """Shape a verbatim dictation TRANSCRIPT into an editable script.md.

    By default, natural self-corrections are preserved verbatim as content. Pass
    --clean to resolve them into final prose instead.
    """
    text = transcript.read_text(encoding="utf-8")
    result = shape_sync(
        text,
        clean=clean,
        budget=_budget(max_cost),
        output=output,
        dry_run=dry_run,
    )
    _report(result)
