from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_shell.config import ShellSettings
from agent_shell.engine.base import (
    EngineEvent,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnd,
)
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.proposals import Proposal, walk_proposals
from agent_shell.session.api import ConfirmRequested, Session, SessionEvent
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio

Make = Callable[..., Session]


def kinds(events: list[SessionEvent]) -> list[str]:
    return [type(e).__name__ for e in events]


async def test_streams_text_tool_calls_and_cost(make_session: Make, counter: Counter) -> None:
    s = make_session([[Say(text="hello there", cost_usd=0.1), Call(name="read", args={"text": "q"})]])
    await s.start()
    events = await drain(s, "hi")
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["hello ", "there "]
    assert any(isinstance(e, ToolCallStarted) for e in events)
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.text == "read ran q"
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete"
    assert s.budgets.repl.spent == pytest.approx(0.1)
    await s.close()


async def test_session_api_confirm_flow_needs_no_terminal(make_session: Make, counter: Counter) -> None:
    s = make_session(
        [[Call(name="gpu", args={"text": "a"})], [Call(name="gpu", args={"text": "b"})]],
        broker=True,
    )
    await s.start()
    ev1 = await drain(s, "go", Decision(kind="accept"))
    ev2 = await drain(s, "again", Decision(kind="reject"))
    assert sum(isinstance(e, ConfirmRequested) for e in ev1 + ev2) == 2
    assert counter.calls == ["a"]
    assert s.budgets.gpu.spent == 0.25


async def test_injected_confirmer_is_used_instead_of_events(make_session: Make, counter: Counter) -> None:
    c = AutoConfirmer("accept")
    s = make_session([[Call(name="mem", args={"text": "m"})]], confirmer=c)
    await s.start()
    events = await drain(s, "go")
    assert not any(isinstance(e, ConfirmRequested) for e in events) and counter.calls == ["m"]
    with pytest.raises(RuntimeError):
        s.confirm(Decision(kind="accept"))


async def test_dry_run_through_a_session(make_session: Make, counter: Counter) -> None:
    s = make_session([[Call(name="gpu", args={})]], confirmer=AutoConfirmer())
    s.dry_run = True
    await s.start()
    events = await drain(s, "go")
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.text.startswith("[dry-run]") and counter.calls == []


async def test_budget_stop_ends_the_turn_and_blocks_the_next(make_session: Make, counter: Counter) -> None:
    s = make_session(
        [[Say(text="a", cost_usd=0.6), Call(name="read", args={}), Say(text="b")], [Say(text="again")]],
        budget=0.5,
    )
    await s.start()
    e1 = await drain(s, "one")
    assert isinstance(e1[-1], TurnEnd) and e1[-1].reason == "budget_exhausted"
    assert counter.calls == []  # the tool after the overspend never ran
    e2 = await drain(s, "two")
    assert kinds(e2) == ["TurnEnd"] and isinstance(e2[0], TurnEnd) and e2[0].reason == "budget_exhausted"


async def test_interrupt_stops_a_streaming_turn(make_session: Make) -> None:
    s = make_session([[Say(text=" ".join(["w"] * 200))]], delay=0.01)
    await s.start()
    events: list[EngineEvent | ConfirmRequested] = []
    async for ev in s.send("go"):
        events.append(ev)
        if len(events) == 3:
            await s.interrupt()
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "interrupted"
    assert len(events) < 50


async def test_interrupt_during_a_pending_confirm_rejects_it(make_session: Make, counter: Counter) -> None:
    s = make_session([[Call(name="gpu", args={})]], broker=True)
    await s.start()
    events: list[SessionEvent] = []
    async for ev in s.send("go"):
        events.append(ev)
        if isinstance(ev, ConfirmRequested):
            await s.interrupt()
    assert counter.calls == []
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "interrupted"
    assert s.pending_confirmation is None


async def test_engine_failure_is_a_turn_end_not_a_crash(make_session: Make) -> None:
    class Bad(FakeEngine):
        async def send(self, handle: Any, user_text: str, history: Any = None) -> Any:  # type: ignore[override]
            raise ValueError("engine down")
            yield  # pragma: no cover

    s = make_session(engine=Bad())
    await s.start()
    events = await drain(s, "hi")
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "error"
    assert "engine down" in events[-1].detail


