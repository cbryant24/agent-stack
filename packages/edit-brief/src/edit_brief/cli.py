"""edit-brief CLI.

Usage:
    edit-brief draft SCRIPT.md [--footage DIR] [--music FILE] [--bpm N] \
        [--gap SECONDS] [-o brief.md] [--project-id ID] [--max-cost N] [--dry-run]

`--dry-run` is the one free op: discovery + the computed grids only — it prints
what was found and what is missing per input (the degradation picture) before
anything is spent.
"""
from __future__ import annotations

from pathlib import Path

import click

from edit_brief.agent import draft_sync
from edit_brief.constants import DEFAULT_BUDGET, DEFAULT_GAP_SEC
from edit_brief.models import BriefResult


@click.group()
def cli() -> None:
    """Edit brief agent — script + artifacts → a time-ordered DaVinci checklist."""


def _validate_output(ctx, param, value):
    """Fail-fast -o validation at PARSE time, before any discovery or spend."""
    if value is None:
        return None
    path = Path(value)
    if path.is_dir():
        return path
    parent = path.parent if str(path.parent) else Path(".")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise click.BadParameter(
            f"cannot write a brief at {path} — its directory is unusable: {exc}"
        ) from exc
    return path


@cli.command()
@click.argument("script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--footage", default=None, type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Director footage directory — scanned + ffprobed (filename + duration).")
@click.option("--music", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Music track file — ffprobed for duration (the collection logs no file).")
@click.option("--bpm", type=int, default=None,
              help="Track BPM for the beat grid (overrides any matched proposal).")
@click.option("--gap", type=float, default=DEFAULT_GAP_SEC, show_default=True,
              help="Breathing gap inserted between sections, seconds.")
@click.option("-o", "--output", "output", default=None, type=click.Path(path_type=Path),
              callback=_validate_output,
              help="Where to write edit-brief.md (default: next to the script).")
@click.option("--project-id", default=None, help="Project id (default: the script's filename stem).")
@click.option("--max-cost", type=float, default=None, help="Override max cost USD for the run.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Discovery + computed grids only; no LLM call, no file written.")
def draft(
    script: Path,
    footage: Path | None,
    music: Path | None,
    bpm: int | None,
    gap: float,
    output: Path | None,
    project_id: str | None,
    max_cost: float | None,
    dry_run: bool,
) -> None:
    """Draft the edit brief for SCRIPT.md."""
    from agent_runtime import BudgetEnvelope

    budget = BudgetEnvelope(
        max_items=DEFAULT_BUDGET.max_items,
        max_depth=DEFAULT_BUDGET.max_depth,
        max_cost_usd=max_cost if max_cost is not None else DEFAULT_BUDGET.max_cost_usd,
        max_wall_time_sec=DEFAULT_BUDGET.max_wall_time_sec,
    )

    result = draft_sync(
        script,
        footage=str(footage) if footage else None,
        music=str(music) if music else None,
        bpm=bpm,
        gap=gap,
        project_id=project_id,
        output_path=output,
        budget=budget,
        dry_run=dry_run,
    )

    _print_discovery(result)

    if dry_run:
        click.echo("\n(dry run — no brief written, nothing spent)")
        return

    click.echo(f"\nStatus:    {result.status}")
    click.echo(f"Run ID:    {result.run_id}")
    click.echo(f"Cost:      ${result.cost_usd:.4f}")
    click.echo(f"Wall time: {result.wall_time_sec:.1f}s")
    if result.brief_path:
        click.echo(f"Brief:     {result.brief_path}")
    if result.report_run_path:
        click.echo(f"Run report: {result.report_run_path}")


def _print_discovery(result: BriefResult) -> None:
    b = result.brief
    inputs = b.provenance
    click.echo(f"\n── Discovery: {inputs.project_id} ───────────────────────")
    n_vo = sum(1 for t in inputs.vo_takes if t.duration_sec is not None)
    click.echo(f"  VO takes:  {n_vo}/{len(b.timeline)} sections with measured durations")
    m = inputs.music
    click.echo(f"  Music:     {m.file or '(none)'}"
               + (f"  duration={m.duration_sec:.1f}s" if m.duration_sec else ""))
    click.echo(f"  BPM:       {m.bpm if m.bpm is not None else '(none)'} ({m.bpm_source})"
               + (f'  ← "{m.matched_title}"' if m.bpm_source == "matched" and m.matched_title else ""))
    click.echo(f"  Assets:    {len(inputs.assets)}")

    if b.notations:
        click.echo("\n  Missing inputs / notes:")
        for n in b.notations:
            click.echo(f"    - {n}")


if __name__ == "__main__":
    cli()
