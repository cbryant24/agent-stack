from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent_runtime import BudgetEnvelope

from orchestrator.agent import run_turn
from orchestrator.graph import build_graph

from ._stubs import StubModel, make_echo_tool, make_tool_call_message


@pytest.mark.asyncio
async def test_exhausted_envelope_short_circuits_before_next_tool_runs() -> None:
    """Once the per-turn envelope is exhausted, the guard must short-circuit to a
    partial answer BEFORE the next tool executes (mirrors tutorial-research's
    budget-exhaustion test). max_items=1: the first tool consumes the budget, the
    second tool call is skipped by the guard."""
    one_shot = BudgetEnvelope(max_items=1, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300)

    echo, ran = make_echo_tool()
    model = StubModel([
        make_tool_call_message("echo", {"x": "first"}, call_id="c1"),   # runs, consumes the item
        make_tool_call_message("echo", {"x": "second"}, call_id="c2"),  # guard trips, skipped
        AIMessage(content="here is what I have so far"),                 # partial answer
    ])
    graph = build_graph(model, [echo], InMemorySaver())

    result = await run_turn(graph, "do work", thread_id="t-budget", budget=one_shot)

    assert ran["count"] == 1                        # only the first tool executed
    assert ran["args"] == "first"                   # the second was short-circuited
    assert result.status == "partial"               # degraded to a partial answer
    assert result.response == "here is what I have so far"
    assert result.consumption.tool_calls == 1       # exactly one tool recorded as run


@pytest.mark.asyncio
async def test_budget_allows_tool_when_not_exhausted() -> None:
    echo, ran = make_echo_tool()
    model = StubModel([
        make_tool_call_message("echo", {"x": "go"}),
        AIMessage(content="finished"),
    ])
    graph = build_graph(model, [echo], InMemorySaver())

    result = await run_turn(graph, "do work", thread_id="t-budget-ok")

    assert ran["called"] is True
    assert result.status == "completed"
