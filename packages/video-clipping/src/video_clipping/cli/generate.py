"""`clip generate <plan>` — Stages 2–6 on a draft plan.

Preflight (before any paid call fires):
- Refuse if `plan.cost_estimate.projected_usd > --max-usd`.
- Ask for confirmation (unless `--yes`) showing projected vs cap, candidate
  count, and expected clip-count range.
"""

from __future__ import annotations

import asyncio
from math import ceil, floor
from pathlib import Path

import click

from video_clipping.constants import (
    MAX_USD_DEFAULT,
    SIMILARITY_THRESHOLD,
    WHISPER_MODEL_CHOICES,
    WHISPER_MODEL_DEFAULT,
)


def _expected_clip_range(run) -> tuple[int, int]:
    """Rough sanity range: max_total_output_min / target window bounds."""
    lo, hi = run.spec.target_clip_length_sec
    total_sec = run.spec.max_total_output_min * 60.0
    if hi <= 0 or lo <= 0:
        return (0, 0)
    max_clips = int(floor(total_sec / lo)) if lo > 0 else 0
    min_clips = int(ceil(total_sec / hi)) if hi > 0 else 0
    return (min(min_clips, max_clips), max(min_clips, max_clips))


@click.command("generate")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--max-usd",
    type=float,
    default=MAX_USD_DEFAULT,
    show_default=True,
    help="Per-invocation cost cap. Preflight refusal if the plan's projected_usd exceeds this.",
)
@click.option(
    "--whisper-model",
    type=click.Choice(list(WHISPER_MODEL_CHOICES)),
    default=WHISPER_MODEL_DEFAULT,
    show_default=True,
    help="faster-whisper model. Downloaded on first use.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Skip Whisper / vision / decision / embedding calls; cut every segment as-is.",
)
@click.option(
    "--cross-run-dedupe/--no-cross-run-dedupe",
    default=False,
    show_default=True,
    help="Also drop segments near-duplicating any accepted clip from prior runs.",
)
@click.option(
    "--cross-run-threshold",
    type=float,
    default=SIMILARITY_THRESHOLD,
    show_default=True,
    help="Cosine threshold for cross-run duplicate. Only used when --cross-run-dedupe.",
)
@click.option(
    "--use-lessons/--no-lessons",
    default=True,
    show_default=True,
    help="Surface prior auto-accrued lessons into each decide-stage prompt.",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
def generate_command(
    plan: Path,
    max_usd: float,
    whisper_model: str,
    dry_run: bool,
    cross_run_dedupe: bool,
    cross_run_threshold: float,
    use_lessons: bool,
    yes: bool,
) -> None:
    """Run stages 2–6 on a draft plan (transcribe → vision → decide → dedupe → cut)."""
    from video_clipping.generate import generate_sync
    from video_clipping.plan import load_plan

    try:
        run = load_plan(plan)
    except Exception as exc:
        raise click.ClickException(f"failed to load plan {plan}: {exc}") from exc

    projected = run.cost_estimate.projected_usd
    if not dry_run and projected > max_usd:
        raise click.ClickException(
            f"projected cost ${projected:.4f} exceeds --max-usd ${max_usd:.4f}. "
            f"Raise the cap with --max-usd or shrink the plan."
        )

    lo, hi = _expected_clip_range(run)
    click.echo("── clip generate ──")
    click.echo(f"  plan:              {plan}")
    click.echo(f"  video:             {run.spec.video}")
    click.echo(f"  candidates:        {len(run.segments)}")
    click.echo(f"  expected clips:    {lo}–{hi}")
    click.echo(f"  projected cost:    ${projected:.4f} (max ${max_usd:.4f})")
    click.echo(f"  whisper model:     {whisper_model}")
    if dry_run:
        click.echo("  DRY RUN — no paid calls; cutting every segment as-is.")

    if not yes:
        confirmed = click.confirm(
            f"Spend up to ${max_usd:.2f} on this run?" if not dry_run else "Proceed?",
            abort=True,
        )
        if not confirmed:  # confirm(abort=True) raises Abort; this is belt+braces.
            raise click.Abort()

    try:
        result = asyncio.run(
            generate_sync(
                run=run,
                plan_path=plan,
                max_usd=max_usd,
                whisper_model=whisper_model,
                dry_run=dry_run,
                cross_run_dedupe=cross_run_dedupe,
                cross_run_threshold=cross_run_threshold,
                use_lessons=use_lessons,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("")
    click.echo(f"  status:            {result.status}")
    click.echo(f"  qdrant memory:     {_qdrant_summary(result, dry_run)}")
    click.echo(f"  actual cost:       ${result.actual_cost_usd or 0.0:.4f}")
    click.echo(f"  clips written:     {len(result.clip_paths)}")
    if result.halted_reason:
        click.echo(f"  halted_reason:     {result.halted_reason}", err=True)
    click.echo(f"  run manifest:      {plan.parent / 'run.json'}")


def _qdrant_summary(run, dry_run: bool) -> str:
    """One-line summary of memory-persistence outcome for the CLI end-of-run block.

    Kept honest so `status: completed` isn't the whole story — a run that produced
    clips but couldn't write to Qdrant is only partially done from a memory
    standpoint, and this line surfaces that.
    """
    if dry_run:
        return "n/a (dry-run)"
    if run.status == "failed":
        return "not attempted (run failed)"
    if not run.accepted_segment_ids:
        return "nothing to persist (no accepted clips)"
    if run.qdrant_deviation:
        return (
            "⚠  DEVIATED — writes failed; re-run to persist "
            "(start with `docker compose -f infrastructure/docker-compose.yml up -d`)"
        )
    lesson_count = len(run.lessons_recorded)
    seg_count = len(run.accepted_segment_ids)
    lesson_part = f", {lesson_count} lesson{'s' if lesson_count != 1 else ''}" if lesson_count else ""
    return f"persisted (run + {seg_count} segment{'s' if seg_count != 1 else ''}{lesson_part})"
