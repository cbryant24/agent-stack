from __future__ import annotations

import pytest

import orchestrator.agent as agent_mod
from agent_runtime.config import get_config, reset_config


def _capture_key(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    class FakeChatAnthropic:
        def __init__(self, **kwargs) -> None:
            captured["api_key"] = kwargs.get("api_key")

    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", FakeChatAnthropic)
    monkeypatch.setattr(agent_mod, "all_tools", lambda: [])
    monkeypatch.setattr(agent_mod, "build_graph", lambda model, tools, checkpointer: "graph")
    return captured


def test_build_app_uses_orchestrator_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_ANTHROPIC_API_KEY", "sk-orch-only")
    reset_config()
    captured = _capture_key(monkeypatch)

    agent_mod.build_app(checkpointer=None)

    assert get_config().orchestrator_anthropic_api_key == "sk-orch-only"
    assert captured["api_key"] == "sk-orch-only"


def test_build_app_falls_back_to_shared_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_ANTHROPIC_API_KEY", raising=False)
    reset_config()
    captured = _capture_key(monkeypatch)

    agent_mod.build_app(checkpointer=None)

    assert get_config().orchestrator_anthropic_api_key is None
    assert captured["api_key"] == "sk-test-anthropic"
