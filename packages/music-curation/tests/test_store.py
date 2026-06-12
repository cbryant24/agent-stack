from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_runtime.diagnostics import DiagnosticReport, RemediationSpec
from music_curation.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TASTE,
    REACTION_LOVED,
    REACTION_PENDING,
    STATUS_COMPLETE,
    STATUS_PENDING,
)
from music_curation.models import Generation, TasteLesson, Template
from music_curation.store import MusicCurationStore


def _make_store() -> tuple[MusicCurationStore, MagicMock]:
    """Return a MusicCurationStore with a mocked MemoryStore."""
    mock_memory = MagicMock()
    mock_memory.embedding_client = MagicMock()
    mock_memory.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mock_memory.upsert_raw_points = AsyncMock()
    mock_memory.set_payload = AsyncMock()
    mock_memory.retrieve_points = AsyncMock(return_value=[])
    mock_memory.query_by_vector = AsyncMock(return_value=[])
    mock_memory.ensure_collection = AsyncMock()
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(return_value=([], None))
    store = MusicCurationStore(mock_memory)
    return store, mock_memory


class TestMusicCurationStoreConstruction:
    def test_default_collection(self):
        mock_memory = MagicMock()
        store = MusicCurationStore(mock_memory)
        assert store._collection == COLLECTION_NAME

    def test_custom_collection(self):
        mock_memory = MagicMock()
        store = MusicCurationStore(mock_memory, collection_name="test_collection")
        assert store._collection == "test_collection"


class TestUpsertGeneration:
    @pytest.mark.asyncio
    async def test_upsert_calls_embed_and_raw_upsert(self):
        store, mock_memory = _make_store()
        gen = Generation(session_id="s1", style_field="lo-fi, 80 BPM, jazz, vinyl crackle")

        await store.upsert_generation(gen)

        mock_memory.embedding_client.embed.assert_awaited_once()
        embed_call_args = mock_memory.embedding_client.embed.call_args
        assert gen.style_field in embed_call_args[0][0]

        mock_memory.upsert_raw_points.assert_awaited_once()
        points_arg = mock_memory.upsert_raw_points.call_args[0][1]
        assert len(points_arg) == 1
        assert points_arg[0].id == gen.entry_id

    @pytest.mark.asyncio
    async def test_payload_includes_memory_type(self):
        store, mock_memory = _make_store()
        gen = Generation(session_id="s1", style_field="trap, 140 BPM, heavy 808 bass")
        await store.upsert_generation(gen)

        point = mock_memory.upsert_raw_points.call_args[0][1][0]
        assert point.payload["memory_type"] == MEMORY_TYPE_GENERATION

    @pytest.mark.asyncio
    async def test_bulk_upsert(self):
        store, mock_memory = _make_store()
        mock_memory.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])

        gens = [
            Generation(session_id="s1", style_field="lo-fi, 80 BPM, jazz piano"),
            Generation(session_id="s1", style_field="phonk, 135 BPM, heavy 808"),
        ]
        await store.upsert_generations_bulk(gens)

        mock_memory.upsert_raw_points.assert_awaited_once()
        points = mock_memory.upsert_raw_points.call_args[0][1]
        assert len(points) == 2

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_is_noop(self):
        store, mock_memory = _make_store()
        await store.upsert_generations_bulk([])
        mock_memory.embedding_client.embed.assert_not_called()


class TestUpdateGenerationReaction:
    @pytest.mark.asyncio
    async def test_updates_reaction_and_status(self):
        store, mock_memory = _make_store()
        await store.update_generation_reaction("entry-123", REACTION_LOVED)

        mock_memory.set_payload.assert_awaited_once()
        call_args = mock_memory.set_payload.call_args
        assert call_args[0][1] == "entry-123"
        payload = call_args[0][2]
        assert payload["reaction"] == REACTION_LOVED
        assert payload["status"] == STATUS_COMPLETE

    @pytest.mark.asyncio
    async def test_includes_notes_when_provided(self):
        store, mock_memory = _make_store()
        await store.update_generation_reaction("e1", REACTION_LOVED, notes="slow it down next time")

        payload = mock_memory.set_payload.call_args[0][2]
        assert payload["notes"] == "slow it down next time"

    @pytest.mark.asyncio
    async def test_includes_context_when_provided(self):
        store, mock_memory = _make_store()
        await store.update_generation_reaction(
            "e1", REACTION_LOVED, context="the cowbell placement is exactly right"
        )

        payload = mock_memory.set_payload.call_args[0][2]
        assert payload["context"] == "the cowbell placement is exactly right"

    @pytest.mark.asyncio
    async def test_includes_rating_when_provided(self):
        store, mock_memory = _make_store()
        await store.update_generation_reaction("e1", REACTION_LOVED, rating=5)

        payload = mock_memory.set_payload.call_args[0][2]
        assert payload["rating"] == 5

    @pytest.mark.asyncio
    async def test_no_optional_fields_not_in_payload(self):
        store, mock_memory = _make_store()
        await store.update_generation_reaction("e1", REACTION_LOVED)

        payload = mock_memory.set_payload.call_args[0][2]
        assert "notes" not in payload
        assert "context" not in payload
        assert "rating" not in payload


