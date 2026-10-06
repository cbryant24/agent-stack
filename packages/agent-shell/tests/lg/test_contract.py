"""One behavior suite, run against every engine.

Cases: the scripted FakeEngine and the LangGraph engine in both provider shapes
(Anthropic-style blocks, OpenAI-style strings), driven by a scripted chat model. A neutral
"turns" script is translated for each. Real-provider runs are in test_live.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agent_shell.engine.base import (
    Engine,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnd,
)
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.session.api import ConfirmRequested, Session, SessionEvent
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio

# neutral script: a turn is a list of ("say", text, cost_usd) / ("call", tool, args)
Turn = list[tuple[Any, ...]]
Make = Callable[..., Session]

_PRICE_PER_TOKEN = {"claude": 3.0 / 1e6, "openai": 0.25 / 1e6}   # sonnet-4-6 / gpt-5-mini input


@dataclass
class Case:
    name: str
    # build(turns, skip, delay): `skip` = turns already in a resumed transcript that a scripted
    # FakeEngine must step over (real engines have no such concept); `delay` = seconds per chunk
    build: Callable[..., Engine]
    prior_users: Callable[[Engine], list[str]]   # user texts the engine was given as history


def _fake(turns: list[Turn], skip: int = 0, delay: float = 0.0) -> Engine:
    script = [
        [Say(text=s[1], cost_usd=s[2]) if s[0] == "say" else Call(name=s[1], args=s[2]) for s in t]
        for t in turns
    ]
    return FakeEngine([[] for _ in range(skip)] + script, delay=delay)


def _sim_script(turns: list[Turn], provider: str) -> list[dict[str, Any]]:
    """Fold each turn into model calls: a call that asks for tools is followed by another."""
    out: list[dict[str, Any]] = []
    for turn in turns:
        cur: dict[str, Any] = {"text": "", "calls": []}
        for step in turn:
            if step[0] == "say":
                if cur["calls"]:
                    out.append(cur)
                    cur = {"text": "", "calls": []}
                cur["text"] = (cur["text"] + " " + step[1]).strip()
                tokens = int(step[2] / _PRICE_PER_TOKEN[provider])
                if tokens:
                    cur["usage"] = (tokens, 0, 0, 0)
            else:
                cur["calls"].append((step[1], step[2]))
        out.append(cur)
        if cur["calls"]:
            out.append({"text": "ok"})
    return out


@pytest.fixture(params=["fake", "claude-sim", "openai-sim"])
def case(request: pytest.FixtureRequest, sim: Callable[..., Any]) -> Case:
    if request.param == "fake":
        return Case("fake", _fake, lambda e: [m["content"] for m in e.histories[-1] if m["role"] == "user"])  # type: ignore[attr-defined]
    provider = request.param.split("-")[0]
    holders: list[Any] = []

    def build(turns: list[Turn], skip: int = 0, delay: float = 0.0) -> Engine:
        s = sim(_sim_script(turns, provider), provider=provider, delay=delay)
        holders.append(s)
        return s.engine  # type: ignore[no-any-return]

    def prior(_: Engine) -> list[str]:
        humans = [m.content for m in holders[-1].model.seen[-1] if isinstance(m, HumanMessage)]
        return [str(h) for h in humans[:-1]]

    return Case(request.param, build, prior)


def evs(events: list[SessionEvent], kind: type) -> list[Any]:
    return [e for e in events if isinstance(e, kind)]


async def test_streams_text_and_ends_the_turn(case: Case, make_session: Make) -> None:
    s = make_session(engine=case.build([[("say", "hello there", 0.0)]]))
    await s.start()
    events = await drain(s, "hi")
    assert "".join(e.text for e in evs(events, TextDelta)).strip() == "hello there"
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete"
    assert [m["role"] for m in s.transcript()] == ["user", "assistant"]


async def test_tool_call_started_before_finished_with_matching_ids(
    case: Case, make_session: Make, counter: Counter
) -> None:
    s = make_session(engine=case.build([[("say", "look", 0.0), ("call", "read", {"text": "q"}), ("say", "done", 0.0)]]))
    await s.start()
    events = await drain(s, "go")
    started, finished = evs(events, ToolCallStarted)[0], evs(events, ToolCallFinished)[0]
    assert events.index(started) < events.index(finished)
    assert started.call_id == finished.call_id and finished.result.text == "read ran q"
    assert counter.calls == ["q"]
    msgs = s.transcript()
    call_id = next(c["id"] for m in msgs for c in m.get("tool_calls", []))
    assert any(m["role"] == "tool" and m["tool_call_id"] == call_id for m in msgs)


async def test_gate_accept_runs_the_tool_and_charges_the_gpu_budget(
    case: Case, make_session: Make, counter: Counter
) -> None:
    s = make_session(engine=case.build([[("call", "gpu", {"text": "g"})]]), broker=True)
    await s.start()
    events = await drain(s, "go", Decision(kind="accept"))
    assert counter.calls == ["g"] and s.budgets.gpu.spent == pytest.approx(0.25)
    ask = evs(events, ConfirmRequested)[0]
    assert ask.request.tool == "gpu" and ask.request.preview == "preview g"
    # the confirm panel comes after the "tool started" line, never before it
    assert events.index(evs(events, ToolCallStarted)[0]) < events.index(ask)


async def test_gate_reject_runs_nothing_and_says_so(
    case: Case, make_session: Make, counter: Counter
) -> None:
    s = make_session(engine=case.build([[("call", "gpu", {})]]), confirmer=AutoConfirmer("reject"))
    await s.start()
    events = await drain(s, "go")
    assert counter.calls == [] and evs(events, ToolCallFinished)[0].result.data == {"rejected": True}


async def test_dry_run_calls_no_handler(case: Case, make_session: Make, counter: Counter) -> None:
    s = make_session(engine=case.build([[("call", "gpu", {}), ("call", "mem", {})]]))
    s.dry_run = True
    await s.start()
    events = await drain(s, "go")
    assert counter.calls == []
    assert all(f.result.text.startswith("[dry-run]") for f in evs(events, ToolCallFinished))


async def test_budget_stop_ends_the_turn_before_any_tool_runs(
    case: Case, make_session: Make, counter: Counter
) -> None:
    s = make_session(
        engine=case.build([[("say", "pricey", 0.6), ("call", "read", {}), ("say", "after", 0.0)]]),
        budget=0.5,
    )
    await s.start()
    events = await drain(s, "go")
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "budget_exhausted"
    assert counter.calls == []                       # the tool never ran
    again = await drain(s, "again")
    assert isinstance(again[-1], TurnEnd) and again[-1].reason == "budget_exhausted"


async def test_interrupt_stops_a_turn_and_the_session_continues(case: Case, make_session: Make) -> None:
    long_turn: Turn = [("say", " ".join(["w"] * 80), 0.0)]
    s = make_session(engine=case.build([long_turn, [("say", "after", 0.0)]], delay=0.01))
    await s.start()
    events: list[SessionEvent] = []
    async for ev in s.send("go"):
        events.append(ev)
        if len(events) == 3:
            await s.interrupt()
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "interrupted"
    assert len(events) < 40                          # it really stopped early
    nxt = await drain(s, "again")
    assert isinstance(nxt[-1], TurnEnd) and nxt[-1].reason == "complete"
    assert "after" in "".join(e.text for e in evs(nxt, TextDelta))


async def test_resume_gives_the_new_engine_the_earlier_turns(case: Case, make_session: Make) -> None:
    s1 = make_session(engine=case.build([[("say", "first", 0.0)]]))
    await s1.start()
    await drain(s1, "one")
    sid = s1.session_id
    await s1.close()

    eng2 = case.build([[("say", "second", 0.0)]], skip=1)
    s2 = make_session(engine=eng2)
    await s2.start(resume_id=sid)
    events = await drain(s2, "two")
    assert case.prior_users(eng2) == ["one"]
    assert "second" in "".join(e.text for e in evs(events, TextDelta))
    assert [m["content"] for m in s2.transcript() if m["role"] == "user"] == ["one", "two"]
