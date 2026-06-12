"""The identify→gate→delegate orchestration, with collaborators mocked but the
real BudgetTracker running (so budget/tracing lifecycle is exercised)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import technique_research.agent as a
from technique_research.models import CheckOutcome, IdentificationInput, TechniqueDomain


def _domain(name: str) -> TechniqueDomain:
    return TechniqueDomain(name=name, why_it_matters="matters", search_query=f"{name} query")


def _outcome(name: str, decision: str) -> CheckOutcome:
    return CheckOutcome(domain_name=name, decision=decision)


def _deleg_result():
    return SimpleNamespace(status="completed", result={"run_id": "tr-1", "items_processed": 2})


def _wire(monkeypatch, *, domains, outcomes, delegate_mock):
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.search_findings = AsyncMock(return_value=[])
    store.upsert_findings = AsyncMock(return_value=["fid-1"])

    monkeypatch.setattr(a, "AsyncAnthropic", lambda **k: MagicMock())
    monkeypatch.setattr(a, "get_memory_store", lambda: MagicMock())
    monkeypatch.setattr(a, "TechniqueResearchStore", lambda ms: store)
    monkeypatch.setattr(a, "UserKnowledgeStore", lambda ms: MagicMock())
    monkeypatch.setattr(a, "register_delegate_handlers", lambda: None)
    monkeypatch.setattr(a, "read_editing_toolset", AsyncMock(return_value="TOOLSET"))
    monkeypatch.setattr(a, "fetch_url_context", AsyncMock(return_value=None))
    monkeypatch.setattr(a, "tavily_reference_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(a, "assess_reference", AsyncMock(
        return_value={"needs_grounding": False, "tavily_query": None, "preliminary_summary": "s"}))
    monkeypatch.setattr(a, "identify_techniques",
                        AsyncMock(return_value=(domains, "grounded summary", "editing")))

    outcome_by_name = {o.domain_name: o for o in outcomes}

    async def fake_check(d, *args):
        return outcome_by_name[d.name]

    monkeypatch.setattr(a, "check_domain", fake_check)
    monkeypatch.setattr(a, "_gather_material", AsyncMock(return_value="material"))
    monkeypatch.setattr(a, "curate_findings",
                        AsyncMock(return_value=[{"technique": "T1", "description": "d"}]))
    monkeypatch.setattr(a, "delegate", delegate_mock)
    monkeypatch.setattr(a, "render_run_report", lambda rid, name: None)
    monkeypatch.setattr(a, "notify_run_complete", lambda *args, **k: None)
    return store


async def _run(monkeypatch, tmp_path, *, domains, outcomes, approval=None, plan_only=False,
               delegate_mock=None):
    delegate_mock = delegate_mock or AsyncMock(return_value=_deleg_result())
    store = _wire(monkeypatch, domains=domains, outcomes=outcomes, delegate_mock=delegate_mock)
    result = await a.identify(
        IdentificationInput(goal="a punchy AMV"),
        approval=approval, plan_only=plan_only, output_path=tmp_path / "report.md",
    )
    return result, store, delegate_mock


@pytest.mark.asyncio
async def test_auto_approve_delegates_every_gap(monkeypatch, tmp_path) -> None:
    domains = [_domain("A"), _domain("B")]
    outcomes = [_outcome("A", "delegate"), _outcome("B", "delegate")]
    result, store, delegate_mock = await _run(
        monkeypatch, tmp_path, domains=domains, outcomes=outcomes, approval=None
    )
    assert delegate_mock.await_count == 2
    # max_items counts DELEGATIONS, not findings.
    assert result.items_processed == 2
    store.upsert_findings.assert_awaited_once()
    assert (tmp_path / "report.md").exists()
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_decline_all_curates_from_local_without_delegating(monkeypatch, tmp_path) -> None:
    domains = [_domain("A"), _domain("B")]
    outcomes = [_outcome("A", "delegate"), _outcome("B", "delegate")]
    result, store, delegate_mock = await _run(
        monkeypatch, tmp_path, domains=domains, outcomes=outcomes,
        approval=lambda d, o: set(),  # decline all
    )
    assert delegate_mock.await_count == 0           # not an abort…
    store.upsert_findings.assert_awaited_once()      # …still curates + writes
    assert result.items_processed == 0
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_partial_prune_delegates_only_approved(monkeypatch, tmp_path) -> None:
    domains = [_domain("A"), _domain("B")]
    outcomes = [_outcome("A", "delegate"), _outcome("B", "delegate")]
    result, _store, delegate_mock = await _run(
        monkeypatch, tmp_path, domains=domains, outcomes=outcomes,
        approval=lambda d, o: {"A"},
    )
    assert delegate_mock.await_count == 1
    assert result.items_processed == 1


@pytest.mark.asyncio
async def test_local_domains_are_never_delegated(monkeypatch, tmp_path) -> None:
    domains = [_domain("A"), _domain("B")]
    outcomes = [_outcome("A", "local"), _outcome("B", "delegate")]
    result, _store, delegate_mock = await _run(
        monkeypatch, tmp_path, domains=domains, outcomes=outcomes, approval=None
    )
    # Only the gap (B) delegates; the known domain (A) is curated locally.
    assert delegate_mock.await_count == 1


@pytest.mark.asyncio
async def test_plan_only_writes_nothing_and_marks_preview(monkeypatch, tmp_path) -> None:
    domains = [_domain("A"), _domain("B")]
    outcomes = [_outcome("A", "delegate"), _outcome("B", "local")]
    result, store, delegate_mock = await _run(
        monkeypatch, tmp_path, domains=domains, outcomes=outcomes, plan_only=True
    )
    assert delegate_mock.await_count == 0
    store.upsert_findings.assert_not_awaited()
    assert result.report.preview is True
    assert result.finding_ids == []