async def test_resume_replays_transcript_and_native_handle(
    make_session: Make, settings: ShellSettings
) -> None:
    s1 = make_session([[Say(text="first")], [Say(text="second")]])
    await s1.start()
    await drain(s1, "hello")
    sid = s1.session_id
    await s1.close()

    e2 = FakeEngine([[Say(text="first")], [Say(text="second")]])
    s2 = make_session(engine=e2)
    await s2.start(resume_id=sid)
    assert s2.session_id == sid
    assert e2.started_with is not None
    assert [m["role"] for m in e2.started_with.transcript] == ["user", "assistant"]
    assert e2.started_with.native_handle == "fake-1"
    events = await drain(s2, "more")
    assert "".join(e.text for e in events if isinstance(e, TextDelta)).strip() == "second"
    assert [m["content"] for m in s2.transcript() if m["role"] == "user"] == ["hello", "more"]


async def test_resume_with_a_different_provider_replays_the_neutral_transcript(
    make_session: Make
) -> None:
    s1 = make_session([[Say(text="a")]])
    await s1.start()
    await drain(s1, "hello")
    sid = s1.session_id
    await s1.close()

    other = FakeEngine()
    other.provider = "claude"
    s2 = make_session(engine=other)
    await s2.start(resume_id=sid)
    assert other.started_with is not None
    assert other.started_with.native_handle is None  # claude has no handle for this session
    assert len(other.started_with.transcript) == 2


async def test_resume_unknown_session_raises(make_session: Make) -> None:
    s = make_session()
    with pytest.raises(KeyError):
        await s.start(resume_id="nope")


async def test_audit_log_lives_beside_the_runtime_trace(
    make_session: Make, settings: ShellSettings
) -> None:
    s = make_session([[Call(name="read", args={})]])
    await s.start()
    await drain(s, "go")
    assert s.audit is not None
    p = s.audit.path
    assert p.name == "audit.jsonl" and p.parent.name == s.session_id
    assert p.parent.parent.name == "t" and p.is_relative_to(settings.agent_data_dir / "runs")
    rec = s.audit.read()[0]
    assert rec["tool"] == "read" and rec["provider"] == "fake" and rec["model"] == "fake-1"


async def test_shell_only_creates_its_own_tables(make_session: Make, settings: ShellSettings) -> None:
    s = make_session()
    await s.start()
    con = sqlite3.connect(settings.db_path)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert all(n.startswith("agent_shell_") or n.startswith("sqlite_") for n in names)


async def test_end_of_session_proposals_walk_accept_edit_defer_skip(
    make_session: Make, settings: ShellSettings, tmp_path: Path
) -> None:
    props = [
        Proposal(kind="lesson", summary="one", payload={"statement": "a"}),
        Proposal(kind="lesson", summary="two", payload={"statement": "b"}),
        Proposal(kind="lesson", summary="three", payload={"statement": "c"}),
        Proposal(kind="lesson", summary="four", payload={"statement": "d"}),
    ]
    s = make_session([[Say(text="hi")]], on_end=lambda transcript: props)
    await s.start()
    await drain(s, "hello")
    proposals = await s.close()
    assert [p.summary for p in proposals] == ["one", "two", "three", "four"]

    drafts = tmp_path / "drafts"
    c = AutoConfirmer("accept", Decision(kind="edit", payload={"statement": "B!"}), "defer", "reject")
    report = await walk_proposals(proposals, c, drafts)
    assert [p.payload["statement"] for p in report.accepted] == ["a", "B!"]
    assert [p.summary for p in report.deferred] == ["three"]
    assert [p.summary for p in report.skipped] == ["four"]
    assert len(list(drafts.glob("*.json"))) == 1
    # deferring the same proposal again does not create a second file
    await walk_proposals([proposals[2]], AutoConfirmer("defer"), drafts)
    assert len(list(drafts.glob("*.json"))) == 1


async def test_no_proposals_when_the_agent_supplies_no_hook(make_session: Make) -> None:
    s = make_session([[Say(text="hi")]])
    await s.start()
    await drain(s, "x")
    assert await s.close() == []
