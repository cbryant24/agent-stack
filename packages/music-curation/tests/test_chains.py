from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_curation.chains import (
    DelegationTrigger,
    MissingTitlesError,
    _is_theory_question,
    _mentions_artist_or_genre_reference,
    _mentions_suno_feature,
    _parse_generation_response,
    _record_llm,
)
from music_curation.constants import (
    DELEGATION_ARTIST_REF_THRESHOLD,
    DELEGATION_MUSIC_THEORY_THRESHOLD,
    DELEGATION_SUNO_FEATURE_THRESHOLD,
)
from music_curation.models import SunoPrompt
from music_curation.retrieval import RetrievedContext


class MockMessage:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 200):
        self.content = [MagicMock(text=text)]
        self.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)


class TestMentionsSunoFeature:
    def test_suno_tag(self):
        assert _mentions_suno_feature("how do I use the suno v5 feature")

    def test_suno_syntax(self):
        assert _mentions_suno_feature("what is the suno syntax for tags")

    def test_style_field_mention(self):
        assert _mentions_suno_feature("how long can the style field be")

    def test_instrumental_tag(self):
        assert _mentions_suno_feature("where do I put [Instrumental]")

    def test_no_suno_mention(self):
        assert not _mentions_suno_feature("I want something lo-fi and chill")

    def test_suno_in_context_but_not_feature(self):
        assert not _mentions_suno_feature("suno generated this yesterday")


class TestIsTheoryQuestion:
    def test_why_does_it_work(self):
        assert _is_theory_question("why does this chord progression work so well")

    def test_music_theory(self):
        assert _is_theory_question("explain the music theory behind this")

    def test_what_makes(self):
        assert _is_theory_question("what makes phonk sound so dark")

    def test_plain_request(self):
        assert not _is_theory_question("create a lo-fi hip-hop track for me")


class TestMentionsArtistReference:
    def test_sounds_like(self):
        assert _mentions_artist_or_genre_reference("something that sounds like Nujabes")

    def test_inspired_by(self):
        assert _mentions_artist_or_genre_reference("inspired by JRPGs from the 90s")

    def test_in_the_style_of(self):
        assert _mentions_artist_or_genre_reference("in the style of Junya Nakano")

    def test_plain_description(self):
        assert not _mentions_artist_or_genre_reference("lo-fi, chill, 80 BPM vibes")


class TestParseGenerationResponse:
    def test_valid_json(self):
        response_text = json.dumps({
            "prompts": [
                {
                    "style_field": "lo-fi hip-hop, 80 BPM, jazz piano, vinyl crackle",
                    "lyrics_field": "[Instrumental]",
                }
            ],
            "theory_reasoning": "This works because of the warm analog texture.",
            "suggested_titles": ["Midnight Study Session"],
        })
        msg = MockMessage(response_text)
        prompts, reasoning, titles = _parse_generation_response(msg)
        assert len(prompts) == 1
        assert prompts[0].style_field.startswith("lo-fi")
        assert prompts[0].lyrics_field == "[Instrumental]"
        assert "warm analog" in reasoning
        assert titles[0] == "Midnight Study Session"

    def test_json_in_markdown_block(self):
        response_text = "Here is the result:\n```json\n" + json.dumps({
            "prompts": [{"style_field": "trap, 140 BPM, 808 bass", "lyrics_field": None}],
            "theory_reasoning": "Dark and heavy.",
            "suggested_titles": ["Dark Trap"],
        }) + "\n```"
        msg = MockMessage(response_text)
        prompts, reasoning, titles = _parse_generation_response(msg)
        assert len(prompts) == 1
        assert "trap" in prompts[0].style_field

    def test_invalid_json_raises_missing_titles_error(self):
        msg = MockMessage("This is not JSON at all, sorry!")
        with pytest.raises(MissingTitlesError, match="not valid JSON"):
            _parse_generation_response(msg)

    def test_truncates_long_style_field(self):
        long_style = "lo-fi, " + ("jazz, " * 300)
        response_text = json.dumps({
            "prompts": [{"style_field": long_style}],
            "theory_reasoning": "Test",
            "suggested_titles": ["Test"],
        })
        msg = MockMessage(response_text)
        prompts, _, _ = _parse_generation_response(msg)
        from music_curation.constants import STYLE_FIELD_MAX_CHARS
        assert len(prompts[0].style_field) <= STYLE_FIELD_MAX_CHARS

    def test_multiple_variants(self):
        response_text = json.dumps({
            "prompts": [
                {"style_field": "lo-fi, 80 BPM, jazz piano, vinyl"},
                {"style_field": "lo-fi, 72 BPM, sad piano, tape hiss"},
            ],
            "theory_reasoning": "Two variants at different tempos.",
            "suggested_titles": ["Chill", "Sad"],
        })
        msg = MockMessage(response_text)
        prompts, _, titles = _parse_generation_response(msg)
        assert len(prompts) == 2
        assert len(titles) == 2


