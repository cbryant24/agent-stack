from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.constants import (
    CANON_DOMAINS,
    CANON_SCORE_MULTIPLIER,
    COMFYUI_MECHANICS_DOMAIN,
    MECHANICS_DOMAINS,
    RUNPOD_MECHANICS_DOMAIN,
    TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
    TECHNIQUE_VISUAL_SCOPES,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
    VISUAL_GENERATION_CANON_DOMAIN,
)
from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate
from visual_generation.retrieval import (
    RetrievedContext,
    build_context_prompt,
    retrieve_context,
    summarize_provenance,
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


def _domains_of(filters) -> list[str] | None:
    """Pull the `domain` MatchAny values out of a must-filter (or None)."""
    if filters is None:
        return None
    for cond in filters.must or []:
        if cond.key == "domain":
            return cond.match.any
    return None


def _tech_point(text="storybook stop-motion technique", title="Illustrated Storybook Visual Generation"):
    """A technique_research_outputs point shaped like a real MemoryPoint.

    Tagged the way the technique-research agent actually writes them:
    `domain_tags` = freeform technique title, `topic_tags` = [scope] where scope
    ∈ {editing, generation, both}. A visual report is scoped `both` (or
    `generation`) — NOT the tutorial_research tag vocabulary."""
    return SimpleNamespace(
        text=text,
        caption=None,
        source_title=title,
        domain_tags=[title],
        topic_tags=["both"],
    )


def _make_memory(
    facts_raw=None, canon_raw=None, tutorial_results=None, technique_results=None
) -> MagicMock:
    """A fake MemoryStore whose query_by_vector dispatches by domain filter
    (mechanics vs canon) and whose search dispatches by collection name."""
    mem = MagicMock()
    mem.embedding_client = MagicMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])

    async def _qbv(collection, vector, *, limit=10, filters=None):
        if _domains_of(filters) == CANON_DOMAINS:
            return canon_raw if canon_raw is not None else []
        return facts_raw if facts_raw is not None else []

    mem.query_by_vector = AsyncMock(side_effect=_qbv)

    async def _search(collection, query, *, limit=10, filters=None):
        if collection == TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION:
            return technique_results if technique_results is not None else []
        return tutorial_results if tutorial_results is not None else []

    mem.search = AsyncMock(side_effect=_search)
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

    # The mechanics query (one of several query_by_vector calls) carries the
    # two-domain MatchAny + active sentinel "". Find it among all calls.
    mechanics_calls = [
        c for c in mem.query_by_vector.call_args_list
        if _domains_of(c.kwargs["filters"]) == MECHANICS_DOMAINS
    ]
    assert len(mechanics_calls) == 1
    by_key = {c.key: c for c in mechanics_calls[0].kwargs["filters"].must}
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
    # The tutorial collection is never searched when the flag is off (the
    # technique-reports leg may still search its own collection).
    searched = [c.args[0] for c in mem.search.call_args_list]
    assert TUTORIAL_RESEARCH_COLLECTION not in searched


# ── Part 1: surfacing the under-read stores ──────────────────────────────────


@pytest.mark.asyncio
async def test_canon_leg_surfaces_and_boosts_highest() -> None:
    canon_raw = [("cid", 0.6, {"statement": "narrator hair to mid-back", "domain": VISUAL_GENERATION_CANON_DOMAIN})]
    mem = _make_memory(canon_raw=canon_raw)
    store = _make_store()
    ctx = await retrieve_context("narrator", store, mem)

    assert len(ctx.canon_facts) == 1
    score, statement, _payload = ctx.canon_facts[0]
    assert statement == "narrator hair to mid-back"
    assert score == pytest.approx(0.6 * CANON_SCORE_MULTIPLIER)

    # The canon query filters on CANON_DOMAINS + active sentinel.
    canon_calls = [
        c for c in mem.query_by_vector.call_args_list
        if _domains_of(c.kwargs["filters"]) == CANON_DOMAINS
    ]
    assert len(canon_calls) == 1
    by_key = {c.key: c for c in canon_calls[0].kwargs["filters"].must}
    assert by_key["superseded_by"].match.value == ""


