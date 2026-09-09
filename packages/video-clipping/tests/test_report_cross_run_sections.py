"""Phase-2 report sections: cross-run drops, related prior clips, lessons."""

from __future__ import annotations

import asyncio
from pathlib import Path


from agent_runtime import BudgetEnvelope, BudgetTracker
from video_clipping.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_SEGMENT,
)
from video_clipping.models import (
    ClipDecision,
    CostEstimate,
    PrepassMetrics,
    Run,
    Segment,
    Spec,
)
from video_clipping.plan import save_run
from video_clipping.report import render_run_report_from_dir
from video_clipping.store import VideoClippingStore, _lesson_point_id

from tests.fakes import FakeMemoryStore, _FakePoint, _pseudo_vector


def _synthetic_run(tmp_path: Path) -> tuple[Run, Path]:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video, location="loc", event_type="hike",
        target_clip_length_sec=(1.0, 8.0), max_total_output_min=1.0,
        content_wanted=["scenery"], exclude_when=["theme_mismatch"],
    )
    seg1 = Segment(segment_id="s1", start=0.0, end=3.0, duration=3.0)
    d1 = ClipDecision(
        segment_id="s1", action="include", refined_start=0.0, refined_end=3.0,
        theme_match=0.9, confidence=0.9, one_line_summary="scene one panorama",
    )
    run = Run(
        spec=spec, video_sha256="deadbeef",
        prepass_metrics=PrepassMetrics(
            resolution=(320, 240), fps=15.0, bitrate_kbps=100, duration_sec=9.0
        ),
        segments=[seg1],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=1, projected_input_tokens=100, projected_usd=0.05,
            pricing_model_id="claude-sonnet-4-6", pricing_input_usd_per_mtok=3.0,
        ),
        decisions=[d1], accepted_segment_ids=["s1"],
        clip_paths=[Path("/tmp/01_scene.mp4")],
        actual_cost_usd=0.02, status="completed",
        cross_run_hits=[{
            "segment_id": "s0",
            "one_line_summary": "dropped one",
            "prior_run_id": "prior-run-A",
            "prior_segment_id": "ps0",
            "prior_one_line": "matched prior",
            "score": 0.95,
        }],
    )
    run_dir = tmp_path / "outputs" / run.run_id
    save_run(run, run_dir)
    return run, run_dir


def _bootstrap_trace(run: Run) -> None:
    envelope = BudgetEnvelope(max_items=1, max_cost_usd=1.0, max_wall_time_sec=10)

    async def _run_it() -> None:
        async with BudgetTracker(envelope, "video-clipping", run_id=run.run_id):
            pass

    asyncio.run(_run_it())


def test_report_renders_cross_run_related_and_lessons_when_qdrant_available(
    tmp_path: Path,
) -> None:
    run, run_dir = _synthetic_run(tmp_path)
    _bootstrap_trace(run)

    fake = FakeMemoryStore()
    # Seed a prior segment so Related-prior-clips has something to show.
    fake.collections.setdefault(COLLECTION_NAME, {})["prior-seg-1"] = _FakePoint(
        id="prior-seg-1",
        vector=_pseudo_vector("scene one panorama"),
        payload={
            "memory_type": MEMORY_TYPE_SEGMENT,
            "run_id": "prior-run-1",
            "segment_id": "prior-seg-1",
            "decision": {"one_line_summary": "similar prior scene"},
        },
    )
    # Seed a lesson keyed by our lesson uuid5-of-lesson_id.
    lesson_id = "lesson-abc"
    fake.collections[COLLECTION_NAME][_lesson_point_id(lesson_id)] = _FakePoint(
        id=_lesson_point_id(lesson_id),
        vector=_pseudo_vector("lesson body"),
        payload={
            "memory_type": MEMORY_TYPE_LESSON,
            "human_summary": "hike runs cluster on theme_mismatch",
            "pattern_type": "exclude_cluster",
        },
    )
    run.lessons_recorded = [lesson_id]
    save_run(run, run_dir)

    store = VideoClippingStore(fake)
    report_path = asyncio.run(render_run_report_from_dir(run_dir, store=store))
    body = report_path.read_text(encoding="utf-8")

    assert "## Cross-run dedupe" in body
    assert "matched prior" in body
    assert "prior-r" in body  # first-8 of prior_run_id

    assert "## Related prior clips" in body
    assert "similar prior scene" in body

    assert "## Lessons recorded this run" in body
    assert "hike runs cluster on theme_mismatch" in body


def test_report_degrades_gracefully_when_qdrant_unavailable(tmp_path: Path) -> None:
    run, run_dir = _synthetic_run(tmp_path)
    _bootstrap_trace(run)

    run.lessons_recorded = ["lesson-abc"]
    save_run(run, run_dir)

    fake = FakeMemoryStore(raise_on_query=True)
    store = VideoClippingStore(fake)

    report_path = asyncio.run(render_run_report_from_dir(run_dir, store=store))
    body = report_path.read_text(encoding="utf-8")

    # Cross-run section still renders from run.cross_run_hits (no Qdrant needed).
    assert "## Cross-run dedupe" in body
    # Related-prior-clips + Lessons show unavailable notice.
    assert "## Related prior clips" in body
    assert "(Qdrant unavailable)" in body
