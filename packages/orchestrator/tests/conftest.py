from __future__ import annotations

from pathlib import Path

import pytest


def _qdrant_reachable() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:6333/healthz", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


requires_qdrant = pytest.mark.skipif(
    not _qdrant_reachable(),
    reason="Qdrant not running at localhost:6333",
)


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", "sk-test-anthropic")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "agent-data"))
    monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "vault"))
    # Isolate tests from the developer's real .env. With env_file=".env" set on
    # RuntimeConfig.model_config, pydantic-settings reads .env (incl. the 1Password
    # op:// references) as a config source, so a delenv'd OS var would still be
    # populated from the file. Neutralize the dotenv source so the fixture's OS env
    # vars are the only config source. monkeypatch.setitem auto-restores after the test.
    from agent_runtime.config import RuntimeConfig
    monkeypatch.setitem(RuntimeConfig.model_config, "env_file", None)
    import agent_runtime.config
    agent_runtime.config.reset_config()
