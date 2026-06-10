from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from orchestrator.agent import run_turn
from orchestrator.graph import build_graph

from ._stubs import StubModel, make_echo_tool


@pytest.mark.asyncio
async def test_two_turns_on_one_thread_resume_accumulated_state(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-stack.db"
    echo, _ = make_echo_tool()
    model = StubModel([AIMessage(content="first reply"), AIMessage(content="second reply")])
    thread_id = "resume-thread"
    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        graph = build_graph(model, [echo], saver)

        r1 = await run_turn(graph, "hello orchestrator", thread_id=thread_id)
        assert r1.response == "first reply"

        r2 = await run_turn(graph, "do you remember me?", thread_id=thread_id)
        assert r2.response == "second reply"

        # The second turn resumed the first turn's accumulated state.
        state = await graph.aget_state(config)
        messages = state.values["messages"]
        contents = [str(getattr(m, "content", "")) for m in messages]

        # human1, ai1, human2, ai2 — both turns present on the one thread.
        assert len(messages) == 4
        assert "hello orchestrator" in contents
        assert "first reply" in contents
        assert "do you remember me?" in contents
        assert "second reply" in contents


@pytest.mark.asyncio
async def test_state_persists_to_disk_across_saver_instances(tmp_path: Path) -> None:
    """A fresh saver over the same DB file sees the prior thread (resumable across
    process restarts)."""
    db_path = tmp_path / "agent-stack.db"
    echo, _ = make_echo_tool()
    thread_id = "persisted-thread"
    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        graph = build_graph(StubModel([AIMessage(content="reply one")]), [echo], saver)
        await run_turn(graph, "first session message", thread_id=thread_id)

    # New saver, same file — state survived.
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver2:
        await saver2.setup()
        graph2 = build_graph(StubModel([AIMessage(content="reply two")]), [echo], saver2)
        state = await graph2.aget_state(config)
        contents = [str(getattr(m, "content", "")) for m in state.values["messages"]]
        assert "first session message" in contents
