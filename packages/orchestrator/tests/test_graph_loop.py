from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from orchestrator.agent import run_turn
from orchestrator.graph import build_graph

from ._stubs import StubModel, make_echo_tool, make_tool_call_message


@pytest.mark.asyncio
async def test_tool_call_routes_to_tools_then_loops_back() -> None:
    # First model response asks for a tool; second ends the turn.
    echo, ran = make_echo_tool()
    model = StubModel([
        make_tool_call_message("echo", {"x": "hi"}),
        AIMessage(content="done"),
    ])
    graph = build_graph(model, [echo], InMemorySaver())

    result = await run_turn(graph, "use the tool", thread_id="t-loop")

    assert ran["called"] is True          # tools node executed the tool
    assert ran["args"] == "hi"
    assert result.status == "completed"
    assert result.response == "done"       # looped back to agent for the final answer
    assert model.calls == 2                # agent ran twice (before + after tools)
    assert result.consumption.tool_calls == 1


@pytest.mark.asyncio
async def test_no_tool_call_ends_turn_immediately() -> None:
    echo, ran = make_echo_tool()
    model = StubModel([AIMessage(content="just an answer")])
    graph = build_graph(model, [echo], InMemorySaver())

    result = await run_turn(graph, "no tools needed", thread_id="t-direct")

    assert ran["called"] is False
    assert result.status == "completed"
    assert result.response == "just an answer"
    assert model.calls == 1
    assert result.consumption.tool_calls == 0
