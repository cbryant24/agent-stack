from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_shell.engine.base import ToolCallFinished, ToolCallStarted
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer
from agent_shell.session.api import Session
from agent_shell.session.recorder import INTERRUPTED, TurnRecorder
from agent_shell.session.store import SessionStore
from agent_shell.testing import Counter, drain
from agent_shell.tools.registry import ToolResult

pytestmark = pytest.mark.asyncio
Make = Callable[..., Session]


async def test_turn_is_stored_as_ordered_assistant_and_tool_messages(
    make_session: Make, counter: Counter
) -> None:
    s = make_session([[
        Say(text="Looking."), Call(name="read", args={"text": "a"}),
        Say(text="Now another."), Call(name="read", args={"text": "b"}),
        Say(text="Done."),
    ]])
    await s.start()
    await drain(s, "go")
    msgs = s.transcript()
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    first, tool1 = msgs[1], msgs[2]
    assert first["content"] == "Looking." and first["tool_calls"][0]["name"] == "read"
    assert first["tool_calls"][0]["args"] == {"text": "a"}
    assert tool1["tool_call_id"] == first["tool_calls"][0]["id"]
    assert tool1["content"] == "read ran a" and tool1["is_error"] is False
    assert msgs[-1]["content"] == "Done." and "tool_calls" not in msgs[-1]


async def test_parallel_calls_share_one_assistant_message(make_session: Make) -> None:
    s = make_session([[Call(name="read", args={"text": "1"}), Call(name="read", args={"text": "2"})]])
    await s.start()
    await drain(s, "go")
    msgs = s.transcript()
    # the fake engine runs calls one after another (Started, Finished, Started, ...),
    # so each lands in its own assistant message with a matching result
    ids = [c["id"] for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls", [])]
    answered = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert ids == answered and len(ids) == 2


async def test_started_calls_before_any_result_join_one_message(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "db.sqlite")
    store.create("s", "t", "fake", "m")
    rec = TurnRecorder(store, "s")
    rec.on_event(ToolCallStarted(call_id="c1", name="a", args={}))
    rec.on_event(ToolCallStarted(call_id="c2", name="b", args={}))
    rec.on_event(ToolCallFinished(call_id="c1", name="a", result=ToolResult(text="ra")))
    rec.on_event(ToolCallFinished(call_id="c2", name="b", result=ToolResult(text="rb", is_error=True)))
    rec.finish()
    msgs = store.messages("s")
    assert [m["role"] for m in msgs] == ["assistant", "tool", "tool"]
    assert [c["id"] for c in msgs[0]["tool_calls"]] == ["c1", "c2"]
    assert msgs[2]["is_error"] is True


async def test_unanswered_call_gets_a_synthetic_result(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "db.sqlite")
    store.create("s", "t", "fake", "m")
    rec = TurnRecorder(store, "s")
    rec.on_event(ToolCallStarted(call_id="c1", name="a", args={}))
    rec.finish()
    msgs = store.messages("s")
    assert msgs[1] == {
        "role": "tool", "content": INTERRUPTED, "tool_call_id": "c1", "name": "a", "is_error": True,
    }


async def test_interrupt_during_confirm_leaves_a_balanced_transcript(
    make_session: Make, counter: Counter
) -> None:
    from agent_shell.session.api import ConfirmRequested

    s = make_session([[Call(name="gpu", args={})]], broker=True)
    await s.start()
    async for ev in s.send("go"):
        if isinstance(ev, ConfirmRequested):
            await s.interrupt()
    msgs = s.transcript()
    calls = [c["id"] for m in msgs for c in m.get("tool_calls", [])]
    results = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert calls and calls == results and counter.calls == []


async def test_engine_receives_the_history_before_the_new_message(make_session: Make) -> None:
    eng = FakeEngine([[Say(text="one")], [Say(text="two")]])
    s = make_session(engine=eng, confirmer=AutoConfirmer())
    await s.start()
    await drain(s, "first")
    await drain(s, "second")
    assert eng.histories[0] == []
    assert [m["role"] for m in eng.histories[1]] == ["user", "assistant"]
    assert eng.histories[1][0]["content"] == "first"


async def test_store_migrates_a_database_from_the_first_shell_version(tmp_path: Path) -> None:
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE agent_shell_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT "
        "NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);"
        "INSERT INTO agent_shell_messages (session_id, role, content, created_at) "
        "VALUES ('s','user','kept','2026-01-01');"
    )
    con.commit()
    con.close()
    store = SessionStore(db)
    assert store.messages("s") == [{"role": "user", "content": "kept"}]
    store.add_message("s", "tool", "x", {"tool_call_id": "c"})
    assert store.messages("s")[1]["tool_call_id"] == "c"
