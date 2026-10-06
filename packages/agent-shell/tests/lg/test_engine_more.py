from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agent_runtime.config import reset_config
from agent_shell.engine.base import TextDelta, ToolCallFinished, TurnEnd
from agent_shell.engine.factory import EngineConfigError, make_engine
from agent_shell.engine.langgraph_engine import LangGraphEngine, text_of
from agent_shell.session.api import Session
from agent_shell.testing import Counter, drain

pytestmark = pytest.mark.asyncio
Make = Callable[..., Session]
SimMaker = Callable[..., Any]


async def test_text_of_handles_strings_blocks_and_junk() -> None:
    assert text_of("abc") == "abc"
    blocks = [{"type": "text", "text": "a"}, {"type": "tool_use", "id": "x"}, "b", {"type": "text", "text": "c"}]
    assert text_of(blocks) == "abc"
    assert text_of(None) == "" and text_of([]) == ""


async def test_claude_engine_marks_the_system_prompt_and_last_tool_for_caching(
    make_session: Make, sim: SimMaker
) -> None:
    s = sim([{"text": "hi"}], provider="claude")
    session = make_session(engine=s.engine)
    await session.start()
    await drain(session, "x")
    system = s.model.seen[0][0]
    assert isinstance(system, SystemMessage) and isinstance(system.content, list)
    block = cast(list[dict[str, Any]], system.content)[0]
    assert block["cache_control"] == {"type": "ephemeral"}
    extras = [getattr(t, "extras", None) for t in s.model.bound]
    assert extras[-1] == {"cache_control": {"type": "ephemeral"}}
    assert all(not e for e in extras[:-1]) and len(extras) == 3


async def test_openai_engine_sends_neither_marker(make_session: Make, sim: SimMaker) -> None:
    s = sim([{"text": "hi"}], provider="openai")
    session = make_session(engine=s.engine)
    await session.start()
    await drain(session, "x")
    system = s.model.seen[0][0]
    assert isinstance(system, SystemMessage) and isinstance(system.content, str)
    assert all(not getattr(t, "extras", None) for t in s.model.bound)


async def test_markers_survive_into_the_real_anthropic_request(make_session: Make, sim: SimMaker) -> None:
    """Offline check against langchain-anthropic's own payload builder (no network)."""
    from langchain_anthropic import ChatAnthropic

    s = sim([{"text": "hi"}], provider="claude")
    session = make_session(engine=s.engine)
    await session.start()
    tools = list(s.engine._tools.values())
    llm = ChatAnthropic(model="claude-sonnet-4-6", api_key="x", max_tokens=100)  # type: ignore[call-arg,arg-type]
    bound = llm.bind_tools(tools)
    payload: dict[str, Any] = dict(llm._get_request_payload(
        [s.engine._system_message(), HumanMessage(content="hello")],
        **bound.kwargs,  # type: ignore[attr-defined]
    ))
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in payload["tools"][0]


async def test_an_unpriced_model_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="no price"):
        LangGraphEngine("openai", "gpt-9-imaginary", "k")


@pytest.fixture
def fresh_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    def setup(**env: str | None) -> None:
        for k in ("CHAT_OPENAI_API_KEY", "PRODUCTION_AGENTS_OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            if v is not None:
                monkeypatch.setenv(k, v)
        reset_config()

    yield setup
    reset_config()


async def test_factory_openai_needs_a_model_a_key_and_a_price(fresh_config: Callable[..., None]) -> None:
    fresh_config()
    with pytest.raises(EngineConfigError, match="model"):
        make_engine("openai", None)
    with pytest.raises(EngineConfigError, match="CHAT_OPENAI_API_KEY"):
        make_engine("openai", "gpt-5-nano")
    fresh_config(CHAT_OPENAI_API_KEY="sk-chat")
    with pytest.raises(EngineConfigError, match="no price"):
        make_engine("openai", "gpt-9-imaginary")
    eng = make_engine("openai", "gpt-5-nano")
    assert eng.provider == "openai" and eng._api_key == "sk-chat"  # type: ignore[attr-defined]


async def test_factory_prefers_the_chat_key_and_falls_back_to_the_shared_one(
    fresh_config: Callable[..., None],
) -> None:
    fresh_config(PRODUCTION_AGENTS_OPENAI_API_KEY="sk-shared")
    assert make_engine("openai", "gpt-5-nano")._api_key == "sk-shared"  # type: ignore[attr-defined]
    fresh_config(PRODUCTION_AGENTS_OPENAI_API_KEY="sk-shared", CHAT_OPENAI_API_KEY="sk-chat")
    assert make_engine("openai", "gpt-5-nano")._api_key == "sk-chat"  # type: ignore[attr-defined]


async def test_factory_claude_default_model_is_priced(fresh_config: Callable[..., None]) -> None:
    fresh_config()
    eng = make_engine("claude")
    assert eng.provider == "claude" and eng.model == "claude-sonnet-4-6"
    with pytest.raises(EngineConfigError, match="no price"):
        make_engine("claude", "claude-unlisted-9")


async def test_interrupt_mid_stream_leaves_the_next_turn_usable(make_session: Make, sim: SimMaker) -> None:
    s = sim([{"text": " ".join(["w"] * 100)}, {"text": "after"}], delay=0.01)
    session = make_session(engine=s.engine)
    await session.start()
    seen = 0
    async for ev in session.send("go"):
        seen += 1
        if seen == 3:
            await session.interrupt()
    events = await drain(session, "again")
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete"
    assert "after" in "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_interrupt_during_a_tool_confirm_repairs_history_for_the_next_model_call(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    from langchain_core.messages import ToolMessage

    from agent_shell.session.api import ConfirmRequested

    s = sim([{"calls": [("gpu", {})]}, {"text": "next"}])
    session = make_session(engine=s.engine, broker=True)
    await session.start()
    async for ev in session.send("go"):
        if isinstance(ev, ConfirmRequested):
            await session.interrupt()
    await drain(session, "again")
    last = s.model.seen[-1]
    tool_msgs = [m for m in last if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1 and tool_msgs[0].status == "error"
    assert "Interrupted" in str(tool_msgs[0].content) and counter.calls == []


async def test_runaway_tool_loop_stops_at_the_recursion_limit(
    make_session: Make, sim: SimMaker, counter: Counter
) -> None:
    s = sim([{"calls": [("read", {})]}] * 30, recursion_limit=5)
    session = make_session(engine=s.engine)
    await session.start()
    events = await drain(session, "loop")
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "error"
    assert "5 steps" in events[-1].detail
    assert 0 < len(counter.calls) < 5
    assert sum(isinstance(e, ToolCallFinished) for e in events) == len(counter.calls)
