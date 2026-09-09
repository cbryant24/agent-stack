"""`clip report <run-id>` reads run.json + trace.jsonl and writes a Markdown report."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_runtime import BudgetEnvelope, BudgetTracker
from video_clipping.cli import cli
from video_clipping.models import (
    ClipDecision,
    CostEstimate,
    PrepassMetrics,
    Run,
    Segment,
    Spec,
)
from video_clipping.plan import save_run


def _synthetic_run(tmp_path: Path) -> tuple[Run, Path]:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video, location="loc", event_type="hike",
        target_clip_length_sec=(1.0, 8.0), max_total_output_min=1.0,
        content_wanted=["scenery"], exclude_when=["theme_mismatch"],
    )
    seg1 = Segment(segment_id="s1", start=0.0, end=3.0, duration=3.0)
    seg2 = Segment(segment_id="s2", start=3.0, end=6.0, duration=3.0)
    d1 = ClipDecision(
        segment_id="s1", action="include", refined_start=0.0, refined_end=3.0,
        theme_match=0.9, confidence=0.9, one_line_summary="scene one panorama",
    )
    d2 = ClipDecision(
        segment_id="s2", action="exclude", refined_start=3.0, refined_end=6.0,
        exclude_reason="theme_mismatch",
        theme_match=0.2, confidence=0.8, one_line_summary="parking lot",
    )
    run = Run(
        spec=spec, video_sha256="deadbeef",
        prepass_metrics=PrepassMetrics(
            resolution=(320, 240), fps=15.0, bitrate_kbps=100, duration_sec=9.0
        ),
        segments=[seg1, seg2],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=2, projected_input_tokens=1000,
            projected_usd=0.10,
            pricing_model_id="claude-sonnet-4-6",
            pricing_input_usd_per_mtok=3.0,
        ),
        decisions=[d1, d2],
        accepted_segment_ids=["s1"],
        clip_paths=[Path("/tmp/01_scene-one-panorama.mp4")],
        actual_cost_usd=0.03,
        status="completed",
    )
    run_dir = tmp_path / "outputs" / run.run_id
    save_run(run, run_dir)
    return run, run_dir


def test_clip_report_renders_rich_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, run_dir = _synthetic_run(tmp_path)

    # The shared renderer needs a trace.jsonl. Enter+exit a BudgetTracker briefly
    # to create the run_start / run_end events under the current agent_data_dir.
    envelope = BudgetEnvelope(max_items=1, max_cost_usd=1.0, max_wall_time_sec=10)

    async def _bootstrap() -> None:
        async with BudgetTracker(envelope, "video-clipping", run_id=run.run_id):
            pass

    asyncio.run(_bootstrap())

    outputs_root = tmp_path / "outputs"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["report", run.run_id, "--outputs-root", str(outputs_root)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stderr

    report_path = Path(result.output.strip())
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")

    assert run.run_id in body
    assert "## Cost" in body
    assert "$0.1000" in body
    assert "$0.0300" in body
    assert "## Segments" in body
    assert "scene one panorama" in body
    assert "parking lot" in body
    assert "theme_mismatch" in body
    assert "## Clips" in body
    assert "01_scene-one-panorama.mp4" in body


def test_clip_report_missing_run_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["report", "no-such-run", "--outputs-root", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "no run.json" in (result.output + (result.stderr or ""))
