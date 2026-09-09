"""Cross-run duplicate detection (Phase 2)."""

from __future__ import annotations


import pytest

from video_clipping.constants import COLLECTION_NAME, MEMORY_TYPE_SEGMENT
from video_clipping.models import ClipDecision
from video_clipping.similarity.cross_run import (
    apply_cross_run_dedupe,
    flip_to_cross_run_duplicate,
)
from video_clipping.store import VideoClippingStore, _segment_point_id

from tests.fakes import FakeMemoryStore, _FakePoint


def _decision(seg_id: str, summary: str) -> ClipDecision:
    return ClipDecision(
        segment_id=seg_id, action="include", refined_start=0.0, refined_end=3.0,
        theme_match=0.8, confidence=0.9, one_line_summary=summary,
    )


def _seed_prior_segment(
    fake: FakeMemoryStore, *, prior_run_id: str, seg_id: str, one_line: str
) -> None:
    """Insert a prior-run segment with a vector matching the deterministic embedder."""
    from tests.fakes import _pseudo_vector

    vector = _pseudo_vector(one_line)
    point_id = _segment_point_id(prior_run_id, seg_id)
    fake.collections.setdefault(COLLECTION_NAME, {})[point_id] = _FakePoint(
        id=point_id,
        vector=vector,
        payload={
            "memory_type": MEMORY_TYPE_SEGMENT,
            "run_id": prior_run_id,
            "segment_id": seg_id,
            "decision": {"one_line_summary": one_line},
        },
    )


@pytest.mark.asyncio
async def test_flips_current_segment_that_duplicates_prior_run() -> None:
    fake = FakeMemoryStore()
    _seed_prior_segment(
        fake, prior_run_id="prior-1", seg_id="ps-x",
        one_line="wide granite summit view",
    )
    store = VideoClippingStore(fake)
    await store.ensure_collection()

    current = [
        _decision("cur-1", "wide granite summit view"),  # identical → will match
        _decision("cur-2", "muddy trail switchback"),    # unrelated
    ]
    [v1] = await fake.embedding_client.embed(["wide granite summit view"])
    [v2] = await fake.embedding_client.embed(["muddy trail switchback"])
    embeddings = {"cur-1": v1, "cur-2": v2}

    outcome = await apply_cross_run_dedupe(
        decisions=current,
        embeddings=embeddings,
        current_run_id="current-run",
        store=store,
        threshold=0.9,
    )
    assert [d.segment_id for d in outcome.kept] == ["cur-2"]
    assert len(outcome.hits) == 1
    hit = outcome.hits[0]
    assert hit.segment_id == "cur-1"
    assert hit.prior_run_id == "prior-1"
    assert hit.prior_segment_id == "ps-x"
    assert hit.score >= 0.9


@pytest.mark.asyncio
async def test_ignores_segments_from_same_run() -> None:
    fake = FakeMemoryStore()
    _seed_prior_segment(
        fake, prior_run_id="current-run", seg_id="ps-x",
        one_line="wide granite summit view",
    )
    store = VideoClippingStore(fake)
    await store.ensure_collection()

    current = [_decision("cur-1", "wide granite summit view")]
    [v] = await fake.embedding_client.embed(["wide granite summit view"])
    outcome = await apply_cross_run_dedupe(
        decisions=current, embeddings={"cur-1": v},
        current_run_id="current-run", store=store, threshold=0.9,
    )
    assert len(outcome.hits) == 0
    assert [d.segment_id for d in outcome.kept] == ["cur-1"]


@pytest.mark.asyncio
async def test_missing_embedding_skips_segment_but_keeps_it() -> None:
    fake = FakeMemoryStore()
    store = VideoClippingStore(fake)
    await store.ensure_collection()
    current = [_decision("cur-1", "x")]
    outcome = await apply_cross_run_dedupe(
        decisions=current, embeddings={}, current_run_id="run",
        store=store, threshold=0.9,
    )
    assert outcome.skipped_segment_ids == ["cur-1"]
    assert outcome.kept == current
    assert outcome.hits == []


def test_flip_to_cross_run_duplicate_sets_reason() -> None:
    d = _decision("s1", "x")
    flipped = flip_to_cross_run_duplicate(d)
    assert flipped.action == "exclude"
    assert flipped.exclude_reason == "duplicate_of_previous_run"
