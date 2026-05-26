from __future__ import annotations

import pytest
from agent_runtime.models import (
    BudgetConsumption,
    BudgetEnvelope,
    BudgetMode,
    DelegationResult,
    TraceEvent,
)


class TestBudgetMode:
    def test_values(self) -> None:
        assert BudgetMode.CONSERVATIVE == "conservative"
        assert BudgetMode.NORMAL == "normal"
        assert BudgetMode.EXPLORATORY == "exploratory"


class TestBudgetEnvelopeDerive:
    def test_inherits_session_id(self) -> None:
        parent = BudgetEnvelope(session_id="parent-session", max_depth=2)
        child = parent.derive_child()
        assert child.session_id == "parent-session"

    def test_sets_parent_run_id(self) -> None:
        parent = BudgetEnvelope(session_id="s1", max_depth=2)
        child = parent.derive_child()
        assert child.parent_run_id == "s1"

    def test_decrements_depth(self) -> None:
        parent = BudgetEnvelope(max_depth=3)
        child = parent.derive_child()
        assert child.max_depth == 2

    def test_caps_max_cost_usd_override_above_parent(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_cost_usd=5.0)
        child = parent.derive_child(max_cost_usd=10.0)
        assert child.max_cost_usd == 5.0  # capped to parent

    def test_caps_max_cost_usd_override_below_parent(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_cost_usd=5.0)
        child = parent.derive_child(max_cost_usd=2.0)
        assert child.max_cost_usd == 2.0  # override honored since < parent

    def test_caps_max_items(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_items=100)
        child = parent.derive_child(max_items=200)
        assert child.max_items == 100

    def test_caps_max_wall_time(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_wall_time_sec=60)
        child = parent.derive_child(max_wall_time_sec=120)
        assert child.max_wall_time_sec == 60

    def test_parent_none_limit_passes_override(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_cost_usd=None)
        child = parent.derive_child(max_cost_usd=3.0)
        assert child.max_cost_usd == 3.0

    def test_both_none_stays_none(self) -> None:
        parent = BudgetEnvelope(max_depth=2, max_cost_usd=None)
        child = parent.derive_child()
        assert child.max_cost_usd is None

    def test_inherits_mode(self) -> None:
        parent = BudgetEnvelope(max_depth=2, mode=BudgetMode.EXPLORATORY)
        child = parent.derive_child()
        assert child.mode == BudgetMode.EXPLORATORY


class TestBudgetConsumptionRemaining:
    def test_remaining_unlimited_when_no_caps(self) -> None:
        envelope = BudgetEnvelope(max_depth=0)
        consumption = BudgetConsumption()
        remaining = consumption.remaining(envelope)
        assert remaining.items is None
        assert remaining.cost_usd is None
        assert remaining.wall_time_sec is None
        assert not remaining.exhausted

    def test_remaining_cost(self) -> None:
        envelope = BudgetEnvelope(max_cost_usd=10.0)
        consumption = BudgetConsumption(cost_usd=3.0)
        remaining = consumption.remaining(envelope)
        assert remaining.cost_usd == pytest.approx(7.0)
        assert not remaining.exhausted

    def test_exhausted_when_cost_exceeded(self) -> None:
        envelope = BudgetEnvelope(max_cost_usd=1.0)
        consumption = BudgetConsumption(cost_usd=1.5)
        remaining = consumption.remaining(envelope)
        assert remaining.exhausted
        assert remaining.reason == "max_cost_usd"

    def test_exhausted_when_items_exceeded(self) -> None:
        envelope = BudgetEnvelope(max_items=10)
        consumption = BudgetConsumption(items_processed=11)
        remaining = consumption.remaining(envelope)
        assert remaining.exhausted
        assert remaining.reason == "max_items"

    def test_exhausted_when_time_exceeded(self) -> None:
        envelope = BudgetEnvelope(max_wall_time_sec=30)
        consumption = BudgetConsumption(wall_time_sec=31.0)
        remaining = consumption.remaining(envelope)
        assert remaining.exhausted
        assert remaining.reason == "max_wall_time_sec"

    def test_first_exhausted_dimension_wins(self) -> None:
        envelope = BudgetEnvelope(max_items=5, max_cost_usd=1.0)
        consumption = BudgetConsumption(items_processed=6, cost_usd=2.0)
        remaining = consumption.remaining(envelope)
        assert remaining.reason == "max_items"


class TestDelegationResultRoundTrip:
    def test_serialization(self) -> None:
        result = DelegationResult(
            run_id="run-123",
            target_agent="tutorial-research",
            status="completed",
            result={"summary": "hello"},
            consumption=BudgetConsumption(cost_usd=0.42, llm_calls=3),
        )
        data = result.model_dump()
        restored = DelegationResult(**data)
        assert restored.run_id == "run-123"
        assert restored.consumption.cost_usd == pytest.approx(0.42)
        assert restored.status == "completed"

    def test_failed_status(self) -> None:
        result = DelegationResult(
            run_id="run-456",
            target_agent="music-curation",
            status="failed",
            consumption=BudgetConsumption(),
            error="timeout",
        )
        assert result.result is None
        assert result.error == "timeout"


class TestTraceEvent:
    def test_default_timestamp(self) -> None:
        event = TraceEvent(event_type="info", metadata={"msg": "hello"})
        assert event.timestamp is not None
        assert event.span_id != ""

    def test_all_event_types(self) -> None:
        for etype in ("llm_call", "tool_call", "delegation", "memory_query",
                      "memory_write", "error", "info"):
            e = TraceEvent(event_type=etype)  # type: ignore[arg-type]
            assert e.event_type == etype
