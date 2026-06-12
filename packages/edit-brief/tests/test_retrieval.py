from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from edit_brief.retrieval import read_editing_toolset, retrieve_context


def _hit(statement, domain="editing_toolset", score=0.9):
    return SimpleNamespace(statement=statement, domain=domain, score=score)


def _finding_result(meta):
    return SimpleNamespace(point=SimpleNamespace(metadata=meta, text="", source_title="t", source_id="t"))


@pytest.mark.asyncio
async def test_toolset_always_loaded():
    uks = MagicMock()
    uks.search = AsyncMock(return_value=[_hit("DaVinci free has no Studio NR")])
    facts = await read_editing_toolset("color", uks)
    assert facts == ["DaVinci free has no Studio NR"]
    # called with the editing_toolset domain
    assert uks.search.await_args.kwargs["domain"] == "editing_toolset"


@pytest.mark.asyncio
async def test_toolset_degrades_to_empty_on_error():
    uks = MagicMock()
    uks.search = AsyncMock(side_effect=RuntimeError("no collection"))
    assert await read_editing_toolset("x", uks) == []


@pytest.mark.asyncio
async def test_retrieve_context_composes_and_parses_findings(monkeypatch):
    store = MagicMock()

    async def fake_search(collection, query, *, limit=10, filters=None):
        if collection == "technique_research_outputs":
            return [_finding_result({
                "technique": "S-curve grade", "description": "contrast curve",
                "application_notes": "Color page", "toolset_fit": "free Color page",
                "upgrade_flag": "smoother in Studio",
            })]
        if collection == "tutorial_research":
            return [SimpleNamespace(point=SimpleNamespace(
                metadata={}, text="grading basics", source_title="Grade 101", source_id="x"))]
        return []

    store.search = AsyncMock(side_effect=fake_search)

    uks = MagicMock()

    async def fake_uks_search(query, *, domain=None, limit=10):
        if domain == "editing_toolset":
            return [_hit("Resolve free 20.3")]
        return [_hit("use 0.5s gaps", domain="editing_prefs", score=0.7)]

    uks.search = AsyncMock(side_effect=fake_uks_search)

    ctx = await retrieve_context("grading", store, uks)
    assert ctx.toolset == ["Resolve free 20.3"]
    assert ctx.has_findings
    f = ctx.findings[0]
    assert f.technique == "S-curve grade"
    assert f.upgrade_flag == "smoother in Studio"  # carried verbatim
    assert ctx.tutorial and "Grade 101" in ctx.tutorial[0]
    assert ctx.preferences == ["use 0.5s gaps"]  # editing_toolset domain filtered out


@pytest.mark.asyncio
async def test_retrieve_context_degrades_each_leg(monkeypatch):
    store = MagicMock()
    store.search = AsyncMock(side_effect=RuntimeError("down"))
    uks = MagicMock()
    uks.search = AsyncMock(side_effect=RuntimeError("down"))
    ctx = await retrieve_context("x", store, uks)
    assert ctx.toolset == [] and ctx.findings == [] and not ctx.has_findings
