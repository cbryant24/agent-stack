from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from agent_runtime.budget import BudgetTracker, _PRICING
from agent_runtime.exceptions import BudgetExhaustedError
from agent_runtime.models import BudgetEnvelope


@pytest.fixture(autouse=True)
def _env(fake_env: None) -> None:
    pass


class TestBudgetTrackerBasic:
    def test_consumption_starts_zero(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                c = t.consumption
                assert c.llm_calls == 0
                assert c.cost_usd == 0.0
                assert c.tool_calls == 0

        asyncio.run(run())

    def test_add_tool_call_increments(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_tool_call()
                t.add_tool_call()
                assert t.consumption.tool_calls == 2

        asyncio.run(run())

    def test_add_item_increments(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_item_processed()
                assert t.consumption.items_processed == 1

        asyncio.run(run())


class TestBudgetTrackerCostTracking:
    def test_llm_cost_math_sonnet(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                # 1000 input + 500 output @ sonnet pricing
                # input: 1000/1M * 3.00 = 0.003
                # output: 500/1M * 15.00 = 0.0075
                # total: 0.0105
                t.add_llm_cost("claude-sonnet-4-6", 1000, 500)
                assert t.consumption.cost_usd == pytest.approx(0.0105, rel=1e-6)
                assert t.consumption.llm_calls == 1

        asyncio.run(run())

    def test_llm_cost_math_haiku(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                # 2000 input + 1000 output @ haiku pricing
                # input: 2000/1M * 0.80 = 0.0016
                # output: 1000/1M * 4.00 = 0.004
                # total: 0.0056
                t.add_llm_cost("claude-haiku-4-5", 2000, 1000)
                assert t.consumption.cost_usd == pytest.approx(0.0056, rel=1e-6)

        asyncio.run(run())

    def test_cumulative_cost_across_calls(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_llm_cost("claude-haiku-4-5", 1000, 1000)
                t.add_llm_cost("claude-haiku-4-5", 1000, 1000)
                assert t.consumption.llm_calls == 2

        asyncio.run(run())

    def test_pricing_table_has_all_models(self) -> None:
        assert "claude-opus-4-7" in _PRICING
        assert "claude-opus-4-6" in _PRICING
        assert "claude-sonnet-4-6" in _PRICING
        assert "claude-haiku-4-5" in _PRICING


class TestBudgetTrackerEnforcement:
    def test_check_budget_raises_on_cost_exceeded(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=0.001)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_llm_cost("claude-sonnet-4-6", 10000, 10000)
                with pytest.raises(BudgetExhaustedError) as exc_info:
                    t.check_budget()
                assert exc_info.value.dimension == "max_cost_usd"

        asyncio.run(run())

    def test_check_budget_raises_on_items_exceeded(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_items=3)
            async with BudgetTracker(envelope, "test-agent") as t:
                for _ in range(4):
                    t.add_item_processed()
                with pytest.raises(BudgetExhaustedError) as exc_info:
                    t.check_budget()
                assert exc_info.value.dimension == "max_items"

        asyncio.run(run())

    def test_wall_time_enforcement(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_wall_time_sec=1)
            async with BudgetTracker(envelope, "test-agent") as t:
                await asyncio.sleep(1.1)
                with pytest.raises(BudgetExhaustedError) as exc_info:
                    t.check_budget()
                assert exc_info.value.dimension == "max_wall_time_sec"

        asyncio.run(run())

    def test_zero_max_items_raises_not_zerodivision(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_items=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                with pytest.raises(BudgetExhaustedError) as exc_info:
                    t.check_budget()
                assert exc_info.value.dimension == "max_items"

        asyncio.run(run())

    def test_zero_max_cost_raises_not_zerodivision(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                with pytest.raises(BudgetExhaustedError) as exc_info:
                    t.check_budget()
                assert exc_info.value.dimension == "max_cost_usd"

        asyncio.run(run())

    def test_check_can_afford_unlimited(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)
            async with BudgetTracker(envelope, "test-agent") as t:
                assert t.check_can_afford(999.0)

        asyncio.run(run())

    def test_check_can_afford_within_limit(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=1.0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_llm_cost("claude-haiku-4-5", 100, 100)
                assert t.check_can_afford(0.50)

        asyncio.run(run())

    def test_check_can_afford_over_limit(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=0.01)
            async with BudgetTracker(envelope, "test-agent") as t:
                t.add_llm_cost("claude-sonnet-4-6", 1000, 1000)
                assert not t.check_can_afford(1.0)

        asyncio.run(run())


class TestBudgetThreshold:
    """notify_budget_threshold fires from check_budget() at 75% — once per dimension."""

    def test_fires_on_cost_cross(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=1.0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t._consumption.cost_usd = 0.76
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    mock_notify.assert_called_once()

        asyncio.run(run())

    def test_fires_on_items_cross(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_items=10)
            async with BudgetTracker(envelope, "test-agent") as t:
                for _ in range(8):  # 80 % of 10
                    t.add_item_processed()
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    mock_notify.assert_called_once()

        asyncio.run(run())

    def test_fires_on_wall_time_cross(self) -> None:
        async def run() -> None:
            fake_time = [0.0]

            def time_source() -> float:
                return fake_time[0]

            envelope = BudgetEnvelope(max_depth=0, max_wall_time_sec=100)
            async with BudgetTracker(envelope, "test-agent", time_source=time_source) as t:
                fake_time[0] = 80.0  # 80 % of 100 s
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    mock_notify.assert_called_once()

        asyncio.run(run())

    def test_does_not_fire_below_75(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=1.0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t._consumption.cost_usd = 0.74  # below threshold
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    mock_notify.assert_not_called()

        asyncio.run(run())

    def test_fires_only_once_per_dimension(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0, max_cost_usd=1.0)
            async with BudgetTracker(envelope, "test-agent") as t:
                t._consumption.cost_usd = 0.80
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    t.check_budget()
                    t.check_budget()
                    assert mock_notify.call_count == 1

        asyncio.run(run())

    def test_no_fire_when_no_max_set(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=0)  # no limits
            async with BudgetTracker(envelope, "test-agent") as t:
                t._consumption.cost_usd = 999.0
                with patch("agent_runtime.budget.notify_budget_threshold") as mock_notify:
                    t.check_budget()
                    mock_notify.assert_not_called()

        asyncio.run(run())


class TestBudgetTrackerJSONLEmission:
    def test_llm_call_written_to_jsonl(self, tmp_path: pytest.TempPathFactory) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import load_trace
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            async def run() -> str:
                envelope = BudgetEnvelope(max_depth=0)
                async with BudgetTracker(envelope, "test-agent") as t:
                    t.add_llm_cost("claude-haiku-4-5", 200, 100)
                    t.add_llm_cost("claude-sonnet-4-6", 500, 300)
                    return t.run_id

            run_id = asyncio.run(run())
            events = load_trace(run_id, "test-agent")
            llm_events = [e for e in events if e.event_type == "llm_call"]
            assert len(llm_events) == 2
            models = {e.metadata["llm.model"] for e in llm_events}
            assert models == {"claude-haiku-4-5", "claude-sonnet-4-6"}
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_tool_call_written_to_jsonl(self, tmp_path: pytest.TempPathFactory) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import load_trace
        from agent_runtime.tracing.decorators import record_tool_call
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            async def run() -> str:
                envelope = BudgetEnvelope(max_depth=0)
                async with BudgetTracker(envelope, "test-agent") as t:
                    record_tool_call("tavily.search", "query", "results")
                    record_tool_call("tavily.search", "query2", "results2")
                    t.add_tool_call()
                    t.add_tool_call()
                    return t.run_id

            run_id = asyncio.run(run())
            events = load_trace(run_id, "test-agent")
            tool_events = [e for e in events if e.event_type == "tool_call"]
            assert len(tool_events) == 2
            assert all(e.metadata["tool.name"] == "tavily.search" for e in tool_events)
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_memory_query_written_to_jsonl(self, tmp_path: pytest.TempPathFactory) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import load_trace
        from agent_runtime.tracing.decorators import record_memory_query
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            async def run() -> str:
                envelope = BudgetEnvelope(max_depth=0)
                async with BudgetTracker(envelope, "test-agent") as t:
                    record_memory_query("tutorials", "async python", 5)
                    return t.run_id

            run_id = asyncio.run(run())
            events = load_trace(run_id, "test-agent")
            mq_events = [e for e in events if e.event_type == "memory_query"]
            assert len(mq_events) == 1
            assert mq_events[0].metadata["memory.collection"] == "tutorials"
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()