class TestDelegationTrigger:
    def _make_trigger(self):
        curation_store = MagicMock()
        memory_store = MagicMock()
        return DelegationTrigger(curation_store, memory_store)

    @pytest.mark.asyncio
    async def test_local_when_high_score(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext(
            suno_facts=[(DELEGATION_SUNO_FEATURE_THRESHOLD + 0.1, "fact", {})]
        )
        result = await trigger.check("how do I use the suno syntax for stems", ctx)
        assert result == "local"

    @pytest.mark.asyncio
    async def test_retrieve_when_low_score_suno_feature(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext(
            suno_facts=[(DELEGATION_SUNO_FEATURE_THRESHOLD - 0.2, "fact", {})]
        )
        result = await trigger.check("how do I use the suno syntax for stems", ctx)
        assert result == "retrieve"

    @pytest.mark.asyncio
    async def test_retrieve_when_theory_question_no_context(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext()
        result = await trigger.check("why does this chord progression work", ctx)
        assert result == "retrieve"

    @pytest.mark.asyncio
    async def test_local_when_theory_question_has_tutorial(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext(
            tutorial_hits=[(DELEGATION_MUSIC_THEORY_THRESHOLD + 0.1, "theory content")]
        )
        result = await trigger.check("why does this chord progression sound melancholic", ctx)
        assert result == "local"

    @pytest.mark.asyncio
    async def test_retrieve_when_artist_ref_no_context(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext()
        result = await trigger.check("something inspired by Nujabes", ctx)
        assert result == "retrieve"

    @pytest.mark.asyncio
    async def test_local_when_no_triggers(self):
        trigger = self._make_trigger()
        ctx = RetrievedContext()
        result = await trigger.check("lo-fi, 80 BPM, chill and relaxing", ctx)
        assert result == "local"


class TestMissingTitles:
    """Bug D regression: suggested_titles must be present and specific; no silent fallback."""

    def _response_with_titles(self, titles: list[str]) -> MockMessage:
        return MockMessage(json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass", "lyrics_field": None}],
            "theory_reasoning": "Heavy underground.",
            "suggested_titles": titles,
        }))

    def test_valid_titles_accepted(self):
        msg = self._response_with_titles(["Memphis Night Drive"])
        prompts, _, titles = _parse_generation_response(msg)
        assert titles == ["Memphis Night Drive"]

    def test_missing_titles_key_raises(self):
        msg = MockMessage(json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass"}],
            "theory_reasoning": "Heavy.",
        }))
        with pytest.raises(MissingTitlesError):
            _parse_generation_response(msg)

    def test_generic_fallback_string_raises(self):
        msg = self._response_with_titles(["Generated Prompt"])
        with pytest.raises(MissingTitlesError, match="specific"):
            _parse_generation_response(msg)

    def test_empty_title_string_raises(self):
        msg = self._response_with_titles([""])
        with pytest.raises(MissingTitlesError):
            _parse_generation_response(msg)

    def test_fewer_titles_than_prompts_raises(self):
        msg = MockMessage(json.dumps({
            "prompts": [
                {"style_field": "phonk, 135 BPM, heavy 808"},
                {"style_field": "lo-fi phonk, 80 BPM, cowbell"},
            ],
            "theory_reasoning": "Two variants.",
            "suggested_titles": ["Only One Title"],
        }))
        with pytest.raises(MissingTitlesError):
            _parse_generation_response(msg)

    @pytest.mark.asyncio
    async def test_generate_prompts_retries_on_missing_titles(self):
        """generate_prompts retries once when titles are missing; does not return fallback."""
        from music_curation.chains import generate_prompts
        from music_curation.retrieval import RetrievedContext

        bad_response = MockMessage(json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass"}],
            "theory_reasoning": "Heavy.",
            # No suggested_titles
        }))
        good_response = MockMessage(json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass"}],
            "theory_reasoning": "Heavy underground phonk.",
            "suggested_titles": ["130 Raw Memphis Phonk"],
        }))

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=[bad_response, good_response])

        with (
            patch("agent_runtime.budget.get_current_tracker", return_value=None),
            patch("music_curation.chains.record_llm_call"),
        ):
            prompts, _, titles = await generate_prompts("phonk track", RetrievedContext(), mock_client)

        assert mock_client.messages.create.await_count == 2, "should retry once"
        assert titles == ["130 Raw Memphis Phonk"]
        assert "Generated Prompt" not in titles

    @pytest.mark.asyncio
    async def test_generate_prompts_raises_after_two_failures(self):
        """generate_prompts raises MissingTitlesError after both attempts fail — no fallback."""
        from music_curation.chains import generate_prompts
        from music_curation.retrieval import RetrievedContext

        bad_response = MockMessage(json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass"}],
            "theory_reasoning": "Heavy.",
        }))

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=[bad_response, bad_response])

        with (
            patch("agent_runtime.budget.get_current_tracker", return_value=None),
            patch("music_curation.chains.record_llm_call"),
        ):
            with pytest.raises(MissingTitlesError):
                await generate_prompts("phonk track", RetrievedContext(), mock_client)

        assert mock_client.messages.create.await_count == 2


