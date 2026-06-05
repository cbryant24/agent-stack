from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from voiceover_direction.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_DIRECTION_LESSON,
    MEMORY_TYPE_TAKE,
    STATUS_COMPLETE,
)
from voiceover_direction.models import DirectionLesson, Take, VoiceProfile
from voiceover_direction.store import VoiceoverDirectionStore
from voiceover_direction.voice_registry import VoiceRegistry


def _make_store(registry: VoiceRegistry | None = None) -> tuple[VoiceoverDirectionStore, MagicMock]:
    mock_memory = MagicMock()
    mock_memory.embedding_client = MagicMock()
    mock_memory.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mock_memory.upsert_raw_points = AsyncMock()
    mock_memory.set_payload = AsyncMock()
    mock_memory.retrieve_points = AsyncMock(return_value=[])
    mock_memory.query_by_vector = AsyncMock(return_value=[])
    mock_memory.ensure_collection = AsyncMock()
    store = VoiceoverDirectionStore(mock_memory, voice_registry=registry)
    return store, mock_memory


def _take(**overrides) -> Take:
    base = dict(
        text="Welcome back to the channel.",
        voice_id="voice-1",
        model="eleven_v3",
        section_id="intro",
        project_id="proj-1",
    )
    base.update(overrides)
    return Take(**base)


def _match_values(filters) -> dict[str, object]:
    """Collapse a qdrant Filter's must-conditions into {key: value}."""
    return {c.key: c.match.value for c in filters.must}


# ── Construction ─────────────────────────────────────────────────────────────


def test_default_collection() -> None:
    store, _ = _make_store()
    assert store._collection == COLLECTION_NAME


def test_custom_collection() -> None:
    store = VoiceoverDirectionStore(MagicMock(), collection_name="test_collection")
    assert store._collection == "test_collection"


@pytest.mark.asyncio
async def test_ensure_collection_uses_embedding_dim() -> None:
    store, mock_memory = _make_store()
    await store.ensure_collection()
    mock_memory.ensure_collection.assert_awaited_once_with(COLLECTION_NAME, vector_size=1024)


# ── Take writes ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_take_embeds_text_and_sets_memory_type() -> None:
    store, mock_memory = _make_store()
    take = _take()
    await store.upsert_take(take)

    assert take.text in mock_memory.embedding_client.embed.call_args[0][0]
    point = mock_memory.upsert_raw_points.call_args[0][1][0]
    assert point.id == take.entry_id
    assert point.payload["memory_type"] == MEMORY_TYPE_TAKE


@pytest.mark.asyncio
async def test_bulk_upsert_takes() -> None:
    store, mock_memory = _make_store()
    mock_memory.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
    await store.upsert_takes_bulk([_take(), _take(section_id="outro")])
    points = mock_memory.upsert_raw_points.call_args[0][1]
    assert len(points) == 2


@pytest.mark.asyncio
async def test_bulk_upsert_empty_is_noop() -> None:
    store, mock_memory = _make_store()
    await store.upsert_takes_bulk([])
    mock_memory.upsert_raw_points.assert_not_called()
    mock_memory.embedding_client.embed.assert_not_called()


@pytest.mark.asyncio
async def test_update_take_reaction_flips_status_without_reembedding() -> None:
    store, mock_memory = _make_store()
    await store.update_take_reaction("take-1", "loved", rating=5, notes="great")

    mock_memory.embedding_client.embed.assert_not_called()
    coll, entry_id, payload = mock_memory.set_payload.call_args[0]
    assert coll == COLLECTION_NAME
    assert entry_id == "take-1"
    assert payload["reaction"] == "loved"
    assert payload["status"] == STATUS_COMPLETE
    assert payload["rating"] == 5
    assert payload["notes"] == "great"
    assert "reacted_at" in payload


@pytest.mark.asyncio
async def test_get_take_returns_none_when_absent() -> None:
    store, _ = _make_store()
    assert await store.get_take("missing") is None


@pytest.mark.asyncio
async def test_get_take_parses_record_payload() -> None:
    store, mock_memory = _make_store()
    take = _take()
    record = MagicMock()
    record.payload = take.to_payload()
    mock_memory.retrieve_points = AsyncMock(return_value=[record])

    restored = await store.get_take(take.entry_id)
    assert restored is not None
    assert restored.entry_id == take.entry_id
    assert restored.section_id == "intro"


