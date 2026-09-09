"""`clip report <run-id>` — render a rich Markdown report for a completed run."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from agent_runtime import get_config

from video_clipping.constants import AGENT_SUBDIR
from video_clipping.plan import RUN_FILENAME


@click.command("report")
@click.argument("run_id", type=str)
@click.option(
    "--outputs-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override the outputs root (default: <agent_data_dir>/video-clipping/outputs).",
)
def report_command(run_id: str, outputs_root: Path | None) -> None:
    """Render the run summary from run.json + trace.jsonl."""
    from video_clipping.report import render_run_report_from_dir

    if outputs_root is None:
        outputs_root = get_config().agent_data_dir / AGENT_SUBDIR / "outputs"
    run_dir = Path(outputs_root) / run_id
    if not (run_dir / RUN_FILENAME).exists():
        raise click.ClickException(
            f"no {RUN_FILENAME} under {run_dir} — did `clip generate` complete for this run_id?"
        )
    try:
        report_path = asyncio.run(render_run_report_from_dir(run_dir))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(report_path))
