from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "agent-data"))
    monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "vault"))
    import agent_runtime.config

    agent_runtime.config.reset_config()