class TestSearchGenerations:
    @pytest.mark.asyncio
    async def test_search_excludes_pending_by_default(self):
        store, mock_memory = _make_store()
        await store.search_generations("lo-fi phonk")

        call_args = mock_memory.query_by_vector.call_args
        filters = call_args[1].get("filters") or call_args[0][2]
        # Should have a memory_type=generation filter AND status=complete filter
        filter_conditions = filters.must
        keys = [c.key for c in filter_conditions]
        assert "memory_type" in keys
        assert "status" in keys

    @pytest.mark.asyncio
    async def test_search_includes_pending_when_requested(self):
        store, mock_memory = _make_store()
        await store.search_generations("lo-fi", exclude_pending=False)

        filters = mock_memory.query_by_vector.call_args[1].get("filters") or \
            mock_memory.query_by_vector.call_args[0][2]
        keys = [c.key for c in filters.must]
        assert "memory_type" in keys
        assert "status" not in keys

    @pytest.mark.asyncio
    async def test_search_returns_generation_objects(self):
        store, mock_memory = _make_store()
        gen = Generation(session_id="s1", style_field="lo-fi, 80 BPM", reaction=REACTION_LOVED)
        payload = gen.to_payload()
        mock_memory.query_by_vector = AsyncMock(
            return_value=[(gen.entry_id, 0.92, payload)]
        )

        results = await store.search_generations("lo-fi jazz")
        assert len(results) == 1
        entry_id, score, returned_gen = results[0]
        assert score == 0.92
        assert returned_gen.reaction == REACTION_LOVED
        assert returned_gen.session_id == "s1"


class TestListPending:
    @pytest.mark.asyncio
    async def test_list_pending_uses_scroll(self):
        store, mock_memory = _make_store()
        gen = Generation(session_id="s1", style_field="lo-fi, 80 BPM, vinyl crackle")
        mock_memory._client.scroll = AsyncMock(
            return_value=([MagicMock(payload=gen.to_payload())], None)
        )

        results = await store.list_pending()
        assert len(results) == 1
        mock_memory._client.scroll.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_pending_empty(self):
        store, mock_memory = _make_store()
        results = await store.list_pending()
        assert results == []


