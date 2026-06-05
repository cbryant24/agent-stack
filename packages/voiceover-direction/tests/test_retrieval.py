from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from voiceover_direction.constants import (
    ELEVENLABS_MECHANICS_DOMAIN,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from voiceover_direction.models import DirectionLesson, Take
from voiceover_direction.retrieval import (
    RetrievedContext,
    build_context_prompt,
    retrieve_context,
)


def _take(**overrides) -> Take:
    base = dict(text="Welcome back.", voice_id="v1", model="eleven_v3",
                section_id="intro", project_id="p1")
    base.update(overrides)
    return Take(**base)


def _lesson() -> DirectionLesson:
    return DirectionLesson(statement="Slow down on emotional beats.", valence="positive",
                           scope="pacing", confirmed=True)


def _make_store(takes=None, lessons=None) -> MagicMock:
    store = MagicMock()
    store.search_takes = AsyncMock(return_value=takes if takes is not None else [])
    store.search_lessons = AsyncMock(return_value=lessons if lessons is not None else [])
    return store


def _make_memory(facts_raw=None, tutorial_results=None) -> MagicMock:
    mem = MagicMock()
    mem.embedding_client = MagicMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mem.query_by_vector = AsyncMock(return_value=facts_raw if facts_raw is not None else [])
    mem.search = AsyncMock(return_value=tutorial_results if tutorial_results is not None else [])
    return mem


@pytest.mark.asyncio
async def test_composes_all_legs() -> None:
    take = _take()
    lesson = _lesson()
    store = _make_store(
        takes=[(take.entry_id, 0.9, take)],
        lessons=[(lesson.entry_id, 0.8, lesson)],
    )
    facts_raw = [("kid", 0.6, {"statement": "eleven_v3 reads audio tags"})]
    tutorial = [SimpleNamespace(score=0.5, point=SimpleNamespace(text="tutorial chunk", caption=None))]
    mem = _make_memory(facts_raw=facts_raw, tutorial_results=tutorial)

    ctx = await retrieve_context("calm intro", store, mem)

    assert len(ctx.prior_takes) == 1
    assert len(ctx.direction_lessons) == 1
    assert len(ctx.elevenlabs_facts) == 1
    assert len(ctx.tutorial_hits) == 1


@pytest.mark.asyncio
async def test_user_knowledge_boost_and_filter() -> None:
    facts_raw = [("kid", 0.6, {"statement": "fact A"})]
    mem = _make_memory(facts_raw=facts_raw)
    store = _make_store()

    ctx = await retrieve_context("q", store, mem)

    # Boost applied.
    score, statement, _payload = ctx.elevenlabs_facts[0]
    assert score == pytest.approx(0.6 * USER_KNOWLEDGE_SCORE_MULTIPLIER)
    assert statement == "fact A"

    # Filter keys are the real payload fields and use the active sentinel "".
    filters = mem.query_by_vector.call_args.kwargs["filters"]
    matched = {c.key: c.match.value for c in filters.must}
    assert matched["domain"] == ELEVENLABS_MECHANICS_DOMAIN
    assert matched["superseded_by"] == ""


@pytest.mark.asyncio
async def test_tutorial_leg_surfaces_text_not_content_type() -> None:
    # Regression guard: content_type is a label ("text"); the real chunk is .text.
    point = SimpleNamespace(text="the real chunk body", caption=None, content_type="text")
    mem = _make_memory(tutorial_results=[SimpleNamespace(score=0.7, point=point)])
    store = _make_store()

    ctx = await retrieve_context("q", store, mem)

    assert ctx.tutorial_hits == [(0.7, "the real chunk body")]


@pytest.mark.asyncio
async def test_tutorial_leg_falls_back_to_caption_for_image_points() -> None:
    point = SimpleNamespace(text="", caption="a labelled diagram", content_type="image_with_caption")
    mem = _make_memory(tutorial_results=[SimpleNamespace(score=0.4, point=point)])
    ctx = await retrieve_context("q", _make_store(), mem)
    assert ctx.tutorial_hits == [(0.4, "a labelled diagram")]


@pytest.mark.asyncio
async def test_each_leg_degrades_silently() -> None:
    store = _make_store()
    store.search_takes = AsyncMock(side_effect=Exception("takes down"))
    store.search_lessons = AsyncMock(side_effect=Exception("lessons down"))
    mem = _make_memory()
    mem.query_by_vector = AsyncMock(side_effect=Exception("qdrant down"))
    mem.search = AsyncMock(side_effect=Exception("tutorial down"))

    ctx = await retrieve_context("q", store, mem)

    assert ctx.is_empty()  # nothing raised; cold-start-safe


@pytest.mark.asyncio
async def test_prior_takes_sorted_by_score_then_rating() -> None:
    low = _take(section_id="a")
    hi = _take(section_id="b", reaction="loved", rating=5)
    store = _make_store(takes=[(low.entry_id, 0.5, low), (hi.entry_id, 0.9, hi)])
    ctx = await retrieve_context("q", store, _make_memory())
    assert ctx.prior_takes[0][1].section_id == "b"  # higher score first


def test_build_context_prompt_emits_source_tags() -> None:
    take = _take(reaction="loved", rating=4, emotion_tags=["[whispers]"])
    lesson = _lesson()
    ctx = RetrievedContext(
        prior_takes=[(0.9, take)],
        direction_lessons=[(0.8, lesson)],
        elevenlabs_facts=[(0.7, "eleven_v3 reads tags", {})],
        tutorial_hits=[(0.6, "a tutorial note")],
    )
    block = build_context_prompt(ctx)
    assert "[PRIOR TAKE: reaction=LOVED" in block
    assert "[DIRECTION LESSON: positive/pacing" in block
    assert "[USER FACT: elevenlabs_mechanics" in block
    assert "[TUTORIAL KNOWLEDGE" in block


def test_is_empty_cold_start() -> None:
    assert RetrievedContext().is_empty()
    assert build_context_prompt(RetrievedContext()) == ""


def test_render_failed_take_annotated_territory_open() -> None:
    take = _take(reaction="render_failed")
    block = build_context_prompt(RetrievedContext(prior_takes=[(0.8, take)]))
    assert "territory is still open" in block
    assert "do not abandon the direction" in block


def test_disliked_take_not_annotated_territory_open() -> None:
    take = _take(reaction="disliked")
    block = build_context_prompt(RetrievedContext(prior_takes=[(0.8, take)]))
    # disliked weighs against the territory by its label; it gets no "still open" note.
    assert "territory is still open" not in block
    assert "[PRIOR TAKE: reaction=DISLIKED" in block
