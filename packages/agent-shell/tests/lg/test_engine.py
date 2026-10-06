from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_runtime.budget import estimate_cost
from agent_shell.engine.base import (
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCost,
    TurnEnd,
)
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.session.api import ConfirmRequested, Session
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio
Make = Callable[..., Session]
SimMaker = Callable[..., Any]  # lg/conftest.py::sim -> Sim(engine, .model)
CLAUDE_MODEL = "claude-sonnet-4-6"


def text(events: list[Any]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta)).strip()


@pytest.mark.parametrize("provider", ["claude", "openai"])
async def test_streams_text_in_both_content_shapes(
    make_session: Make, sim: SimMaker, provider: str
) -> None:
    s = sim([{"text": "hello there friend"}], provider=provider)
    session = make_session(engine=s.engine)
    await session.start()
    events = await drain(session, "hi")
    assert text(events) == "hello there friend"
    assert [e.text for e in events if isinstance(e, TextDelta)][0] == "hello "
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete"
    assert [m["role"] for m in session.transcript()] == ["user", "assistant"]


@pytest.mark.parametrize("provider", ["claude", "openai"])
async def test_tool_call_runs_through_the_executor_and_the_model_sees_the_result(
    make_session: Make, sim: SimMaker, counter: Counter, provider: str
) -> None:
    s = sim([
        {"text": "checking", "calls": [("read", {"text": "q"})]},
        {"text": "all done"},
    ], provider=provider)
    session = make_session(engine=s.engine)
    await session.start()
    events = await drain(session, "go")

    started = next(e for e in events if isinstance(e, ToolCallStarted))
    finished = next(e for e in events if isinstance(e, ToolCallFinished))
    assert started.name == "read" and started.args == {"text": "q"}
    assert finished.call_id == started.call_id and finished.result.text == "read ran q"
    assert counter.calls == ["q"] and text(events) == "checking all done"
    # second model call received [system, human, ai(tool_call), tool_result]
    second = s.model.seen[1]
    assert isinstance(second[0], SystemMessage) and isinstance(second[1], HumanMessage)
    assert isinstance(second[2], AIMessage) and second[2].tool_calls[0]["id"] == started.call_id
    assert isinstance(second[3], ToolMessage) and second[3].content == "read ran q"
    # and the audit log has it, like any other front end
    assert session.audit is not None
    calls = [r for r in session.audit.read() if r["kind"] == "tool_call"]
    assert [r["tool"] for r in calls] == ["read"]


async def test_gate_reject_and_dry_run_apply_to_langgraph_tool_calls(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    s = sim([
        {"calls": [("gpu", {"text": "x"})]}, {"text": "ok"},
        {"calls": [("gpu", {"text": "y"})]}, {"text": "ok"},
    ])
    session = make_session(engine=s.engine, confirmer=AutoConfirmer("reject"))
    await session.start()
    ev1 = await drain(session, "one")
    assert next(e for e in ev1 if isinstance(e, ToolCallFinished)).result.data == {"rejected": True}
    session.dry_run = True
    ev2 = await drain(session, "two")
    assert next(e for e in ev2 if isinstance(e, ToolCallFinished)).result.text.startswith("[dry-run]")
    assert counter.calls == []


async def test_tool_errors_and_unknown_tools_are_results_not_crashes(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    from agent_shell.testing import make_tool
    from agent_shell.tools.registry import EffectClass

    s = sim([
        {"calls": [("boom", {}), ("nope", {})]}, {"text": "recovered"},
    ])
    session = make_session(
        engine=s.engine, tools=[make_tool("boom", EffectClass.READ, counter, boom=True)]
    )
    await session.start()
    events = await drain(session, "go")
    done = [e for e in events if isinstance(e, ToolCallFinished)]
    assert [(d.name, d.result.is_error) for d in done] == [("boom", True), ("nope", True)]
    assert done[0].result.text == "RuntimeError: kaput" and "unknown tool" in done[1].result.text
    tool_msgs = [m for m in s.model.seen[1] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_msgs] == ["error", "error"]
    assert text(events) == "recovered"


async def test_tool_calls_in_one_message_run_one_at_a_time(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    s = sim([{"calls": [("mem", {"text": "a"}), ("mem", {"text": "b"})]}, {"text": "done"}])
    session = make_session(engine=s.engine, broker=True)
    await session.start()
    order: list[str] = []
    async for ev in session.send("go"):
        if isinstance(ev, ConfirmRequested):
            order.append("ask:" + ev.request.args["text"])
            session.confirm(Decision(kind="accept"))
        elif isinstance(ev, ToolCallFinished):
            order.append("done:" + ev.result.text.split()[-1])
    assert order == ["ask:a", "done:a", "ask:b", "done:b"]
    assert counter.calls == ["a", "b"]


async def test_turn_cost_is_priced_strictly_with_cache_tokens(
    make_session: Make, sim: SimMaker
) -> None:
    s = sim([{"text": "hi", "usage": (10_000, 500, 6_000, 2_000)}])
    session = make_session(engine=s.engine)
    await session.start()
    events = await drain(session, "x")
    cost = next(e for e in events if isinstance(e, TurnCost))
    assert (cost.input_tokens, cost.output_tokens) == (10_000, 500)
    assert (cost.cache_read_tokens, cost.cache_write_tokens) == (6_000, 2_000)
    assert cost.model == CLAUDE_MODEL
    assert cost.cost_usd == pytest.approx(estimate_cost(CLAUDE_MODEL, 10_000, 500, 6_000, 2_000))
    assert session.budgets.repl.spent == pytest.approx(cost.cost_usd)


async def test_budget_stop_with_a_real_engine(make_session: Make, sim: SimMaker, counter: Counter) -> None:
    s = sim([
        {"calls": [("read", {})], "usage": (900_000, 100_000, 0, 0)},  # ~ $4.2 on sonnet
        {"text": "never"},
    ])
    session = make_session(engine=s.engine, budget=0.5)
    await session.start()
    events = await drain(session, "go")
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "budget_exhausted"
    assert len(s.model.seen) == 1


async def test_next_turn_rebuilds_history_from_the_neutral_transcript(
    make_session: Make, sim: SimMaker
) -> None:
    s = sim([
        {"calls": [("read", {"text": "a"})]}, {"text": "first answer"},
        {"text": "second answer"},
    ])
    session = make_session(engine=s.engine)
    await session.start()
    await drain(session, "one")
    await drain(session, "two")
    third_call = s.model.seen[2]
    kinds = [type(m).__name__ for m in third_call]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage", "HumanMessage"]
    ai = third_call[2]
    assert isinstance(ai, AIMessage) and ai.tool_calls[0]["name"] == "read"
    assert isinstance(third_call[3], ToolMessage) and third_call[3].tool_call_id == ai.tool_calls[0]["id"]
    assert third_call[-1].content == "two"


async def test_old_turns_are_trimmed_from_what_the_model_sees(make_session: Make, sim: SimMaker) -> None:
    s = sim([{"text": f"r{i}"} for i in range(4)], history_turns=2)
    session = make_session(engine=s.engine)
    await session.start()
    for i in range(4):
        await drain(session, f"u{i}")
    last = [m.content for m in s.model.seen[3] if isinstance(m, HumanMessage)]
    # history window = the last 2 completed turns (u1, u2); u0 is dropped; u3 is the new message
    assert last == ["u1", "u2", "u3"]
