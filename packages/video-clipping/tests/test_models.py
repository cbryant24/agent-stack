from __future__ import annotations

from pathlib import Path

import pytest

from video_clipping.models import (
    ClipDecision,
    CostEstimate,
    Lesson,
    PrepassMetrics,
    Run,
    Segment,
    Spec,
)


def _spec() -> Spec:
    return Spec(
        video=Path("/tmp/x.mp4"),
        location="loc",
        event_type="hike",
        target_clip_length_sec=(15.0, 60.0),
        max_total_output_min=5,
        content_wanted=["a", "b"],
        exclude_when=["low_video_quality", "theme_mismatch"],
    )


def test_spec_from_yaml_roundtrip(tmp_path: Path) -> None:
    yaml_text = (
        "video: /tmp/x.mp4\n"
        "location: loc\n"
        "event_type: hike\n"
        "target_clip_length_sec: [15, 60]\n"
        "max_total_output_min: 5\n"
        "content_wanted:\n  - a\n  - b\n"
        "exclude_when:\n  - low_video_quality\n"
        "tone_notes: null\n"
    )
    p = tmp_path / "spec.yaml"
    p.write_text(yaml_text)
    spec = Spec.from_yaml(p)
    assert spec.target_clip_length_sec == (15.0, 60.0)
    assert spec.location == "loc"
    assert spec.exclude_when == ["low_video_quality"]


def test_spec_rejects_bad_window() -> None:
    with pytest.raises(ValueError):
        Spec(
            video=Path("/tmp/x.mp4"),
            location="l",
            event_type="e",
            target_clip_length_sec=(60.0, 15.0),  # inverted
            max_total_output_min=5,
        )


def test_segment_roundtrip() -> None:
    seg = Segment(
        start=1.0, end=5.0, duration=4.0,
        mean_loudness_lufs=-22.5,
        detector_provenance=["pyscenedetect", "scdet"],
        length_status="near_miss_short",
    )
    payload = seg.to_payload()
    assert payload["memory_type"] == "segment"
    restored = Segment.from_payload(payload)
    assert restored.start == 1.0
    assert restored.detector_provenance == ["pyscenedetect", "scdet"]
    assert restored.length_status == "near_miss_short"


def test_lesson_roundtrip() -> None:
    lesson = Lesson(statement="silence-heavy segments make bad clips", valence="negative")
    payload = lesson.to_payload()
    assert payload["memory_type"] == "lesson"
    restored = Lesson.from_payload(payload)
    assert restored.statement == "silence-heavy segments make bad clips"


def test_run_roundtrip() -> None:
    run = Run(
        spec=_spec(),
        video_sha256="deadbeef",
        prepass_metrics=PrepassMetrics(resolution=(320, 240), fps=15.0, bitrate_kbps=200, duration_sec=9.0),
        segments=[],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=0,
            projected_input_tokens=0,
            projected_usd=0.0,
            pricing_model_id="claude-sonnet-4-6",
            pricing_input_usd_per_mtok=3.0,
        ),
    )
    payload = run.to_payload()
    assert payload["memory_type"] == "run"
    restored = Run.from_payload(payload)
    assert restored.spec.location == "loc"
    assert restored.video_sha256 == "deadbeef"


def test_clip_decision_bounds() -> None:
    decision = ClipDecision(
        segment_id="seg-1",
        action="include",
        refined_start=1.0,
        refined_end=5.0,
        theme_match=0.9,
        confidence=0.8,
        one_line_summary="landscape pan",
    )
    assert decision.action == "include"
    assert decision.segment_id == "seg-1"
    with pytest.raises(ValueError):
        ClipDecision(
            segment_id="seg-2",
            action="include", refined_start=0, refined_end=1,
            theme_match=1.5, confidence=0.5, one_line_summary="x",
        )


def test_clip_decision_roundtrip() -> None:
    decision = ClipDecision(
        segment_id="seg-9",
        action="trim",
        refined_start=10.0,
        refined_end=30.0,
        theme_match=0.6,
        confidence=0.7,
        one_line_summary="summit ridge pan",
    )
    restored = ClipDecision.from_payload(decision.to_payload())
    assert restored == decision


def test_clip_decision_error_reason() -> None:
    d = ClipDecision(
        segment_id="seg-x",
        action="exclude",
        refined_start=0.0,
        refined_end=1.0,
        exclude_reason="error",
        theme_match=0.0,
        confidence=0.0,
        one_line_summary="[error] boom",
    )
    assert d.exclude_reason == "error"
