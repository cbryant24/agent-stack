from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agent_runtime.budget import BudgetTracker, get_current_tracker
from agent_runtime.delegation import delegate
from agent_runtime.exceptions import BudgetExhaustedError, DelegationError
from agent_runtime.models import BudgetEnvelope
from agent_runtime.registry import _clear_registry, register_agent


@pytest.fixture(autouse=True)
def _env(fake_env: None) -> None:
    pass


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    _clear_registry()
    yield
    _clear_registry()


class TestAgentRegistry:
    def test_register_and_lookup(self) -> None:
        async def handler(req: dict, budget: BudgetEnvelope) -> dict:
            return {}

        register_agent("my-agent", handler)
        from agent_runtime.registry import get_agent
        assert get_agent("my-agent") is handler

    def test_decorator_form(self) -> None:
        @register_agent("decorated-agent")
        async def handler(req: dict, budget: BudgetEnvelope) -> dict:
            return {}

        from agent_runtime.registry import get_agent
        assert get_agent("decorated-agent") is handler

    def test_duplicate_name_raises(self) -> None:
        async def h(req: dict, budget: BudgetEnvelope) -> dict:
            return {}

        register_agent("dup", h)
        with pytest.raises(ValueError, match="already registered"):
            register_agent("dup", h)

    def test_missing_agent_raises_delegation_error(self) -> None:
        from agent_runtime.registry import get_agent
        with pytest.raises(DelegationError):
            get_agent("nonexistent")

    def test_list_agents(self) -> None:
        from agent_runtime.registry import list_agents
        async def h(req: dict, budget: BudgetEnvelope) -> dict:
            return {}
        register_agent("a1", h)
        register_agent("a2", h)
        assert set(list_agents()) == {"a1", "a2"}


class TestDelegation:
    def test_successful_delegation(self) -> None:
        async def run() -> None:
            async def handler(req: dict, budget: BudgetEnvelope) -> dict:
                return {"answer": 42}

            register_agent("stub", handler)
            envelope = BudgetEnvelope(max_depth=1)
            result = await delegate("stub", {"query": "hello"}, envelope)
            assert result.status == "completed"
            assert result.result == {"answer": 42}
            assert result.target_agent == "stub"

        asyncio.run(run())

    def test_budget_exhausted_returns_partial(self) -> None:
        async def run() -> None:
            async def handler(req: dict, budget: BudgetEnvelope) -> dict:
                tracker = get_current_tracker()
                if tracker:
                    tracker.add_item_processed()
                    tracker.add_item_processed()
                raise BudgetExhaustedError(
                    "max_items",
                    BudgetEnvelope(max_depth=0, max_items=1),
                    tracker.consumption if tracker else __import__("agent_runtime.models", fromlist=["BudgetConsumption"]).BudgetConsumption(),
                )

            register_agent("exhausted-agent", handler)
            envelope = BudgetEnvelope(max_depth=1, max_items=5)
            result = await delegate("exhausted-agent", {}, envelope)
            assert result.status == "partial"
            assert result.stop_reason is not None
            assert "budget_exhausted" in result.stop_reason

        asyncio.run(run())

    def test_exception_returns_failed(self) -> None:
        async def run() -> None:
            async def handler(req: dict, budget: BudgetEnvelope) -> dict:
                raise RuntimeError("something went wrong")

            register_agent("failing-agent", handler)
            envelope = BudgetEnvelope(max_depth=1)
            result = await delegate("failing-agent", {}, envelope)
            assert result.status == "failed"
            assert "something went wrong" in result.error

        asyncio.run(run())

    def test_unknown_agent_raises(self) -> None:
        async def run() -> None:
            envelope = BudgetEnvelope(max_depth=1)
            with pytest.raises(DelegationError):
                await delegate("unknown-agent", {}, envelope)

        asyncio.run(run())

    def test_depth_zero_raises(self) -> None:
        async def run() -> None:
            async def handler(req: dict, budget: BudgetEnvelope) -> dict:
                return {}

            register_agent("blocked", handler)
            envelope = BudgetEnvelope(max_depth=0)
            with pytest.raises(DelegationError, match="max delegation depth"):
                await delegate("blocked", {}, envelope)

        asyncio.run(run())

    def test_parent_debited_on_delegation(self) -> None:
        async def run() -> None:
            async def child(req: dict, budget: BudgetEnvelope) -> dict:
                tracker = get_current_tracker()
                if tracker:
                    tracker.add_llm_cost("claude-haiku-4-5", 10000, 10000)
                return {}

            register_agent("child-agent", child)
            parent_envelope = BudgetEnvelope(max_depth=2)

            async with BudgetTracker(parent_envelope, "parent-agent") as parent_tracker:
                before = parent_tracker.consumption.delegations
                await delegate("child-agent", {}, parent_envelope, parent_tracker=parent_tracker)
                after = parent_tracker.consumption.delegations
                assert after == before + 1
                assert parent_tracker.consumption.cost_usd > 0

        asyncio.run(run())

    def test_nested_delegation_depth_guard(self) -> None:
        async def run() -> None:
            async def depth_1(req: dict, budget: BudgetEnvelope) -> dict:
                # depth becomes 0 here — another delegation should fail
                with pytest.raises(DelegationError, match="max delegation depth"):
                    await delegate("depth-2", {}, budget)
                return {}

            async def depth_2(req: dict, budget: BudgetEnvelope) -> dict:
                return {}

            register_agent("depth-1", depth_1)
            register_agent("depth-2", depth_2)

            envelope = BudgetEnvelope(max_depth=1)
            result = await delegate("depth-1", {}, envelope)
            # depth-1 completes because it caught the error
            assert result.status == "completed"

        asyncio.run(run())
