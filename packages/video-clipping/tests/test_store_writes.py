"""Qdrant writes: VideoClippingStore upserts run/segment/lesson points.

Verifies deterministic uuid5 point IDs (re-runs upsert instead of duplicating),
payload shape per memory_type, and that payload indices are declared on
ensure_collection.
"""

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
from video_clipping.store import (
    VideoClippingStore,
    _lesson_point_id,
    _run_point_id,
    _segment_point_id,
)

from tests.fakes import FakeMemoryStore


def _run(tmp_path: Path) -> Run:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    spec = Spec(
        video=video, location="loc", event_type="hike",
        target_clip_length_sec=(1.0, 8.0), max_total_output_min=1.0,
        content_wanted=["scenery"], exclude_when=["theme_mismatch"],
    )
    seg = Segment(
        segment_id="seg-a", start=0.0, end=3.0, duration=3.0,
        transcript="hello", visual_summary="a wide shot",
    )
    d = ClipDecision(
        segment_id="seg-a", action="include", refined_start=0.0, refined_end=3.0,
        theme_match=0.9, confidence=0.9, one_line_summary="granite pan",
    )
    run = Run(
        spec=spec, video_sha256="deadbeef",
        prepass_metrics=PrepassMetrics(
            resolution=(320, 240), fps=15.0, bitrate_kbps=100, duration_sec=9.0
        ),
        segments=[seg],
        scene_detection={"pyscenedetect": [], "scdet": [], "union": []},
        cost_estimate=CostEstimate(
            frames_to_send=1, projected_input_tokens=100, projected_usd=0.01,
            pricing_model_id="claude-sonnet-4-6", pricing_input_usd_per_mtok=3.0,
        ),
        decisions=[d],
        accepted_segment_ids=["seg-a"],
        clip_paths=[Path("/tmp/clip.mp4")],
        actual_cost_usd=0.005,
        status="completed",
    )
    return run


@pytest.mark.asyncio
async def test_ensure_collection_declares_payload_indices(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    indexed = [f for _c, f in fake._client.indexed_fields]
    assert "memory_type" in indexed
    assert "run_id" in indexed


@pytest.mark.asyncio
async def test_upsert_run_and_segment_produce_deterministic_ids(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    run = _run(tmp_path)

    rid = await store.upsert_run(run)
    seg = run.segments[0]
    sid = await store.upsert_segment(
        run=run, segment=seg, decision=run.decisions[0], clip_path=str(run.clip_paths[0]),
    )

    assert rid == _run_point_id(run.run_id)
    assert sid == _segment_point_id(run.run_id, seg.segment_id)

    bucket = fake.collections["video_clipping_memory"]
    assert bucket[rid].payload["memory_type"] == "run"
    assert bucket[rid].payload["run_id"] == run.run_id
    assert bucket[sid].payload["memory_type"] == "segment"
    assert bucket[sid].payload["decision"]["one_line_summary"] == "granite pan"


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_replay(tmp_path: Path) -> None:
    """Re-running upsert with the same run/segment leaves point count unchanged."""
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    run = _run(tmp_path)

    await store.upsert_run(run)
    await store.upsert_segment(
        run=run, segment=run.segments[0], decision=run.decisions[0],
        clip_path=str(run.clip_paths[0]),
    )
    initial = len(fake.collections["video_clipping_memory"])
    assert initial == 2

    await store.upsert_run(run)
    await store.upsert_segment(
        run=run, segment=run.segments[0], decision=run.decisions[0],
        clip_path=str(run.clip_paths[0]),
    )
    assert len(fake.collections["video_clipping_memory"]) == 2


@pytest.mark.asyncio
async def test_upsert_lesson_and_retrieve(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    lesson = Lesson(
        source_run_id="run-1", pattern_type="exclude_cluster",
        pattern_payload={"exclude_reason": "theme_mismatch", "count": 3},
        human_summary="hike runs cluster on theme_mismatch",
        event_type="hike",
    )
    lid = await store.upsert_lesson(lesson)
    assert lid == _lesson_point_id(lesson.lesson_id)

    payloads = await store.retrieve_lessons([lesson.lesson_id])
    assert len(payloads) == 1
    assert payloads[0]["memory_type"] == "lesson"
    assert payloads[0]["human_summary"] == "hike runs cluster on theme_mismatch"


@pytest.mark.asyncio
async def test_query_nearest_filters_by_type_and_run(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    run = _run(tmp_path)
    await store.upsert_run(run)
    await store.upsert_segment(
        run=run, segment=run.segments[0], decision=run.decisions[0],
        clip_path=str(run.clip_paths[0]),
    )

    # Query by segment vector should only return the segment (filter_by_type),
    # and if we exclude this run, no hits at all.
    [vector] = await fake.embedding_client.embed(["granite pan"])
    hits_seg = await store.query_nearest(vector, top_k=5, filter_by_type="segment")
    assert len(hits_seg) == 1
    assert hits_seg[0][2]["memory_type"] == "segment"

    hits_exclude = await store.query_nearest(
        vector, top_k=5, filter_by_type="segment", exclude_run_ids=[run.run_id]
    )
    assert hits_exclude == []