@pytest.mark.asyncio
async def test_technique_reports_leg_surfaces_visual_tagged() -> None:
    mem = _make_memory(technique_results=[SimpleNamespace(score=0.55, point=_tech_point())])
    store = _make_store()
    ctx = await retrieve_context("stop motion narrator", store, mem)

    assert len(ctx.technique_reports) == 1
    score, content, payload = ctx.technique_reports[0]
    assert score == 0.55
    assert "storybook" in content
    assert payload["source_title"] == "Illustrated Storybook Visual Generation"

    # The leg searches technique_research_outputs filtered on the technique-research
    # SCOPE vocabulary (topic_tags ∈ {generation, both}) — NOT VISUAL_TUTORIAL_TAGS,
    # which uses tutorial_research's tags and matches zero rows here. No unfiltered
    # fallback — editing-scoped noise must stay out.
    tech_calls = [
        c for c in mem.search.call_args_list
        if c.args[0] == TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION
    ]
    assert len(tech_calls) == 1
    must = tech_calls[0].kwargs["filters"].must
    scope_fields = {c.key: c.match.any for c in must}
    assert scope_fields == {"topic_tags": TECHNIQUE_VISUAL_SCOPES}


@pytest.mark.asyncio
async def test_tutorial_leg_applies_visual_tag_filter() -> None:
    tutorial = [SimpleNamespace(score=0.5, point=SimpleNamespace(text="z-image chunk", caption=None))]
    mem = _make_memory(tutorial_results=tutorial)
    store = _make_store()
    ctx = await retrieve_context("z-image turbo", store, mem)

    assert ctx.tutorial_hits == [(0.5, "z-image chunk")]
    tut_calls = [
        c for c in mem.search.call_args_list
        if c.args[0] == TUTORIAL_RESEARCH_COLLECTION
    ]
    # First (and only, since results were non-empty) tutorial search is tag-filtered.
    assert tut_calls[0].kwargs["filters"] is not None
    should = tut_calls[0].kwargs["filters"].should
    assert {c.key for c in should} == {"domain_tags", "topic_tags"}


@pytest.mark.asyncio
async def test_tutorial_leg_falls_back_to_unfiltered_when_no_visual_hits() -> None:
    # First (filtered) search returns nothing → fall back to an unfiltered search.
    async def _search(collection, query, *, limit=10, filters=None):
        if filters is not None:
            return []
        return [SimpleNamespace(score=0.3, point=SimpleNamespace(text="fallback", caption=None))]

    mem = _make_memory()
    mem.search = AsyncMock(side_effect=_search)
    store = _make_store()
    ctx = await retrieve_context("q", store, mem)
    assert ctx.tutorial_hits == [(0.3, "fallback")]


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


def test_build_context_prompt_tags_canon_and_technique_report() -> None:
    ctx = RetrievedContext(
        canon_facts=[(1.0, "narrator hair to mid-back", {"domain": VISUAL_GENERATION_CANON_DOMAIN})],
        technique_reports=[
            (0.55, "stop-motion storybook look", {"source_title": "Illustrated Storybook Visual Generation"})
        ],
    )
    out = build_context_prompt(ctx)
    assert f"[PROJECT CANON: {VISUAL_GENERATION_CANON_DOMAIN}" in out
    assert "LOCKED" in out
    assert "[TECHNIQUE REPORT: Illustrated Storybook Visual Generation" in out
    # Canon is rendered first (highest tier).
    assert out.index("PROJECT CANON") < out.index("TECHNIQUE REPORT")


def test_build_context_prompt_render_failed_note() -> None:
    ctx = RetrievedContext(prior_generations=[(0.9, _gen(reaction="render_failed"))])
    out = build_context_prompt(ctx)
    assert "mis-rendered" in out


def test_build_context_prompt_empty() -> None:
    assert build_context_prompt(RetrievedContext()) == ""


# ── Part 2: provenance summary ─────────────────────────────────────────────────


def test_summarize_provenance_empty() -> None:
    assert summarize_provenance(RetrievedContext()) == []


def test_summarize_provenance_tiers_and_counts() -> None:
    ctx = RetrievedContext(
        canon_facts=[(1.5, "narrator hair to mid-back", {"domain": VISUAL_GENERATION_CANON_DOMAIN})],
        technique_reports=[(0.55, "stop-motion look", {"source_title": "Illustrated Storybook Visual Generation"})],
        tutorial_hits=[(0.5, "z-image chunk"), (0.4, "another")],
    )
    legs = {leg.label: leg for leg in summarize_provenance(ctx)}
    assert legs["Project canon"].tier == "locked"
    assert legs["Project canon"].top_score == 1.5
    assert legs["Technique reports"].tier == "strong"
    # snippet prefers the report's source_title
    assert "Illustrated Storybook" in legs["Technique reports"].snippets[0]
    assert legs["Tutorial research"].tier == "reference"
    assert legs["Tutorial research"].count == 2
    # ordered locked → strong → reference
    order = [leg.label for leg in summarize_provenance(ctx)]
    assert order.index("Project canon") < order.index("Tutorial research")
