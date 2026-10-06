"""Real-provider smoke tests. Skipped unless AGENT_SHELL_LIVE=1 (a few cents).

    op run --env-file=.env -- env AGENT_SHELL_LIVE=1 AGENT_SHELL_LIVE_OPENAI_MODEL=<priced model> \\
        uv run pytest packages/agent-shell -m live -v
"""

from __future__ import annotations

import os

import pytest

from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ShellSettings
from agent_shell.demo import demo_config
from agent_shell.engine.base import ToolCallFinished, TextDelta, TurnCost, TurnEnd
from agent_shell.engine.factory import make_engine
from agent_shell.session.api import Session
from agent_shell.testing import drain

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

ASK = (
    "Use the lookup tool exactly once with topic 'lighting'. After it returns, reply with a "
    "single short sentence that includes the word DONE."
)


def settings_for(tmp_path) -> ShellSettings:  # type: ignore[no-untyped-def]
    return ShellSettings(agent_data_dir=tmp_path / "data", gpu_budget_usd=0.25)


def live_session(engine, tmp_path) -> Session:  # type: ignore[no-untyped-def]
    cfg = demo_config().model_copy(update={"default_budget": BudgetEnvelope(max_cost_usd=0.5)})
    return Session(cfg, settings_for(tmp_path), engine)


def openai_model() -> str:
    model = os.environ.get("AGENT_SHELL_LIVE_OPENAI_MODEL")
    if not model:
        pytest.skip("set AGENT_SHELL_LIVE_OPENAI_MODEL to a model with a price row")
    return model


async def check_tool_turn(session: Session) -> list:  # type: ignore[type-arg]
    await session.start()
    events = await drain(session, ASK)
    assert isinstance(events[-1], TurnEnd) and events[-1].reason == "complete", events[-1]
    done = [e for e in events if isinstance(e, ToolCallFinished)]
    assert [d.name for d in done] == ["lookup"] and not done[0].result.is_error
    assert "DONE" in "".join(e.text for e in events if isinstance(e, TextDelta)).upper()
    costs = [e for e in events if isinstance(e, TurnCost)]
    assert len(costs) >= 2 and all(c.cost_usd > 0 and c.input_tokens > 0 for c in costs)
    assert session.audit is not None
    assert len([r for r in session.audit.read() if r["kind"] == "turn_cost"]) == len(costs)
    return events


async def test_claude_tool_turn(tmp_path) -> None:  # type: ignore[no-untyped-def]
    session = live_session(make_engine("claude", "claude-haiku-4-5"), tmp_path)
    await check_tool_turn(session)
    await session.close()


async def test_openai_tool_turn(tmp_path) -> None:  # type: ignore[no-untyped-def]
    session = live_session(make_engine("openai", openai_model()), tmp_path)
    await check_tool_turn(session)
    await session.close()


async def test_switch_provider_keeps_the_conversation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    session = live_session(make_engine("claude", "claude-haiku-4-5"), tmp_path)
    await check_tool_turn(session)
    await session.switch_engine(make_engine("openai", openai_model()))
    events = await drain(session, "Which topic did I ask you to look up? Answer in one word.")
    assert "lighting" in "".join(e.text for e in events if isinstance(e, TextDelta)).lower()
    await session.switch_engine(make_engine("claude", "claude-haiku-4-5"))
    events = await drain(session, "And what was the single word you were told to include? One word.")
    assert "done" in "".join(e.text for e in events if isinstance(e, TextDelta)).lower()
    assert session.audit is not None
    assert len([r for r in session.audit.read() if r["kind"] == "provider_switch"]) == 2
    await session.close()


async def test_claude_prompt_caching_reads_on_the_second_call(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Needs a prompt over Anthropic's minimum cacheable size; pads the system prompt."""
    cfg = demo_config().model_copy(update={
        "system_prompt": "You are a demo agent. " + "Reference note. " * 1200,
        "default_budget": BudgetEnvelope(max_cost_usd=0.5),
    })
    session = Session(cfg, settings_for(tmp_path), make_engine("claude", "claude-haiku-4-5"))
    await session.start()
    first = await drain(session, "Say hi in one word.")
    second = await drain(session, "Say bye in one word.")
    c1 = [e for e in first if isinstance(e, TurnCost)][0]
    c2 = [e for e in second if isinstance(e, TurnCost)][0]
    assert c1.cache_write_tokens > 0 or c1.cache_read_tokens > 0
    assert c2.cache_read_tokens > 0
    await session.close()
