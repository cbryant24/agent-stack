"""Preflight cost cap: refuse to start when projected_usd > --max-usd."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from video_clipping.cli import cli
from video_clipping.models import CostEstimate, PrepassMetrics, Run, Segment, Spec
from video_clipping.plan import PLAN_FILENAME


def _synthetic_run(tmp_path: Path, projected_usd: float) -> Path:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video,
        location="somewhere",
        event_type="hike",
        target_clip_length_sec=(15.0, 60.0),
        max_total_output_min=5.0,
    )
    run = Run(
        spec=spec,
        video_sha256="deadbeef",
        prepass_metrics=PrepassMetrics(
            resolution=(320, 240), fps=15.0, bitrate_kbps=100, duration_sec=9.0
        ),
        segments=[Segment(start=0.0, end=3.0, duration=3.0)],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=1,
            projected_input_tokens=100,
            projected_usd=projected_usd,
            pricing_model_id="claude-sonnet-4-6",
            pricing_input_usd_per_mtok=3.0,
        ),
    )
    run_dir = tmp_path / "outputs" / run.run_id
    run_dir.mkdir(parents=True)
    plan = run_dir / PLAN_FILENAME
    plan.write_text(json.dumps(run.to_payload(), indent=2, default=str))
    return plan


def test_preflight_refuses_over_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_path = _synthetic_run(tmp_path, projected_usd=10.0)

    # If any paid boundary is reached, this test has a real bug — cap should stop us first.
    def boom(*_a, **_kw):
        raise AssertionError("paid boundary reached despite preflight refusal")

    monkeypatch.setattr("video_clipping.audio.transcribe._load_model", boom)
    monkeypatch.setattr("video_clipping.generate.get_provider", boom)
    monkeypatch.setattr(
        "video_clipping.similarity.embed.get_embedding_client", boom
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(plan_path), "--max-usd", "1.00", "--yes"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    combined = result.output + (result.stderr or "")
    assert "10.0" in combined
    assert "1.0" in combined
    # run.json must NOT have been written.
    assert not (plan_path.parent / "run.json").exists()


def test_preflight_allows_at_or_under_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan whose projected_usd == cap should not be refused by preflight (dry-run so we
    don't need to stub whisper/provider/voyage for this narrow assertion)."""
    plan_path = _synthetic_run(tmp_path, projected_usd=1.00)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(plan_path), "--max-usd", "1.00", "--yes", "--dry-run"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stderr