# ── Take search ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_takes_default_filters_and_parsing() -> None:
    store, mock_memory = _make_store()
    take = _take(reaction="loved")
    mock_memory.query_by_vector = AsyncMock(return_value=[(take.entry_id, 0.9, take.to_payload())])

    results = await store.search_takes("calm intro")

    filters = mock_memory.query_by_vector.call_args.kwargs["filters"]
    matched = _match_values(filters)
    assert matched["memory_type"] == MEMORY_TYPE_TAKE
    assert matched["status"] == STATUS_COMPLETE  # exclude_pending default

    assert len(results) == 1
    pid, score, parsed = results[0]
    assert pid == take.entry_id
    assert score == 0.9
    assert isinstance(parsed, Take)


@pytest.mark.asyncio
async def test_search_takes_section_scoped_and_includes_pending() -> None:
    store, mock_memory = _make_store()
    await store.search_takes("x", section_id="intro", exclude_pending=False)
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert matched["section_id"] == "intro"
    assert "status" not in matched


# ── Direction lessons ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_lesson_embeds_statement() -> None:
    store, mock_memory = _make_store()
    lesson = DirectionLesson(statement="Slow down on emotional beats.", valence="positive")
    await store.upsert_lesson(lesson)
    assert lesson.statement in mock_memory.embedding_client.embed.call_args[0][0]
    point = mock_memory.upsert_raw_points.call_args[0][1][0]
    assert point.payload["memory_type"] == MEMORY_TYPE_DIRECTION_LESSON


@pytest.mark.asyncio
async def test_search_lessons_filters() -> None:
    store, mock_memory = _make_store()
    await store.search_lessons("pacing", scope="pacing", valence="positive")
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert matched["memory_type"] == MEMORY_TYPE_DIRECTION_LESSON
    assert matched["confirmed"] is True  # confirmed_only default
    assert matched["scope"] == "pacing"
    assert matched["valence"] == "positive"


@pytest.mark.asyncio
async def test_search_lessons_can_include_unconfirmed() -> None:
    store, mock_memory = _make_store()
    await store.search_lessons("x", confirmed_only=False)
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert "confirmed" not in matched


# ── Voice registry delegation ────────────────────────────────────────────────


def test_voice_delegation_hits_the_registry(tmp_path: Path) -> None:
    registry = VoiceRegistry(path=tmp_path / "voices.json")
    store, _ = _make_store(registry=registry)

    store.sync_voices([VoiceProfile(voice_id="v1", name="Rachel", category="stock")])
    assert [v.voice_id for v in store.list_voices()] == ["v1"]
    got = store.get_voice("v1")
    assert got is not None and got.name == "Rachel"
    assert store.get_voice("nope") is None


# ── list_pending (Step 4) ─────────────────────────────────────────────────────


def _record(take: Take) -> SimpleNamespace:
    return SimpleNamespace(id=take.entry_id, payload=take.to_payload())


@pytest.mark.asyncio
async def test_list_pending_filters_pending_and_sorts() -> None:
    store, mock_memory = _make_store()
    older = _take(section_id="a", created_at="2026-06-01T00:00:00+00:00")
    newer = _take(section_id="b", created_at="2026-06-02T00:00:00+00:00")
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(return_value=([_record(newer), _record(older)], None))

    pending = await store.list_pending()

    # Sorted oldest-first.
    assert [t.section_id for t in pending] == ["a", "b"]
    # Filter targets memory_type=take + status=pending.
    matched = _match_values(mock_memory._client.scroll.call_args.kwargs["scroll_filter"])
    assert matched["memory_type"] == MEMORY_TYPE_TAKE
    assert matched["status"] == "pending"


@pytest.mark.asyncio
async def test_list_pending_paginates_without_truncation() -> None:
    store, mock_memory = _make_store()
    page1 = [_record(_take(section_id=f"s{i}")) for i in range(100)]
    page2 = [_record(_take(section_id="s100"))]
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(side_effect=[(page1, "next"), (page2, None)])

    pending = await store.list_pending()

    assert len(pending) == 101  # both pages accumulated
    assert mock_memory._client.scroll.await_count == 2


@pytest.mark.asyncio
async def test_list_pending_empty() -> None:
    store, mock_memory = _make_store()
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(return_value=([], None))
    assert await store.list_pending() == []
