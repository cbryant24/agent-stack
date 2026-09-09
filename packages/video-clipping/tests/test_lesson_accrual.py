"""Auto-accrued lessons from `clip generate` runs.

Two detectors: `exclude_cluster` (>=3 segments sharing an exclude reason) and
`cross_run_repeat` (>=2 cross-run drops matching the same prior run).
"""

from __future__ import annotations

from pathlib import Path

from video_clipping.lesson import accrue_lessons
from video_clipping.models import (
    ClipDecision,
    CostEstimate,
    PrepassMetrics,
    Run,
    Spec,
)
from video_clipping.similarity.cross_run import CrossRunHit


def _make_run(tmp_path: Path) -> Run:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video, location="loc", event_type="hike",
        target_clip_length_sec=(1.0, 8.0), max_total_output_min=1.0,
        content_wanted=["scenery"], exclude_when=["theme_mismatch"],
    )
    return Run(
        spec=spec,
        video_sha256="deadbeefcafebabe",
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


def _excl(seg_id: str, reason: str) -> ClipDecision:
    return ClipDecision(
        segment_id=seg_id, action="exclude", refined_start=0.0, refined_end=1.0,
        exclude_reason=reason, theme_match=0.1, confidence=0.8,
        one_line_summary=f"excluded {seg_id} for {reason}",
    )


def test_exclude_cluster_lesson_at_threshold(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    decisions = [_excl(f"s{i}", "theme_mismatch") for i in range(3)]
    lessons = accrue_lessons(run, decisions, cross_run_hits=[])
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.pattern_type == "exclude_cluster"
    assert lesson.pattern_payload["exclude_reason"] == "theme_mismatch"
    assert lesson.pattern_payload["count"] == 3
    assert lesson.source_run_id == run.run_id
    assert lesson.event_type == "hike"
    assert "theme_mismatch" in (lesson.human_summary or "")


def test_exclude_cluster_below_threshold_no_lesson(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    decisions = [_excl(f"s{i}", "theme_mismatch") for i in range(2)]
    lessons = accrue_lessons(run, decisions, cross_run_hits=[])
    assert lessons == []


def test_exclude_cluster_ignores_suppressed_reasons(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    decisions = [
        *[_excl(f"d{i}", "duplicate_of_previous") for i in range(4)],
        *[_excl(f"r{i}", "duplicate_of_previous_run") for i in range(4)],
        *[_excl(f"e{i}", "error") for i in range(4)],
    ]
    lessons = accrue_lessons(run, decisions, cross_run_hits=[])
    assert lessons == []


def test_cross_run_repeat_lesson_at_threshold(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    hits = [
        CrossRunHit(
            segment_id=f"s{i}", one_line_summary=f"one{i}",
            prior_run_id="prior-run-A", prior_segment_id=f"ps{i}",
            prior_one_line=f"prior{i}", score=0.95,
        )
        for i in range(2)
    ]
    lessons = accrue_lessons(run, decisions=[], cross_run_hits=hits)
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.pattern_type == "cross_run_repeat"
    assert lesson.pattern_payload["prior_run_id"] == "prior-run-A"
    assert lesson.pattern_payload["count"] == 2


def test_cross_run_repeat_below_threshold_no_lesson(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    hits = [
        CrossRunHit(
            segment_id="s0", one_line_summary="x",
            prior_run_id="prior-run-A", prior_segment_id="ps0",
            prior_one_line="prior0", score=0.9,
        )
    ]
    assert accrue_lessons(run, decisions=[], cross_run_hits=hits) == []


def test_cross_run_repeat_separate_prior_runs_no_lesson(tmp_path: Path) -> None:
    """2 hits against two different prior runs → no cluster."""
    run = _make_run(tmp_path)
    hits = [
        CrossRunHit(
            segment_id=f"s{i}", one_line_summary="x",
            prior_run_id=f"prior-run-{c}", prior_segment_id=f"ps{i}",
            prior_one_line=f"prior{i}", score=0.9,
        )
        for i, c in enumerate(["A", "B"])
    ]
    assert accrue_lessons(run, decisions=[], cross_run_hits=hits) == []
