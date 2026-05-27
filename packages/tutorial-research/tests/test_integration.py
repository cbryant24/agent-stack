from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

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


@requires_qdrant
def test_retrieve_against_real_qdrant():
    """Retrieve mode against real Qdrant (fake embeddings) — verify no crash, correct shape."""
    from unittest.mock import MagicMock

    fake_vector = [0.1] * 1024
    mock_embed_result = MagicMock()
    mock_embed_result.embeddings = [fake_vector]

    with (
        patch(
            "agent_runtime.memory.embeddings.EmbeddingClient.embed",
            AsyncMock(return_value=[fake_vector]),
        ),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", request_type="retrieve")

    assert result.request_type == "retrieve"
    assert result.status in ("completed", "partial")
    assert isinstance(result.retrieved, list)
