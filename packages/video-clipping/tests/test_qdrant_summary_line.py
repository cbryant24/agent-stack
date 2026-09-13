"""`clip generate` CLI prints an honest qdrant-memory summary line.

`status: completed` alone hides whether Qdrant writes actually happened. The
summary line makes deviation visible.
"""

from __future__ import annotations

from pathlib import Path

from video_clipping.cli.generate import _qdrant_summary
from video_clipping.models import (
    CostEstimate,
    PrepassMetrics,
    Run,
    Spec,
)


def _run(tmp_path: Path) -> Run:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video, location="loc", event_type="hike",
        target_clip_length_sec=(1.0, 8.0), max_total_output_min=1.0,
        content_wanted=["scenery"], exclude_when=["theme_mismatch"],
    )
    return Run(
        spec=spec, video_sha256="abc",
        prepass_metrics=PrepassMetrics(
            resolution=(320, 240), fps=15.0, bitrate_kbps=100, duration_sec=9.0
        ),
        segments=[],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=0, projected_input_tokens=0, projected_usd=0.0,
            pricing_model_id="claude-sonnet-4-6", pricing_input_usd_per_mtok=3.0,
        ),
    )


def test_dry_run(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "completed"
    assert _qdrant_summary(run, dry_run=True) == "n/a (dry-run)"


def test_failed_run(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "failed"
    assert "not attempted" in _qdrant_summary(run, dry_run=False)


def test_no_accepted_clips(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "completed"
    run.accepted_segment_ids = []
    assert "nothing to persist" in _qdrant_summary(run, dry_run=False)


def test_deviated_surfaces_warning_and_start_hint(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "completed"
    run.accepted_segment_ids = ["s1", "s2"]
    run.qdrant_deviation = True
    summary = _qdrant_summary(run, dry_run=False)
    assert "DEVIATED" in summary
    assert "docker compose" in summary


def test_persisted_reports_segment_and_lesson_counts(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "completed"
    run.accepted_segment_ids = ["s1", "s2", "s3"]
    run.lessons_recorded = ["l1"]
    run.qdrant_deviation = False
    summary = _qdrant_summary(run, dry_run=False)
    assert "persisted" in summary
    assert "3 segments" in summary
    assert "1 lesson" in summary


def test_persisted_no_lessons_hides_lesson_clause(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run.status = "completed"
    run.accepted_segment_ids = ["s1"]
    run.lessons_recorded = []
    summary = _qdrant_summary(run, dry_run=False)
    assert "persisted" in summary
    assert "1 segment" in summary
    assert "lesson" not in summary
