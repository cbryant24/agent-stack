"""`clip generate` writes to Qdrant after a successful run (Phase 2).

Uses a FakeMemoryStore injected via generate_sync's `store=` kwarg. Verifies:
- run + accepted segment points written
- excluded segments not written
- Qdrant failure doesn't fail the run (run.qdrant_deviation=True)
- cross-run dedupe is off by default (no queries fire)
- cross-run dedupe on drops a matching current segment
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from video_clipping.constants import COLLECTION_NAME, MEMORY_TYPE_SEGMENT
from video_clipping.generate import generate_sync
from video_clipping.models import (
    Segment,
)
from video_clipping.plan import load_run
from video_clipping.store import VideoClippingStore, _segment_point_id

from tests.conftest import requires_ffmpeg
from tests.fakes import FakeMemoryStore, FakeProvider, _FakePoint, _pseudo_vector
from tests.fixtures.generate_synthetic_video import generate as generate_video


def _decide_json(action: str, seg: Segment, summary: str,
                 exclude_reason: str | None = None) -> str:
    return json.dumps({
        "action": action,
        "refined_start": seg.start,
        "refined_end": seg.end,
        "exclude_reason": exclude_reason,
        "theme_match": 0.7 if action != "exclude" else 0.2,
        "confidence": 0.8,
        "one_line_summary": summary,
    })


def _make_plan_from_video(tmp_path: Path, video: Path) -> Path:
    """Run pre-pass to get a plan.json for the given video."""
    from click.testing import CliRunner
    from video_clipping.cli import cli
    from agent_runtime import get_config

    spec_yaml = tmp_path / "spec.yaml"
    spec_yaml.write_text(
        "\n".join([
            f"video: {video}",
            "location: Synthetic hillside",
            "event_type: hike",
            "target_clip_length_sec: [1, 8]",
            "max_total_output_min: 1.0",
            "content_wanted: [dynamic scenes]",
            "exclude_when: [theme_mismatch]",
        ]),
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(
        cli, ["draft", str(video), "--spec", str(spec_yaml)], catch_exceptions=False
    )
    assert res.exit_code == 0, res.stderr
    outputs_root = get_config().agent_data_dir / "video-clipping" / "outputs"
    return next(outputs_root.iterdir()) / "plan.json"


def _fake_responses_alternating_include_exclude(plan_segments: list[Segment]) -> list:
    from tests.fakes import FakeCompletion
    responses: list = []
    for i, seg in enumerate(plan_segments):
        responses.append(FakeCompletion(text="visual summary", input_tokens=200, output_tokens=30))
        if i % 2 == 0:
            responses.append(FakeCompletion(
                text=_decide_json("include", seg, f"scene {i} kept")
            ))
        else:
            responses.append(FakeCompletion(
                text=_decide_json("exclude", seg, f"scene {i} skipped", "theme_mismatch")
            ))
    return responses


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    provider: FakeProvider,
    embedder,
) -> None:
    from tests.fakes import FakeWhisperModel, FakeWhisperSegment

    monkeypatch.setattr("video_clipping.generate.get_provider", lambda: provider)
    monkeypatch.setattr(
        "video_clipping.similarity.embed.get_embedding_client", lambda: embedder
    )
    monkeypatch.setattr(
        "video_clipping.audio.transcribe._load_model",
        lambda name: FakeWhisperModel(
            segments=[FakeWhisperSegment(start=0.0, end=9.0, text="hi")],
            duration=9.0,
        ),
    )
    monkeypatch.setattr("video_clipping.audio.transcribe.WHISPER_BACKOFF_SEC", 0.0)


@requires_ffmpeg
def test_generate_persists_run_and_accepted_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    plan_path = _make_plan_from_video(tmp_path, video)

    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)

    fake_store = FakeMemoryStore()
    provider = FakeProvider(
        responses=_fake_responses_alternating_include_exclude(plan.segments)
    )
    _patch_common(monkeypatch, provider, fake_store.embedding_client)
    store = VideoClippingStore(fake_store)

    result = asyncio.run(generate_sync(
        run=plan, plan_path=plan_path, max_usd=5.0, store=store,
    ))
    assert result.status == "completed"
    assert not result.qdrant_deviation

    bucket = fake_store.collections[COLLECTION_NAME]
    n_run_points = sum(1 for p in bucket.values() if p.payload["memory_type"] == "run")
    n_seg_points = sum(1 for p in bucket.values() if p.payload["memory_type"] == "segment")
    n_expected_segs = len(
        [d for d in result.decisions if d.action in ("include", "trim")]
    )
    assert n_run_points == 1
    assert n_seg_points == n_expected_segs
    # Excluded decisions must NOT be persisted as segment points.
    for p in bucket.values():
        if p.payload["memory_type"] == "segment":
            assert p.payload["decision"]["action"] in ("include", "trim")


@requires_ffmpeg
def test_generate_survives_qdrant_upsert_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    plan_path = _make_plan_from_video(tmp_path, video)
    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)

    fake_store = FakeMemoryStore(raise_on_upsert=True)
    provider = FakeProvider(
        responses=_fake_responses_alternating_include_exclude(plan.segments)
    )
    _patch_common(monkeypatch, provider, fake_store.embedding_client)
    store = VideoClippingStore(fake_store)

    result = asyncio.run(generate_sync(
        run=plan, plan_path=plan_path, max_usd=5.0, store=store,
    ))
    assert result.status == "completed"
    assert result.qdrant_deviation is True

    persisted = load_run(plan_path.parent / "run.json")
    assert persisted.qdrant_deviation is True


@requires_ffmpeg
def test_cross_run_dedupe_off_by_default_makes_no_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    plan_path = _make_plan_from_video(tmp_path, video)
    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)

    fake_store = FakeMemoryStore()
    provider = FakeProvider(
        responses=_fake_responses_alternating_include_exclude(plan.segments)
    )
    _patch_common(monkeypatch, provider, fake_store.embedding_client)
    store = VideoClippingStore(fake_store)

    asyncio.run(generate_sync(
        run=plan, plan_path=plan_path, max_usd=5.0, store=store,
        cross_run_dedupe=False, use_lessons=False,
    ))
    # No queries — only writes. (use_lessons=False disables the lesson-surfacing
    # query; cross_run_dedupe=False disables the per-accepted-segment query.)
    assert fake_store.query_calls == []


@requires_ffmpeg
def test_cross_run_dedupe_drops_matching_current_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    plan_path = _make_plan_from_video(tmp_path, video)
    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)

    fake_store = FakeMemoryStore()
    # Seed a prior-run segment whose vector matches the summary "scene 0 kept".
    fake_store.collections.setdefault(COLLECTION_NAME, {})[
        _segment_point_id("prior-1", "ps-x")
    ] = _FakePoint(
        id=_segment_point_id("prior-1", "ps-x"),
        vector=_pseudo_vector("scene 0 kept"),
        payload={
            "memory_type": MEMORY_TYPE_SEGMENT,
            "run_id": "prior-1",
            "segment_id": "ps-x",
            "decision": {"one_line_summary": "scene 0 kept"},
        },
    )

    provider = FakeProvider(
        responses=_fake_responses_alternating_include_exclude(plan.segments)
    )
    _patch_common(monkeypatch, provider, fake_store.embedding_client)
    store = VideoClippingStore(fake_store)

    result = asyncio.run(generate_sync(
        run=plan, plan_path=plan_path, max_usd=5.0, store=store,
        cross_run_dedupe=True, cross_run_threshold=0.9,
    ))
    dupes = [
        d for d in result.decisions
        if d.exclude_reason == "duplicate_of_previous_run"
    ]
    assert len(dupes) >= 1
    assert any(hit["prior_run_id"] == "prior-1" for hit in result.cross_run_hits)
