from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_curation.models import Generation, TasteLesson
from music_curation.retrieval import RetrievedContext, build_context_prompt, retrieve_context
from music_curation.constants import (
    REACTION_LOVED,
    REACTION_LIKED,
    REACTION_PROMPT_FAILED,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)


def _make_curation_store(
    gen_results=None,
    taste_results=None,
    tmpl_results=None,
):
    store = MagicMock()
    store.search_generations = AsyncMock(return_value=gen_results or [])
    store.search_taste = AsyncMock(return_value=taste_results or [])
    store.search_templates = AsyncMock(return_value=tmpl_results or [])
    return store


def _make_memory_store():
    store = MagicMock()
    store.embedding_client = MagicMock()
    store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    store.query_by_vector = AsyncMock(return_value=[])
    store.search = AsyncMock(return_value=[])
    return store


class TestRetrievedContext:
    def test_is_empty_when_no_results(self):
        ctx = RetrievedContext()
        assert ctx.is_empty()

    def test_not_empty_with_generations(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz")
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        assert not ctx.is_empty()

    def test_max_local_score_empty(self):
        ctx = RetrievedContext()
        assert ctx.max_local_score() == 0.0

    def test_max_local_score_with_data(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, vinyl")
        ctx = RetrievedContext(
            prior_generations=[(0.85, gen)],
            suno_facts=[(0.92, "Suno adds drums by default", {})],
        )
        assert ctx.max_local_score() == 0.92

    def test_max_user_knowledge_score(self):
        ctx = RetrievedContext(
            suno_facts=[(0.88, "char limit is 1000", {})],
        )
        assert ctx.max_user_knowledge_score() == 0.88


class TestRetrieveContext:
    @pytest.mark.asyncio
    async def test_parallel_fetch_all_collections(self):
        curation_store = _make_curation_store()
        memory_store = _make_memory_store()

        ctx = await retrieve_context("lo-fi phonk", curation_store, memory_store)

        curation_store.search_generations.assert_awaited_once()
        curation_store.search_taste.assert_awaited_once()
        curation_store.search_templates.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_empty_context_when_no_results(self):
        curation_store = _make_curation_store()
        memory_store = _make_memory_store()

        ctx = await retrieve_context("test query", curation_store, memory_store)
        assert ctx.is_empty()

    @pytest.mark.asyncio
    async def test_generation_results_converted_to_tuples(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, vinyl crackle", reaction=REACTION_LOVED)
        curation_store = _make_curation_store(
            gen_results=[("id1", 0.90, gen)]
        )
        memory_store = _make_memory_store()

        ctx = await retrieve_context("lo-fi", curation_store, memory_store)
        assert len(ctx.prior_generations) == 1
        score, returned_gen = ctx.prior_generations[0]
        assert score == 0.90
        assert returned_gen.reaction == REACTION_LOVED

    @pytest.mark.asyncio
    async def test_tutorial_skipped_when_disabled(self):
        curation_store = _make_curation_store()
        memory_store = _make_memory_store()

        ctx = await retrieve_context(
            "test", curation_store, memory_store, include_tutorial=False
        )
        memory_store.search.assert_not_called()
        assert ctx.tutorial_hits == []

    @pytest.mark.asyncio
    async def test_graceful_degrade_on_exception(self):
        curation_store = _make_curation_store()
        curation_store.search_taste = AsyncMock(side_effect=Exception("Qdrant error"))
        memory_store = _make_memory_store()

        # Should not raise
        ctx = await retrieve_context("test", curation_store, memory_store)
        assert ctx.taste_lessons == []


class TestBuildContextPrompt:
    def test_empty_context(self):
        ctx = RetrievedContext()
        assert build_context_prompt(ctx) == ""

    def test_generation_block_present(self):
        gen = Generation(
            session_id="s",
            style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_LOVED,
            suggested_track_title="Memphis Night Drive",
        )
        ctx = RetrievedContext(prior_generations=[(0.92, gen)])
        prompt = build_context_prompt(ctx)
        assert "[PRIOR GENERATION" in prompt
        assert "LOVED" in prompt
        assert "Memphis Night Drive" in prompt

    def test_taste_block_present(self):
        lesson = TasteLesson(
            statement="User loves Memphis cowbell in phonk",
            valence="positive",
            scope="instrumentation",
            confirmed=True,
        )
        ctx = RetrievedContext(taste_lessons=[(0.85, lesson)])
        prompt = build_context_prompt(ctx)
        assert "[TASTE:" in prompt
        assert "Memphis cowbell" in prompt

    def test_suno_fact_block_present(self):
        ctx = RetrievedContext(
            suno_facts=[(0.9, "Suno adds drums by default", {"domain": "suno_mechanics"})]
        )
        prompt = build_context_prompt(ctx)
        assert "[USER FACT:" in prompt
        assert "Suno adds drums" in prompt

    def test_tutorial_block_present(self):
        ctx = RetrievedContext(
            tutorial_hits=[(0.75, "The chord progression I vi IV V creates...")]
        )
        prompt = build_context_prompt(ctx)
        assert "[TUTORIAL KNOWLEDGE" in prompt

    def test_all_sections_present(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, vinyl")
        lesson = TasteLesson(statement="likes vinyl texture", valence="positive", scope="production", confirmed=True)
        ctx = RetrievedContext(
            prior_generations=[(0.9, gen)],
            taste_lessons=[(0.8, lesson)],
            suno_facts=[(0.85, "Suno fact text", {})],
            tutorial_hits=[(0.7, "Tutorial content")],
        )
        prompt = build_context_prompt(ctx)
        assert "Prior Generations" in prompt
        assert "User Taste" in prompt
        assert "Suno Knowledge" in prompt
        assert "Tutorial Research" in prompt

    # ── Change 3 + 4: rating and context surface in the block; notes does NOT ──
    def test_context_included_in_prior_generation_block(self):
        gen = Generation(
            session_id="s", style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_LOVED,
            context="the cowbell placement matches the Memphis tradition I love",
            notes="slow it down next time",
        )
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "context=" in prompt
        assert "Memphis tradition" in prompt

    def test_notes_excluded_from_prior_generation_block(self):
        gen = Generation(
            session_id="s", style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_LOVED,
            notes="slow it down next time",
        )
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "slow it down next time" not in prompt

    def test_rating_included_when_present(self):
        gen = Generation(
            session_id="s", style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_LOVED, rating=5,
        )
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "rating=5" in prompt

    def test_rating_absent_when_none(self):
        gen = Generation(session_id="s", style_field="phonk, 135 BPM, heavy 808", reaction=REACTION_LIKED)
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "rating=" not in prompt

    def test_prompt_failed_annotated_as_territory_open(self):
        gen = Generation(
            session_id="s", style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_PROMPT_FAILED,
        )
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "PROMPT FAILED" in prompt
        assert "territory is still open" in prompt

    def test_disliked_not_annotated_as_territory_open(self):
        from music_curation.constants import REACTION_DISLIKED
        gen = Generation(
            session_id="s", style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_DISLIKED,
        )
        ctx = RetrievedContext(prior_generations=[(0.9, gen)])
        prompt = build_context_prompt(ctx)
        assert "territory is still open" not in prompt


class TestRatingTiebreaker:
    """Change 3: equal-similarity matches ordered by rating descending."""

    @pytest.mark.asyncio
    async def test_higher_rating_outranks_on_equal_score(self):
        low = Generation(session_id="s", style_field="phonk, 130 BPM, 808", reaction=REACTION_LOVED, rating=3)
        high = Generation(session_id="s", style_field="phonk, 132 BPM, 808", reaction=REACTION_LOVED, rating=5)
        # Both returned at the SAME similarity score, low listed first by Qdrant.
        curation_store = _make_curation_store(
            gen_results=[("id_low", 0.80, low), ("id_high", 0.80, high)]
        )
        memory_store = _make_memory_store()
        ctx = await retrieve_context("phonk", curation_store, memory_store, include_tutorial=False)
        # After the tiebreaker, the rating-5 entry comes first.
        assert ctx.prior_generations[0][1].rating == 5
        assert ctx.prior_generations[1][1].rating == 3

    @pytest.mark.asyncio
    async def test_score_still_dominates_over_rating(self):
        better_match = Generation(session_id="s", style_field="phonk A", reaction=REACTION_LOVED, rating=2)
        worse_match = Generation(session_id="s", style_field="phonk B", reaction=REACTION_LOVED, rating=5)
        curation_store = _make_curation_store(
            gen_results=[("id1", 0.95, better_match), ("id2", 0.60, worse_match)]
        )
        memory_store = _make_memory_store()
        ctx = await retrieve_context("phonk", curation_store, memory_store, include_tutorial=False)
        # Higher similarity wins regardless of lower rating.
        assert ctx.prior_generations[0][0] == 0.95
        assert ctx.prior_generations[0][1].rating == 2
