"""`clip draft <video> --spec spec.yaml` — Phase 0 pre-pass."""

from __future__ import annotations

from pathlib import Path

import click

from video_clipping.draft import draft_sync


@click.command("draft")
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--spec",
    "spec_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the spec.yaml describing what to clip.",
)
@click.option(
    "--outputs-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override the outputs root (default: <agent_data_dir>/video-clipping/outputs).",
)
def draft_command(video: Path, spec_path: Path, outputs_root: Path | None) -> None:
    """Run the free pre-pass and write plan.json (no paid calls)."""
    try:
        result = draft_sync(video=video, spec_path=spec_path, outputs_root=outputs_root)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    run = result.run
    click.echo(f"── clip draft ── run {run.run_id}")
    click.echo(f"  video           : {run.spec.video}")
    click.echo(
        f"  resolution      : {run.prepass_metrics.resolution[0]}x{run.prepass_metrics.resolution[1]}"
        f" @ {run.prepass_metrics.fps:.2f} fps"
    )
    click.echo(f"  duration        : {run.prepass_metrics.duration_sec:.2f} s")
    click.echo(
        f"  scenes          : pyscenedetect={len(run.scene_detection['pyscenedetect'])}"
        f"  scdet={len(run.scene_detection['scdet'])}"
        f"  union={len(run.scene_detection['union'])}"
    )
    click.echo(f"  candidate segs  : {len(run.segments)}")
    for seg in run.segments:
        prov = ",".join(seg.detector_provenance) or "-"
        lufs = f"{seg.mean_loudness_lufs:+.1f} LUFS" if seg.mean_loudness_lufs is not None else "n/a"
        flag = "" if seg.length_status == "ok" else f"  [{seg.length_status}]"
        click.echo(
            f"    • {seg.start:7.2f} → {seg.end:7.2f}  ({seg.duration:5.2f}s)"
            f"  loud={lufs:>12}  det={prov}{flag}"
        )
    est = run.cost_estimate
    click.echo(
        f"  projected cost  : ${est.projected_usd:.4f}"
        f"  ({est.frames_to_send} frames, ~{est.projected_input_tokens} in-tokens)"
    )
    click.echo(
        f"  pricing         : {est.pricing_model_id}"
        f"  @ ${est.pricing_input_usd_per_mtok:.2f}/Mtok input"
    )
    click.echo(f"  plan written    : {result.plan_path}")
