from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import technique_research.retrieval as r
from technique_research.models import TechniqueDomain


def _domain() -> TechniqueDomain:
    return TechniqueDomain(name="Color grading", why_it_matters="look", search_query="teal orange grade")


def _wire(monkeypatch, *, own, tutorial, uk):
    """Patch the three check legs to fixed max scores and capture the decision events."""
    calls: list[dict] = []
    monkeypatch.setattr(r, "record_delegation_decision", lambda **k: calls.append(k))
    monkeypatch.setattr(
        r, "retrieve_chunks",
        AsyncMock(return_value=[SimpleNamespace(score=tutorial)] if tutorial else []),
    )
    store = MagicMock()
    store.search_findings = AsyncMock(
        return_value=[(own, MagicMock())] if own else []
    )
    uks = MagicMock()
    uks.search = AsyncMock(return_value=[SimpleNamespace(score=uk)] if uk else [])
    return store, uks, calls


@pytest.mark.asyncio
async def test_delegates_when_all_legs_below_threshold(monkeypatch) -> None:
    store, uks, calls = _wire(monkeypatch, own=0.10, tutorial=0.20, uk=0.30)
    outcome = await r.check_domain(_domain(), store, MagicMock(), uks)
    assert outcome.decision == "delegate"
    # One decision event per collection leg.
    assert len(calls) == 3
    assert {c["collection"] for c in calls} == {
        "technique_research_outputs", "tutorial_research", "user_knowledge",
    }


@pytest.mark.asyncio
async def test_local_when_any_leg_clears_threshold(monkeypatch) -> None:
    # Own findings clear CHECK_TECHNIQUE_OUTPUTS_THRESHOLD (0.70) even though the
    # other two legs are weak.
    store, uks, _ = _wire(monkeypatch, own=0.92, tutorial=0.10, uk=0.10)
    outcome = await r.check_domain(_domain(), store, MagicMock(), uks)
    assert outcome.decision == "local"
    assert outcome.technique_outputs_score == 0.92


@pytest.mark.asyncio
async def test_empty_everywhere_delegates(monkeypatch) -> None:
    store, uks, _ = _wire(monkeypatch, own=0.0, tutorial=0.0, uk=0.0)
    outcome = await r.check_domain(_domain(), store, MagicMock(), uks)
    assert outcome.decision == "delegate"


@pytest.mark.asyncio
async def test_read_editing_toolset_formats_hits(monkeypatch) -> None:
    uks = MagicMock()
    uks.search = AsyncMock(return_value=[
        SimpleNamespace(statement="DaVinci Resolve free 20.3.1"),
        SimpleNamespace(statement="Topaz Video AI used headlessly"),
    ])
    out = await r.read_editing_toolset("denoise", uks)
    assert "DaVinci Resolve free 20.3.1" in out and "Topaz" in out
    # The query is scoped to the editing_toolset domain — never hardcoded facts.
    assert uks.search.call_args.kwargs["domain"] == "editing_toolset"


@pytest.mark.asyncio
async def test_read_editing_toolset_degrades_to_empty(monkeypatch) -> None:
    uks = MagicMock()
    uks.search = AsyncMock(side_effect=RuntimeError("collection missing"))
    assert await r.read_editing_toolset("x", uks) == ""
