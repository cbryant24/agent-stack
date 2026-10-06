from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.models import BudgetEnvelope
from agent_shell.config import ChatConfig, ShellSettings
from agent_shell.engine.fake import FakeEngine, Step
from agent_shell.guard.gate import AutoConfirmer, Confirmer
from agent_shell.proposals import Proposal
from agent_shell.session.api import Session
from agent_shell.testing import Counter, make_tool
from agent_shell.tools.registry import EffectClass, ToolSpec


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def counter() -> Counter:
    return Counter()


@pytest.fixture
def settings(tmp_path: Path) -> ShellSettings:
    return ShellSettings(agent_data_dir=tmp_path / "data", gpu_budget_usd=1.0, tool_budget_usd=0.5)


def make_config(
    tools: Callable[[], list[ToolSpec]], *, budget: float = 1.0,
    on_end: Callable[..., list[Proposal]] | None = None,
) -> ChatConfig:
    return ChatConfig(
        agent_name="t", system_prompt="sys", tool_pack=tools,
        default_budget=BudgetEnvelope(max_cost_usd=budget), on_session_end=on_end,
    )


@pytest.fixture
def make_session(settings: ShellSettings, counter: Counter) -> Callable[..., Session]:
    def build(
        script: list[list[Step]] | None = None, *, confirmer: Confirmer | None = None,
        tools: list[ToolSpec] | None = None, budget: float = 1.0, engine: FakeEngine | None = None,
        on_end: Callable[..., list[Proposal]] | None = None, broker: bool = False, **kw: Any,
    ) -> Session:
        pack = tools if tools is not None else [
            make_tool("read", EffectClass.READ, counter),
            make_tool("mem", EffectClass.MEMORY_WRITE, counter),
            make_tool("gpu", EffectClass.GPU_SPEND, counter, cost=0.25, est=0.25),
        ]
        return Session(
            make_config(lambda: pack, budget=budget, on_end=on_end), settings,
            engine or FakeEngine(script or [], **kw), confirmer=None if broker else (confirmer or AutoConfirmer()),
        )

    return build
