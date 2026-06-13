from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent_runtime import BudgetEnvelope

from orchestrator.agent import run_turn
from orchestrator.graph import build_graph

from ._stubs import StubModel, make_echo_tool, make_tool_call_message


def assert_balanced(messages: list) -> None:
    """Every AI tool_use id must be answered by a tool_result later in the sequence."""
    answered = {
        getattr(m, "tool_call_id", None)
        for m in messages
        if getattr(m, "tool_call_id", None) is not None
    }
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            assert tc["id"] in answered, f"tool_use {tc['id']} has no tool_result"


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


@pytest.mark.asyncio
async def test_budget_exhaustion_leaves_thread_valid_for_next_turn() -> None:
    """Budget exhaustion must not strand a tool_use on the checkpointed thread. The
    post-exhaustion model response is ALSO a tool call (what a real model does — it
    doesn't know the budget is gone); the final agent step runs with no tools bound so
    it can't emit one. A SECOND turn on the same thread must load cleanly."""
    one_shot = BudgetEnvelope(max_items=1, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300)

    echo, _ = make_echo_tool()
    model = StubModel([
        make_tool_call_message("echo", {"x": "first"}, call_id="c1"),    # runs, consumes the item
        make_tool_call_message("echo", {"x": "second"}, call_id="c2"),   # guard trips, skipped
        make_tool_call_message("echo", {"x": "third"}, call_id="c3"),    # post-exhaustion: must NOT strand
        AIMessage(content="second turn done"),
    ])
    saver = InMemorySaver()
    graph = build_graph(model, [echo], saver)
    config = {"configurable": {"thread_id": "t-poison"}}

    r1 = await run_turn(graph, "do work", thread_id="t-poison", budget=one_shot)
    assert r1.status == "partial"

    # Fix 1: the c3 tool call was stripped (no tools bound on the summary step), so the
    # persisted history has no dangling tool_use.
    state1 = await graph.aget_state(config)
    assert_balanced(state1.values["messages"])

    # Fix: a second turn on the same thread loads the prior history without raising.
    r2 = await run_turn(graph, "anything else?", thread_id="t-poison", budget=one_shot)
    assert r2.response == "second turn done"

    state2 = await graph.aget_state(config)
    assert_balanced(state2.values["messages"])


@pytest.mark.asyncio
async def test_agent_node_sanitizes_stranded_tool_use_on_load() -> None:
    """A thread whose last AI message has an unanswered tool_use (e.g. left by a crash)
    is repaired at the top of agent_node: the model is invoked with a balanced sequence."""
    echo, _ = make_echo_tool()
    model = StubModel([AIMessage(content="ok")])
    saver = InMemorySaver()
    graph = build_graph(model, [echo], saver)
    config = {"configurable": {"thread_id": "t-stranded"}}

    # Seed a poisoned thread: an AI message with a tool_use and no following tool_result.
    # as_node="tools" sets the saved next node to "agent" (the tools -> agent edge), so
    # the next run resumes into agent_node where the sanitizer runs.
    dangling = make_tool_call_message("echo", {"x": "orphan"}, call_id="c9")
    await graph.aupdate_state(config, {"messages": [dangling]}, as_node="tools")

    result = await run_turn(graph, "continue", thread_id="t-stranded")

    assert result.response == "ok"
    # The model must have been handed a balanced sequence: the synthetic skip tool_result
    # was spliced in immediately after the dangling tool_use.
    assert_balanced(model.last_invocation)
