"""Lesson surfacing into the decide prompt (Phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_clipping.constants import COLLECTION_NAME, MEMORY_TYPE_LESSON
from video_clipping.lesson import surface_lessons_for_spec
from video_clipping.models import (
    CostEstimate,
    PrepassMetrics,
    Run,
    Spec,
)
from video_clipping.store import VideoClippingStore

from tests.fakes import FakeMemoryStore, _FakePoint, _pseudo_vector


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


@pytest.mark.asyncio
async def test_surfaces_lesson_whose_text_matches_spec_query(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    # The query is `f"{event_type}: {content_wanted[0]}"` == "hike: scenery".
    matching_text = "hike: scenery"
    fake.collections.setdefault(COLLECTION_NAME, {})["lesson-1"] = _FakePoint(
        id="lesson-1",
        vector=_pseudo_vector(matching_text),
        payload={
            "memory_type": MEMORY_TYPE_LESSON,
            "source_run_id": "prior-1",
            "pattern_type": "exclude_cluster",
            "human_summary": "hike specs cluster on theme_mismatch",
            "event_type": "hike",
        },
    )
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    run = _run(tmp_path)

    lessons = await surface_lessons_for_spec(run, store, threshold=0.0)
    assert lessons == ["hike specs cluster on theme_mismatch"]


@pytest.mark.asyncio
async def test_returns_empty_on_qdrant_failure(tmp_path: Path) -> None:
    fake = FakeMemoryStore(raise_on_query=True)
    store = VideoClippingStore(fake)
    lessons = await surface_lessons_for_spec(_run(tmp_path), store, threshold=0.0)
    assert lessons == []


@pytest.mark.asyncio
async def test_returns_empty_when_no_content_wanted(tmp_path: Path) -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    run = _run(tmp_path)
    run.spec = run.spec.model_copy(update={"content_wanted": []})
    lessons = await surface_lessons_for_spec(run, store)
    # event_type alone still forms a valid non-empty query, so it may or may not
    # return hits depending on seeded data. With no seeded lessons it must be empty.
    assert lessons == []
