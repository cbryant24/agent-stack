from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

from tutorial_research.models import RetrievedChunk


def _chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(score=0.9, source_id="youtube:abc123", content="asyncio event loop basics"),
        RetrievedChunk(score=0.8, source_id="youtube:def456", content="async/await syntax guide"),
    ]


def test_retrieve_mode_returns_chunks():
    with (
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=_chunks())),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("asyncio tutorials", request_type="retrieve")

    assert result.request_type == "retrieve"
    assert len(result.retrieved) == 2
    assert result.retrieved[0].source_id == "youtube:abc123"


def test_retrieve_mode_no_synthesis_by_default():
    with (
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=_chunks())),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
        patch("tutorial_research.agent._synthesize", AsyncMock()) as mock_synth,
    ):
        from tutorial_research import research_sync

        result = research_sync("asyncio tutorials", request_type="retrieve")

    assert result.synthesis is None
    mock_synth.assert_not_called()


def test_retrieve_mode_uses_source_type_filter():
    from agent_runtime.memory.store import filter_by_source_type

    mock_store = MagicMock()
    mock_store.search = AsyncMock(return_value=[])

    with (
        patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        import asyncio
        from tutorial_research.retrieval import retrieve_chunks

        asyncio.run(retrieve_chunks("tutorial_research", "asyncio"))

    mock_store.search.assert_called_once()
    _, kwargs = mock_store.search.call_args
    assert kwargs["filters"] is not None


def test_retrieve_synthesize_on_calls_synthesize():
    with (
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=_chunks())),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="Summary text")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("asyncio tutorials", request_type="retrieve", synthesize=True)

    assert result.synthesis == "Summary text"
