"""The real tool pack inside a real agent-shell Session (scripted engine, no model, no network):
gating, dry-run, budgets and the audit trail behave as designed for these tools."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig, ShellSettings
from agent_shell.engine.base import ToolCallFinished
from agent_shell.engine.fake import Call, FakeEngine, Say
from agent_shell.guard.gate import AutoConfirmer
from agent_shell.session.api import Session
from agent_shell.testing import drain

import visual_generation.chat.tools.craft as craft_mod
from visual_generation.chat.config import build_chat_config
from visual_generation.chat.schemas import FeedbackInterpretation
from visual_generation.models import DraftResult, VisualSpec

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


def session(built: Built, script: list[list[Say | Call]], tmp_path: Path, *, dry_run: bool = False,
            confirmer: AutoConfirmer | None = None, tool_budget: float = 0.5) -> Session:
    cfg: ChatConfig = build_chat_config(built.state)
    return Session(cfg, ShellSettings(agent_data_dir=tmp_path / "shell", dry_run=dry_run, tool_budget_usd=tool_budget),
                   FakeEngine(script), confirmer=confirmer or AutoConfirmer())


def drafted(cost: float = 0.04) -> DraftResult:
    return DraftResult(spec=VisualSpec(prompt="p", heading="h"), template_name="z-image-turbo",
                       template_modality="text2img", status="completed", cost_usd=cost)


async def test_feedback_flows_through_propose_interpretation_and_stores_nothing(
    build: Callable[..., Built], tmp_path: Path
) -> None:
    b = build(gens=make_gens(8))
    args = {"feedback": "attempt-03 looks plastic; also attempt-14?", "observations": [
        {"label": "attempt-03", "layer": "production_quality", "category": "identity",
         "attribution": "conditioning", "claim": "button eyes", "status": "observed"},
        {"label": "attempt-14", "layer": "production_quality", "category": "staging",
         "attribution": "conditioning", "claim": "holding the key", "status": "inferred"}]}
    s = session(b, [[Call(name="propose_interpretation", args=args)]], tmp_path)
    await s.start()
    events = await drain(s, "feedback")
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    fi = FeedbackInterpretation.model_validate(fin.result.data)
    assert not fin.result.is_error and fi.observations[0].resolved_gen_id and fi.observations[1].resolved_gen_id is None
    assert any("attempt-14" in q for q in fi.open_questions)
    assert b.writes == []


async def test_a_draft_within_budget_runs_without_asking_and_charges_the_tool_budget(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted(0.04))
    monkeypatch.setattr(craft_mod, "_draft", spy)
    c = AutoConfirmer()
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert spy.await_count == 1 and c.requests == []                 # estimate fits the budget: no prompt
    assert s.budgets.tool.spent == pytest.approx(0.04)
    assert s.audit is not None and s.audit.read()[0]["tool"] == "draft"


async def test_a_draft_that_would_exceed_the_tool_budget_asks_first(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted())
    monkeypatch.setattr(craft_mod, "_draft", spy)
    c = AutoConfirmer("reject")
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, confirmer=c, tool_budget=0.01)
    await s.start()
    await drain(s, "go")
    assert len(c.requests) == 1 and "exceeds tool budget" in (c.requests[0].warning or "")
    assert spy.await_count == 0


async def test_dry_run_describes_craft_tools_and_calls_no_model(
    build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = AsyncMock(return_value=drafted())
    monkeypatch.setattr(craft_mod, "_draft", spy)
    s = session(build(), [[Call(name="draft", args={"intent": "fog"})]], tmp_path, dry_run=True)
    await s.start()
    events = await drain(s, "go")
    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.text.startswith("[dry-run] would run draft") and spy.await_count == 0


async def test_read_tools_never_prompt(build: Callable[..., Built], tmp_path: Path) -> None:
    c = AutoConfirmer()
    s = session(build(gens=make_gens(2)), [[Call(name="recall", args={"query": "x"}), Call(name="digest", args={})]],
                tmp_path, confirmer=c)
    await s.start()
    await drain(s, "go")
    assert c.requests == []


async def test_the_session_exposes_exactly_the_chat_tools(build: Callable[..., Built], tmp_path: Path) -> None:
    from .test_reachability import EXPECTED  # type: ignore[import-not-found]

    s = session(build(), [], tmp_path)
    await s.start()
    assert set(s.registry.names()) == EXPECTED
    assert s.config.on_session_end is None and s.budgets.gpu.max_usd == 0.0
    assert isinstance(s.config.default_budget, BudgetEnvelope)
