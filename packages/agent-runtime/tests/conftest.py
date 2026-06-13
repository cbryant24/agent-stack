from __future__ import annotations

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


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", "sk-test-anthropic")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