class TestRecordLlm:
    """Regression tests for the cost-aggregation bug (Bugs A and C).

    record_llm_call emits the trace event but never touches BudgetTracker._consumption.
    _record_llm must route through add_llm_cost when a tracker is active so that
    cost_usd and llm_calls accumulate correctly in the run_end summary.
    """

    def test_routes_through_tracker_when_active(self):
        from unittest.mock import patch, MagicMock
        mock_tracker = MagicMock()
        with patch("agent_runtime.budget.get_current_tracker", return_value=mock_tracker):
            _record_llm("claude-sonnet-4-6", 500, 200)
        mock_tracker.add_llm_cost.assert_called_once_with("claude-sonnet-4-6", 500, 200)

    def test_does_not_double_emit_record_llm_call_when_tracker_active(self):
        from unittest.mock import patch, MagicMock
        mock_tracker = MagicMock()
        with (
            patch("agent_runtime.budget.get_current_tracker", return_value=mock_tracker),
            patch("music_curation.chains.record_llm_call") as mock_record,
        ):
            _record_llm("claude-sonnet-4-6", 500, 200)
        # add_llm_cost calls record_llm_call internally; _record_llm must NOT also call it
        mock_record.assert_not_called()

    def test_falls_back_to_direct_emit_when_no_tracker(self):
        from unittest.mock import patch
        with (
            patch("agent_runtime.budget.get_current_tracker", return_value=None),
            patch("music_curation.chains.record_llm_call") as mock_record,
        ):
            _record_llm("claude-sonnet-4-6", 500, 200)
        mock_record.assert_called_once()
        args = mock_record.call_args[0]
        assert args[0] == "claude-sonnet-4-6"
        assert args[1] == 500
        assert args[2] == 200
        assert args[3] > 0  # cost must be non-zero

    def test_tracker_consumption_increments_on_generate(self):
        """Integration: generate_prompts increments tracker cost via _record_llm."""
        import asyncio, json
        from unittest.mock import patch, AsyncMock, MagicMock
        from music_curation.chains import generate_prompts
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker

        response_text = json.dumps({
            "prompts": [{"style_field": "phonk, 135 BPM, heavy 808 bass", "lyrics_field": None}],
            "theory_reasoning": "Heavy and underground.",
            "suggested_titles": ["Memphis Drive"],
        })
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=response_text)]
        mock_msg.usage = MagicMock(input_tokens=300, output_tokens=150)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        from music_curation.retrieval import RetrievedContext

        async def run():
            envelope = BudgetEnvelope(
                max_items=1, max_depth=0, max_cost_usd=5.0, max_wall_time_sec=300
            )
            async with BudgetTracker(envelope, "test-agent") as tracker:
                ctx = RetrievedContext()
                await generate_prompts("phonk track", ctx, mock_client)
                return tracker._consumption.cost_usd, tracker._consumption.llm_calls

        with patch("agent_runtime.tracing.decorators._emit_to_persister"):
            cost, calls = asyncio.run(run())

        assert cost > 0, f"cost_usd should be > 0, got {cost}"
        assert calls == 1, f"llm_calls should be 1, got {calls}"
