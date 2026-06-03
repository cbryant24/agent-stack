from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_curation.constants import REACTION_PENDING, STATUS_PENDING
from music_curation.models import Generation, MusicResult, SunoPrompt


def _make_generate_response():
    """Return a mock Anthropic response for generate_prompts."""
    response_text = json.dumps({
        "prompts": [
            {"style_field": "lo-fi hip-hop, 80 BPM, jazz piano, vinyl crackle, tape saturation", "lyrics_field": None}
        ],
        "theory_reasoning": "This warm analog texture creates a contemplative mood.",
        "suggested_titles": ["Late Night Study"],
    })
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    msg.usage = MagicMock(input_tokens=500, output_tokens=200)
    return msg


def _make_no_question_response():
    msg = MagicMock()
    msg.content = [MagicMock(text='{"ask": false}')]
    msg.usage = MagicMock(input_tokens=100, output_tokens=20)
    return msg


@pytest.fixture
def mock_stores():
    """Patch all store construction and return mock objects."""
    with (
        patch("music_curation.agent._get_stores") as mock_get,
        patch("music_curation.agent.get_config") as mock_config,
        patch("music_curation.agent.AsyncAnthropic") as mock_anthropic,
    ):
        mock_config.return_value = MagicMock(anthropic_api_key="sk-test")

        curation_store = MagicMock()
        curation_store.ensure_collection = AsyncMock()
        curation_store.upsert_generations_bulk = AsyncMock()
        curation_store.search_generations = AsyncMock(return_value=[])
        curation_store.search_taste = AsyncMock(return_value=[])
        curation_store.search_templates = AsyncMock(return_value=[])
        curation_store.to_generation_ref = MagicMock()

        memory_store = MagicMock()
        memory_store.embedding_client = MagicMock()
        memory_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        memory_store.query_by_vector = AsyncMock(return_value=[])
        memory_store.search = AsyncMock(return_value=[])

        knowledge_store = MagicMock()
        mock_get.return_value = (curation_store, memory_store, knowledge_store)

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=_make_generate_response())
        mock_anthropic.return_value = client

        yield {
            "curation_store": curation_store,
            "memory_store": memory_store,
            "knowledge_store": knowledge_store,
            "client": client,
        }


class TestCurateFunction:
    @pytest.mark.asyncio
    async def test_returns_music_result(self, mock_stores):
        from music_curation.agent import curate

        # Mock the question check to say "no question"
        mock_stores["client"].messages.create = AsyncMock(
            side_effect=[_make_no_question_response(), _make_generate_response()]
        )

        result = await curate("I want a lo-fi hip-hop track")

        assert isinstance(result, MusicResult)
        assert len(result.prompts) >= 1
        assert result.prompts[0].style_field.startswith("lo-fi")

    @pytest.mark.asyncio
    async def test_dry_run_no_generation_call(self, mock_stores):
        from music_curation.agent import curate

        result = await curate("lo-fi chill", dry_run=True)

        assert result.status == "completed"
        # In dry run, the Anthropic client should not be called for generation
        # (only possibly for question check, and we skip that in dry_run)
        mock_stores["curation_store"].upsert_generations_bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_generations_stored(self, mock_stores):
        from music_curation.agent import curate

        mock_stores["client"].messages.create = AsyncMock(
            side_effect=[_make_no_question_response(), _make_generate_response()]
        )

        result = await curate("lo-fi chill", skip_question=True)

        mock_stores["curation_store"].upsert_generations_bulk.assert_awaited_once()
        stored_gens = mock_stores["curation_store"].upsert_generations_bulk.call_args[0][0]
        assert len(stored_gens) >= 1
        assert all(g.reaction == REACTION_PENDING for g in stored_gens)

    @pytest.mark.asyncio
    async def test_generation_ids_in_result(self, mock_stores):
        from music_curation.agent import curate

        mock_stores["client"].messages.create = AsyncMock(
            side_effect=[_make_no_question_response(), _make_generate_response()]
        )

        result = await curate("phonk session", skip_question=True)

        assert len(result.generation_ids) >= 1

    @pytest.mark.asyncio
    async def test_skip_question_flag(self, mock_stores):
        from music_curation.agent import curate

        result = await curate("lo-fi", skip_question=True)

        # With skip_question=True, only one LLM call (generation), no question check
        call_count = mock_stores["client"].messages.create.await_count
        assert call_count == 1


class TestMakePendingGenerations:
    def test_creates_generation_for_each_prompt(self):
        from music_curation.agent import _make_pending_generations

        prompts = [
            SunoPrompt(style_field="lo-fi, 80 BPM, jazz"),
            SunoPrompt(style_field="phonk, 135 BPM, 808"),
        ]
        titles = ["Study Beats", "Memphis Nights"]
        gens = _make_pending_generations("test request", prompts, titles, "run-123")

        assert len(gens) == 2
        assert all(g.reaction == REACTION_PENDING for g in gens)
        assert all(g.status == STATUS_PENDING for g in gens)
        assert gens[0].suggested_track_title == "Study Beats"
        assert gens[1].suggested_track_title == "Memphis Nights"

    def test_generation_goal_truncated_to_200(self):
        from music_curation.agent import _make_pending_generations

        long_request = "I want " + "x" * 300
        prompts = [SunoPrompt(style_field="lo-fi, 80 BPM, jazz, vinyl, tape")]
        gens = _make_pending_generations(long_request, prompts, ["Test"], "run")
        assert len(gens[0].goal) <= 200

    def test_unique_entry_ids(self):
        from music_curation.agent import _make_pending_generations

        prompts = [
            SunoPrompt(style_field="lo-fi, 80 BPM, jazz piano"),
            SunoPrompt(style_field="phonk, 135 BPM, heavy 808"),
        ]
        gens = _make_pending_generations("test", prompts, ["A", "B"], "run")
        assert gens[0].entry_id != gens[1].entry_id
