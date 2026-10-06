from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_runtime.budget import estimate_cost
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.proposals import Proposal
from agent_shell.repl.commands import ReplContext, handle_slash
from agent_shell.session.api import Session
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio
Make = Callable[..., Session]
SimMaker = Callable[..., Any]


async def test_switching_provider_reuses_the_same_history_with_the_same_tool_ids(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    claude = sim([{"calls": [("read", {"text": "a"})]}, {"text": "claude says A"}], provider="claude")
    openai = sim([{"text": "openai follows up"}], provider="openai")
    back = sim([{"text": "claude again"}], provider="claude")
    session = make_session(engine=claude.engine)
    await session.start()
    await drain(session, "first question")
    sid = session.session_id

    await session.switch_engine(openai.engine)
    await drain(session, "second question")
    msgs = openai.model.seen[0]
    assert [type(m).__name__ for m in msgs] == [
        "SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage", "HumanMessage",
    ]
    ai = msgs[2]
    assert isinstance(ai, AIMessage) and isinstance(msgs[3], ToolMessage)
    assert msgs[3].tool_call_id == ai.tool_calls[0]["id"] and msgs[3].content == "read ran a"
    assert msgs[4].content == "claude says A"

    await session.switch_engine(back.engine)
    await drain(session, "third question")
    humans = [m.content for m in back.model.seen[0] if isinstance(m, HumanMessage)]
    assert humans == ["first question", "second question", "third question"]
    assert session.session_id == sid  # one session throughout


async def test_switch_is_audited_and_does_not_end_the_session(
    make_session: Make, sim: SimMaker
) -> None:
    fired: list[int] = []

    def on_end(transcript: list[dict[str, Any]]) -> list[Proposal]:
        fired.append(len(transcript))
        return [Proposal(kind="lesson", summary="s", payload={"x": 1})]

    a = sim([{"text": "one"}], provider="claude")
    b = sim([{"text": "two"}], provider="openai", model="gpt-5-nano")
    session = make_session(engine=a.engine, on_end=on_end)
    await session.start()
    await drain(session, "hi")
    await session.switch_engine(b.engine)
    assert fired == []                                   # not an end of session
    await session.switch_engine(a.engine.__class__("claude", "claude-haiku-4-5", "k", model_factory=lambda: a.model))
    assert session.audit is not None
    sw = [r for r in session.audit.read() if r["kind"] == "provider_switch"]
    assert [(r["from_provider"], r["to_provider"], r["to_model"]) for r in sw] == [
        ("claude", "openai", "gpt-5-nano"), ("openai", "claude", "claude-haiku-4-5"),
    ]
    proposals = await session.close()
    assert fired and len(proposals) == 1                 # the real end still produces them


async def test_switch_mid_session_keeps_budgets_and_costs_accumulate(
    make_session: Make, sim: SimMaker
) -> None:
    a = sim([{"text": "x", "usage": (1000, 100, 0, 0)}], provider="claude")
    b = sim([{"text": "y", "usage": (2000, 200, 0, 0)}], provider="openai", model="gpt-5-mini")
    session = make_session(engine=a.engine)
    await session.start()
    await drain(session, "1")
    await session.switch_engine(b.engine)
    await drain(session, "2")
    expect = estimate_cost("claude-sonnet-4-6", 1000, 100) + estimate_cost("gpt-5-mini", 2000, 200)  # type: ignore[operator]
    assert session.budgets.repl.spent == pytest.approx(expect)


async def test_each_model_call_is_a_turn_cost_audit_record_and_a_trace_event(
    make_session: Make, sim: SimMaker, settings: Any
) -> None:
    s = sim([
        {"calls": [("read", {})], "usage": (5000, 50, 4000, 500)},
        {"text": "done", "usage": (5600, 80, 4500, 0)},
    ])
    session = make_session(engine=s.engine)
    await session.start()
    await drain(session, "go")
    assert session.audit is not None and session.trace is not None
    costs = [r for r in session.audit.read() if r["kind"] == "turn_cost"]
    assert len(costs) == 2
    assert costs[0]["provider"] == "claude" and costs[0]["model"] == "claude-sonnet-4-6"
    assert (costs[0]["cache_read_tokens"], costs[0]["cache_write_tokens"]) == (4000, 500)
    total = sum(r["cost_usd"] for r in costs)
    assert total == pytest.approx(session.budgets.repl.spent)

    trace_path = session.trace.path
    await session.close()
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    llm = [e for e in events if e["event_type"] == "llm_call"]
    assert len(llm) == 2 and llm[0]["metadata"]["llm.model"] == "claude-sonnet-4-6"
    assert llm[0]["metadata"]["llm.cost_usd"] == pytest.approx(costs[0]["cost_usd"])
    end = next(e for e in events if e["metadata"].get("event") == "run_end")["metadata"]
    assert end["envelope"]["session_id"] == session.session_id
    assert end["summary"]["cost_usd"] == pytest.approx(total)
    assert end["summary"]["llm_calls"] == 2 and end["summary"]["tool_calls"] == 1
    assert end["providers"] == ["claude"]
    assert trace_path.is_relative_to(settings.agent_data_dir / "runs")
    assert trace_path.parent.parent.name == "t"          # runs/<date>/<app>/<run_id>/trace.jsonl


async def test_a_resumed_session_writes_a_second_segment_with_the_same_session_id(
    make_session: Make
) -> None:
    s1 = make_session([[Say(text="one", cost_usd=0.01)]])
    await s1.start()
    await drain(s1, "a")
    first = s1.trace.path if s1.trace else None
    sid = s1.session_id
    await s1.close()
    # a resumed FakeEngine skips the turns already in the transcript
    s2 = make_session([[Say(text="skipped")], [Say(text="two", cost_usd=0.02)]])
    await s2.start(resume_id=sid)
    await drain(s2, "b")
    second = s2.trace.path if s2.trace else None
    await s2.close()
    assert first and second and first != second
    for p, cost in ((first, 0.01), (second, 0.02)):
        end = next(
            json.loads(line)["metadata"] for line in p.read_text().splitlines()
            if json.loads(line)["metadata"].get("event") == "run_end"
        )
        assert end["envelope"]["session_id"] == sid and end["summary"]["cost_usd"] == pytest.approx(cost)


async def test_provider_and_model_slash_commands_switch_through_the_factory(
    make_session: Make, sim: SimMaker
) -> None:
    a = sim([{"text": "one"}], provider="claude")
    session = make_session(engine=a.engine)
    await session.start()
    built: list[tuple[str, str | None]] = []

    def factory(provider: str, model: str | None) -> Any:
        built.append((provider, model))
        if provider == "bad":
            raise RuntimeError("no key")
        return sim([{"text": "x"}], provider=provider, model=model).engine

    ctx = ReplContext(session, engine_factory=factory)
    out = (await handle_slash("/provider openai gpt-5-nano", ctx)).output
    assert "openai" in out and "history carried over" in out and session.engine.provider == "openai"
    out = (await handle_slash("/model gpt-5-mini", ctx)).output
    assert "gpt-5-mini" in out and session.engine.model == "gpt-5-mini"
    assert built == [("openai", "gpt-5-nano"), ("openai", "gpt-5-mini")]
    before = session.engine
    assert "no key" in (await handle_slash("/provider bad", ctx)).output
    assert session.engine is before                      # a failed switch changes nothing
    assert "available:" in (await handle_slash("/provider", ctx)).output


async def test_audit_command_lists_only_tool_calls(make_session: Make, counter: Counter) -> None:
    s = make_session([[Say(text="x", cost_usd=0.01), Call(name="read", args={})]])
    await s.start()
    await drain(s, "go")
    out = (await handle_slash("/audit", ReplContext(s))).output
    assert "read" in out and "turn_cost" not in out and len(out.splitlines()) == 1
    assert isinstance(s.engine, FakeEngine)
