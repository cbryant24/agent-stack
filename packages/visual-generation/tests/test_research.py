"""research — explicit delegation to tutorial-research (mocked delegate).

Under test: the child budget handed to delegate() is Claude-only and the GPU
tracker is never touched; the result is re-retrieved cheaply from tutorial_research
(the two-step fallback) with NO second delegation; the handler adapter maps the
delegate() contract to tutorial_research.research(); registration is idempotent.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime.config import get_config
from agent_runtime.models import BudgetConsumption, DelegationResult
from agent_runtime.registry import _clear_registry, list_agents
from visual_generation.constants import (
    AGENT_SUBDIR,
    GPU_LEDGER_FILENAME,
    RESEARCH_CHILD_BUDGET,
)
from visual_generation.research import (
    _tutorial_research_handler,
    register_delegate_handlers,
    research,
)


def _gpu_ledger_path() -> Path:
    return get_config().agent_data_dir / AGENT_SUBDIR / GPU_LEDGER_FILENAME


def _delegation_result() -> DelegationResult:
    return DelegationResult(
        run_id="tr-run",
        target_agent="tutorial-research",
        status="completed",
        result={"items_processed": 2, "synthesis": "RunPod pods bill per-second.",
                "status": "completed", "retrieved_count": 3, "request_type": "research"},
        consumption=BudgetConsumption(cost_usd=0.12),
        stop_reason=None,
        error=None,
    )


@pytest.mark.asyncio
async def test_research_delegates_then_cheap_retrieve(monkeypatch) -> None:
    research_mod = importlib.import_module("visual_generation.research")
    delegate_mock = AsyncMock(return_value=_delegation_result())
    fetch_mock = AsyncMock(return_value=[(0.83, "RunPod headless ComfyUI on a pod.")])
    monkeypatch.setattr(research_mod, "delegate", delegate_mock)
    monkeypatch.setattr(research_mod, "_fetch_tutorial", fetch_mock)

    outcome = await research("runpod headless comfyui", memory_store=MagicMock())

    # Exactly one delegation; the re-retrieve is the cheap second step (no re-delegate).
    assert delegate_mock.await_count == 1
    assert fetch_mock.await_count == 1

    target, request, child_budget = delegate_mock.call_args.args[:3]
    assert target == "tutorial-research"
    assert request == {"request": "runpod headless comfyui",
                       "request_type": "research", "synthesize": False, "dry_run": False}
    # The child budget is the Claude-only envelope (no GPU dimension exists on it).
    assert child_budget is RESEARCH_CHILD_BUDGET
    assert child_budget.max_cost_usd is not None

    assert outcome.delegation_status == "completed"
    assert outcome.items_processed == 2
    assert outcome.synthesis == "RunPod pods bill per-second."
    assert outcome.tutorial_hits == [(0.83, "RunPod headless ComfyUI on a pod.")]

    # GPU axis untouched — research never enters the agent-local tracker.
    assert not _gpu_ledger_path().exists()


@pytest.mark.asyncio
async def test_research_no_hits_yet_message(monkeypatch) -> None:
    research_mod = importlib.import_module("visual_generation.research")
    monkeypatch.setattr(research_mod, "delegate", AsyncMock(return_value=_delegation_result()))
    monkeypatch.setattr(research_mod, "_fetch_tutorial", AsyncMock(return_value=[]))

    outcome = await research("a topic", memory_store=MagicMock())
    assert outcome.tutorial_hits == []
    assert outcome.delegation_status == "completed"


@pytest.mark.asyncio
async def test_handler_adapts_delegate_contract_to_research(monkeypatch) -> None:
    fake = SimpleNamespace(
        status="completed", request_type="research", items_processed=2,
        retrieved=[1, 2, 3], synthesis="S", run_id="tr", plan=None,
    )
    research_fn = AsyncMock(return_value=fake)
    monkeypatch.setattr("tutorial_research.research", research_fn)

    out = await _tutorial_research_handler(
        {"request": "q", "request_type": "research", "synthesize": False},
        RESEARCH_CHILD_BUDGET,
    )

    assert out == {"status": "completed", "request_type": "research",
                   "items_processed": 2, "retrieved_count": 3,
                   "synthesis": "S", "run_id": "tr", "plan": None}
    research_fn.assert_awaited_once_with(
        "q", budget=RESEARCH_CHILD_BUDGET, request_type="research",
        synthesize=False, dry_run=False,
    )


@pytest.mark.asyncio
async def test_dry_run_passes_flag_and_skips_re_retrieve(monkeypatch) -> None:
    """Dry-run threads dry_run=True to delegate, surfaces the plan, and does NOT re-query."""
    research_mod = importlib.import_module("visual_generation.research")
    plan = SimpleNamespace(candidates=["c"], selected=["c"])
    result = _delegation_result()
    result.result["plan"] = plan
    delegate_mock = AsyncMock(return_value=result)
    fetch_mock = AsyncMock(return_value=[(0.9, "stale chunk")])
    monkeypatch.setattr(research_mod, "delegate", delegate_mock)
    monkeypatch.setattr(research_mod, "_fetch_tutorial", fetch_mock)

    outcome = await research("a topic", dry_run=True, memory_store=MagicMock())

    request = delegate_mock.call_args.args[1]
    assert request["dry_run"] is True
    # Re-retrieval skipped on dry runs — would surface stale chunks as if ingested.
    assert fetch_mock.await_count == 0
    assert outcome.dry_run is True
    assert outcome.plan is plan
    assert outcome.tutorial_hits == []


def test_render_dry_run_lists_candidates_no_ingest_footer() -> None:
    from visual_generation.research import ResearchOutcome, render_research

    sel = SimpleNamespace(url="https://yt/sel", title="Selected Vid", score=4,
                          rationale="Highly relevant.")
    other = SimpleNamespace(url="https://yt/other", title="Other Vid", score=1,
                            rationale="Marginal.")
    plan = SimpleNamespace(candidates=[sel, other], selected=[sel])
    outcome = ResearchOutcome(
        topic="python asyncio", delegation_status="completed",
        dry_run=True, plan=plan, cost_usd=0.0042,
    )

    out = render_research(outcome)

    assert "dry-run" in out and "NOTHING ingested" in out
    assert "$0.0042" in out  # real, non-zero scoring cost — never $0/free
    assert "would ingest top 1 of 2" in out
    assert "→ [4] Selected Vid" in out
    assert "https://yt/sel" in out and "Highly relevant." in out
    assert "  [1] Other Vid" in out  # scored but not selected → no arrow
    assert "Nothing was ingested" in out
    assert "Now retrievable" not in out  # the ingested-path footer must not appear


def test_register_delegate_handlers_is_idempotent() -> None:
    _clear_registry()
    register_delegate_handlers()
    assert "tutorial-research" in list_agents()
    # Second call does not raise (guarded via list_agents).
    register_delegate_handlers()
    assert list_agents().count("tutorial-research") == 1