class TestGetGeneration:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        store, mock_memory = _make_store()
        result = await store.get_generation("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_memory_type(self):
        store, mock_memory = _make_store()
        taste = TasteLesson(statement="likes heavy bass", valence="positive", scope="instrumentation")
        payload = taste.to_payload()
        mock_memory.retrieve_points = AsyncMock(
            return_value=[MagicMock(id="e1", payload=payload)]
        )

        result = await store.get_generation("e1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_generation_when_found(self):
        store, mock_memory = _make_store()
        gen = Generation(session_id="s1", style_field="lo-fi, 80 BPM, jazz")
        payload = gen.to_payload()
        mock_memory.retrieve_points = AsyncMock(
            return_value=[MagicMock(id=gen.entry_id, payload=payload)]
        )

        result = await store.get_generation(gen.entry_id)
        assert result is not None
        assert result.entry_id == gen.entry_id


class TestToGenerationRef:
    def test_ref_excerpt(self):
        store, _ = _make_store()
        long_style = "lo-fi hip-hop, 80 BPM, " + ("jazz, " * 30)
        gen = Generation(session_id="s1", style_field=long_style[:1000])
        ref = store.to_generation_ref(gen)
        assert len(ref.style_field_excerpt) <= 100
        assert ref.entry_id == gen.entry_id
        assert ref.reaction == REACTION_PENDING


class TestApprovedToLikedMigration:
    """Change 1 regression: the one-shot approved → liked value migration."""

    @pytest.mark.asyncio
    async def test_migrates_all_approved_entries(self):
        store, mock_memory = _make_store()
        recs = [MagicMock(id="g1"), MagicMock(id="g2"), MagicMock(id="g3")]
        # One scroll page, then terminate (offset=None).
        mock_memory._client.scroll = AsyncMock(return_value=(recs, None))

        migrated = await store.migrate_approved_to_liked()

        assert migrated == 3
        assert mock_memory.set_payload.await_count == 3
        for call in mock_memory.set_payload.await_args_list:
            # set_payload(collection, point_id, {"reaction": "liked"})
            assert call[0][2] == {"reaction": "liked"}

    @pytest.mark.asyncio
    async def test_migration_noop_when_none_approved(self):
        store, mock_memory = _make_store()  # scroll returns ([], None) by default
        migrated = await store.migrate_approved_to_liked()
        assert migrated == 0
        mock_memory.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_by_reaction(self):
        store, mock_memory = _make_store()
        mock_memory._client.scroll = AsyncMock(
            return_value=([MagicMock(id="g1"), MagicMock(id="g2")], None)
        )
        count = await store.count_by_reaction("approved")
        assert count == 2

    @pytest.mark.asyncio
    async def test_count_by_reaction_zero(self):
        store, mock_memory = _make_store()
        count = await store.count_by_reaction("approved")
        assert count == 0


class TestRemediation:
    """The music-curation side of the orchestrator's diagnose → delegate seam: a
    filter-parameterized re-tag handler that validates before writing."""

    @staticmethod
    def _report(**overrides) -> DiagnosticReport:
        base = dict(
            collection=COLLECTION_NAME,
            owning_agent="music-curation",
            symptom="s",
            diagnosis="d",
            proposed_fix="re-tag",
            remediation=RemediationSpec(
                kind="retag", match={"reaction": "approvd"}, set={"reaction": "approved"}
            ),
        )
        base.update(overrides)
        return DiagnosticReport(**base)

    @pytest.mark.asyncio
    async def test_refuses_wrong_collection(self):
        store, mock_memory = _make_store()
        outcome = await store.remediate(self._report(collection="some_other_memory"))
        assert outcome.status == "open"
        assert "this store owns" in outcome.detail
        mock_memory.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_refuses_missing_spec(self):
        store, mock_memory = _make_store()
        outcome = await store.remediate(self._report(remediation=None))
        assert outcome.status == "open"
        assert "no remediation spec" in outcome.detail
        mock_memory.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_refuses_unsupported_kind(self):
        store, mock_memory = _make_store()
        # model_construct bypasses Literal validation to simulate a future/unknown kind
        spec = RemediationSpec.model_construct(kind="reembed", match={"a": "b"}, set={"c": "d"})
        outcome = await store.remediate(self._report(remediation=spec))
        assert outcome.status == "open"
        assert "unsupported remediation kind" in outcome.detail
        mock_memory.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_refuses_malformed_spec(self):
        store, mock_memory = _make_store()
        spec = RemediationSpec(kind="retag", match={}, set={"reaction": "approved"})
        outcome = await store.remediate(self._report(remediation=spec))
        assert outcome.status == "open"
        assert "malformed retag spec" in outcome.detail
        mock_memory.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_retag(self):
        store, mock_memory = _make_store()
        recs = [MagicMock(id="g1"), MagicMock(id="g2")]
        mock_memory._client.scroll = AsyncMock(return_value=(recs, None))

        outcome = await store.remediate(self._report())

        assert outcome.status == "fixed"
        assert "re-tagged 2 point(s)" in outcome.detail
        assert mock_memory.set_payload.await_count == 2
        for call in mock_memory.set_payload.await_args_list:
            # set_payload(collection, point_id, {"reaction": "approved"})
            assert call[0][2] == {"reaction": "approved"}

    @pytest.mark.asyncio
    async def test_retag_noop_when_no_matches(self):
        store, mock_memory = _make_store()  # scroll returns ([], None) by default
        outcome = await store.remediate(self._report())
        assert outcome.status == "fixed"
        assert "re-tagged 0 point(s)" in outcome.detail
        mock_memory.set_payload.assert_not_called()
