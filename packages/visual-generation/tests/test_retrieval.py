from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.constants import (
    COMFYUI_MECHANICS_DOMAIN,
    MECHANICS_DOMAINS,
    RUNPOD_MECHANICS_DOMAIN,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate
from visual_generation.retrieval import (
    RetrievedContext,
    build_context_prompt,
    retrieve_context,
)


def _gen(**overrides) -> VisualGeneration:
    base = dict(caption="neon alley", prompt="cyberpunk, neon", model="flux1-dev")
    base.update(overrides)
    return VisualGeneration(**base)


def _lesson() -> TechniqueLesson:
    return TechniqueLesson(
        statement="CFG above 7 washes skin on flux1-dev.",
        valence="negative",
        scope="settings",
        confirmed=True,
    )


def _template() -> WorkflowTemplate:
    return WorkflowTemplate(name="flux-txt2img", descriptor="basic flux still", required_models=["flux1-dev"])


def _make_store(gens=None, lessons=None, templates=None) -> MagicMock:
    store = MagicMock()
    store.search_generations = AsyncMock(return_value=gens if gens is not None else [])
    store.search_lessons = AsyncMock(return_value=lessons if lessons is not None else [])
    store.search_templates = AsyncMock(return_value=templates if templates is not None else [])
    return store


def _make_memory(facts_raw=None, tutorial_results=None) -> MagicMock:
    mem = MagicMock()
    mem.embedding_client = MagicMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mem.query_by_vector = AsyncMock(return_value=facts_raw if facts_raw is not None else [])
    mem.search = AsyncMock(return_value=tutorial_results if tutorial_results is not None else [])
    return mem


# ── Composition ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_composes_all_legs() -> None:
    gen = _gen()
    lesson = _lesson()
    tmpl = _template()
    store = _make_store(
        gens=[(gen.entry_id, 0.9, gen)],
        lessons=[(lesson.entry_id, 0.8, lesson)],
        templates=[(tmpl.entry_id, 0.7, tmpl)],
    )
    facts_raw = [("kid", 0.6, {"statement": "Flux uses CFG=1.0", "domain": COMFYUI_MECHANICS_DOMAIN})]
    tutorial = [SimpleNamespace(score=0.5, point=SimpleNamespace(text="tutorial chunk", caption=None))]
    mem = _make_memory(facts_raw=facts_raw, tutorial_results=tutorial)

    ctx = await retrieve_context("neon cyberpunk alley", store, mem)

    assert len(ctx.prior_generations) == 1
    assert len(ctx.technique_lessons) == 1
    assert len(ctx.workflow_templates) == 1
    assert len(ctx.comfyui_facts) == 1
    assert len(ctx.tutorial_hits) == 1
    assert not ctx.is_empty()


@pytest.mark.asyncio
async def test_user_knowledge_boost_and_two_domain_filter() -> None:
    facts_raw = [("kid", 0.6, {"statement": "fact A", "domain": RUNPOD_MECHANICS_DOMAIN})]
    mem = _make_memory(facts_raw=facts_raw)
    store = _make_store()

    ctx = await retrieve_context("q", store, mem)

    # Boost applied.
    score, statement, _payload = ctx.comfyui_facts[0]
    assert score == pytest.approx(0.6 * USER_KNOWLEDGE_SCORE_MULTIPLIER)
    assert statement == "fact A"

    # Filter: either mechanics domain (MatchAny) + active sentinel "".
    filters = mem.query_by_vector.call_args.kwargs["filters"]
    by_key = {c.key: c for c in filters.must}
    assert by_key["domain"].match.any == MECHANICS_DOMAINS
    assert by_key["superseded_by"].match.value == ""


@pytest.mark.asyncio
async def test_tutorial_leg_surfaces_text_not_content_type() -> None:
    # Regression guard: content_type is a label ("text"); the real chunk is .text.
    tutorial = [SimpleNamespace(score=0.5, point=SimpleNamespace(text="real chunk", caption=None))]
    mem = _make_memory(tutorial_results=tutorial)
    store = _make_store()
    ctx = await retrieve_context("q", store, mem)
    assert ctx.tutorial_hits == [(0.5, "real chunk")]


@pytest.mark.asyncio
async def test_generation_rating_tiebreaker() -> None:
    low = _gen(rating=3)
    high = _gen(rating=5)
    store = _make_store(gens=[(low.entry_id, 0.8, low), (high.entry_id, 0.8, high)])
    mem = _make_memory()
    ctx = await retrieve_context("q", store, mem)
    # Equal score → higher rating first.
    assert ctx.prior_generations[0][1].rating == 5


# ── Silent degradation / cold-start ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_start_all_empty() -> None:
    store = _make_store()
    mem = _make_memory()
    ctx = await retrieve_context("q", store, mem)
    assert ctx.is_empty()
    assert ctx.max_local_score() == 0.0


@pytest.mark.asyncio
async def test_own_collection_leg_failure_degrades_silently() -> None:
    store = _make_store()
    store.search_generations = AsyncMock(side_effect=RuntimeError("qdrant down"))
    mem = _make_memory(
        tutorial_results=[SimpleNamespace(score=0.4, point=SimpleNamespace(text="t", caption=None))]
    )
    ctx = await retrieve_context("q", store, mem)
    # The failed leg is empty; the others still populate.
    assert ctx.prior_generations == []
    assert ctx.tutorial_hits == [(0.4, "t")]


@pytest.mark.asyncio
async def test_user_knowledge_leg_failure_degrades_silently() -> None:
    store = _make_store()
    mem = _make_memory()
    mem.query_by_vector = AsyncMock(side_effect=RuntimeError("no user_knowledge collection"))
    ctx = await retrieve_context("q", store, mem)
    assert ctx.comfyui_facts == []


@pytest.mark.asyncio
async def test_tutorial_excluded_when_flag_off() -> None:
    store = _make_store()
    mem = _make_memory(
        tutorial_results=[SimpleNamespace(score=0.4, point=SimpleNamespace(text="t", caption=None))]
    )
    ctx = await retrieve_context("q", store, mem, include_tutorial=False)
    assert ctx.tutorial_hits == []
    mem.search.assert_not_called()


# ── build_context_prompt ─────────────────────────────────────────────────────


def test_build_context_prompt_tags_sources() -> None:
    ctx = RetrievedContext(
        prior_generations=[(0.9, _gen(reaction="loved", rating=5))],
        technique_lessons=[(0.8, _lesson())],
        comfyui_facts=[(0.7, "Flux uses CFG=1.0", {"domain": COMFYUI_MECHANICS_DOMAIN})],
        tutorial_hits=[(0.5, "tutorial chunk")],
        workflow_templates=[(0.6, _template())],
    )
    out = build_context_prompt(ctx)
    assert "[PRIOR GENERATION:" in out
    assert "[TECHNIQUE LESSON: negative/settings" in out
    assert f"[USER FACT: {COMFYUI_MECHANICS_DOMAIN}" in out
    assert "[TUTORIAL KNOWLEDGE" in out
    assert "[WORKFLOW TEMPLATE: flux-txt2img" in out


def test_build_context_prompt_render_failed_note() -> None:
    ctx = RetrievedContext(prior_generations=[(0.9, _gen(reaction="render_failed"))])
    out = build_context_prompt(ctx)
    assert "mis-rendered" in out


def test_build_context_prompt_empty() -> None:
    assert build_context_prompt(RetrievedContext()) == ""
