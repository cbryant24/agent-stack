"""`clip explain <question>` — grounded semantic-search tutor (Phase 2)."""

from __future__ import annotations


import pytest

from video_clipping.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_SEGMENT,
)
from video_clipping.explain import (
    PreflightCostRefusal,
    QdrantUnavailable,
    explain_sync,
    render_explain,
)
from video_clipping.store import VideoClippingStore

from tests.fakes import (
    FakeCompletion,
    FakeMemoryStore,
    FakeProvider,
    _FakePoint,
    _pseudo_vector,
)


def _seed(fake: FakeMemoryStore) -> None:
    """Seed 3 segments + 1 lesson."""
    bucket = fake.collections.setdefault(COLLECTION_NAME, {})
    for i, summary in enumerate(
        ["piano intro softly playing", "wide granite summit view", "muddy trail switchback"]
    ):
        pid = f"seg-{i}"
        bucket[pid] = _FakePoint(
            id=pid,
            vector=_pseudo_vector(summary),
            payload={
                "memory_type": MEMORY_TYPE_SEGMENT,
                "run_id": f"run-{i}",
                "segment_id": pid,
                "decision": {
                    "action": "include",
                    "one_line_summary": summary,
                    "theme_match": 0.8,
                    "confidence": 0.9,
                },
                "clip_path": f"/tmp/{pid}.mp4",
            },
        )
    bucket["lesson-1"] = _FakePoint(
        id="lesson-1",
        vector=_pseudo_vector("hike specs cluster on theme_mismatch"),
        payload={
            "memory_type": MEMORY_TYPE_LESSON,
            "source_run_id": "run-1",
            "pattern_type": "exclude_cluster",
            "human_summary": "hike specs cluster on theme_mismatch",
            "event_type": "hike",
        },
    )


@pytest.mark.asyncio
async def test_preflight_refusal_below_max_usd_makes_no_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMemoryStore()
    _seed(fake)
    provider = FakeProvider()
    monkeypatch.setattr("video_clipping.explain.get_provider", lambda: provider)

    with pytest.raises(PreflightCostRefusal):
        await explain_sync(
            "why?", max_usd=1e-8, top_k=8, store=VideoClippingStore(fake)
        )
    assert provider.calls == []


@pytest.mark.asyncio
async def test_qdrant_unavailable_raises_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMemoryStore(raise_on_query=True)
    _seed(fake)
    provider = FakeProvider(responses=[FakeCompletion(text="answer")])
    monkeypatch.setattr("video_clipping.explain.get_provider", lambda: provider)

    with pytest.raises(QdrantUnavailable):
        await explain_sync(
            "which clips have piano?", max_usd=1.0, top_k=4,
            store=VideoClippingStore(fake),
        )
    assert provider.calls == []


@pytest.mark.asyncio
async def test_explain_synthesizes_answer_with_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMemoryStore()
    _seed(fake)
    provider = FakeProvider(responses=[
        FakeCompletion(
            text="The piano is in run run-0, segment seg-0.",
            input_tokens=300, output_tokens=40,
        )
    ])
    monkeypatch.setattr("video_clipping.explain.get_provider", lambda: provider)

    result = await explain_sync(
        "which clips have piano?", max_usd=1.0, top_k=4,
        store=VideoClippingStore(fake),
    )
    assert "piano" in result.answer
    # Sources section names the segment/run pattern in render.
    rendered = render_explain(result)
    assert "── Sources ──" in rendered
    assert any(h.memory_type == "segment" for h in result.hits)
    # One provider call made — nothing extra.
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_explain_rejects_unknown_include_types() -> None:
    fake = FakeMemoryStore()
    with pytest.raises(ValueError):
        await explain_sync(
            "?", max_usd=1.0, top_k=2, include_types="segment,bogus",
            store=VideoClippingStore(fake),
        )


def test_explain_cli_preflight_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`clip explain` exits 2 when projected cost > --max-usd."""
    from click.testing import CliRunner
    from video_clipping.cli import cli

    fake = FakeMemoryStore()
    _seed(fake)
    provider = FakeProvider()
    monkeypatch.setattr("video_clipping.explain.get_provider", lambda: provider)
    monkeypatch.setattr(
        "video_clipping.explain.get_memory_store", lambda: fake
    )
    # Also patch the CLI entrypoint's store-source since explain_sync builds one
    # from get_memory_store when store is None.

    runner = CliRunner()
    result = runner.invoke(
        cli, ["explain", "which clips?", "--max-usd", "0.0000001"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert provider.calls == []


def test_explain_cli_qdrant_unavailable_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from click.testing import CliRunner
    from video_clipping.cli import cli

    fake = FakeMemoryStore(raise_on_query=True)
    _seed(fake)
    provider = FakeProvider(responses=[FakeCompletion(text="answer")])
    monkeypatch.setattr("video_clipping.explain.get_provider", lambda: provider)
    monkeypatch.setattr("video_clipping.explain.get_memory_store", lambda: fake)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["explain", "which clips have piano?"], catch_exceptions=False
    )
    assert result.exit_code == 1
