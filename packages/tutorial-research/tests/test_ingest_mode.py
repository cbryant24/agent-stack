from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tutorial_research.models import CandidateEntry, ScoredCandidate


def _pipeline_result(source_id: str = "youtube:abc123") -> MagicMock:
    r = MagicMock()
    r.agent_output = MagicMock()
    r.agent_output.source_id = source_id
    return r


def _candidate(url: str) -> CandidateEntry:
    return CandidateEntry(
        url=url,
        title="Tutorial Video",
        channel="Channel",
        description="desc",
        duration_seconds=900,
        view_count=5000,
        upload_date="20240601",
        has_captions=True,
    )


def _scored(url: str, score: int = 4) -> ScoredCandidate:
    return ScoredCandidate(
        url=url,
        title="Tutorial Video",
        channel="Channel",
        duration_seconds=900,
        view_count=5000,
        has_captions=True,
        score=score,
        rationale="Good tutorial.",
    )


URL = "https://youtube.com/watch?v=abc123"


def test_ingest_mode_processes_urls_from_request():
    with (
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URL))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URL)])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result())),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync(URL, request_type="ingest")

    assert result.request_type == "ingest"
    assert len(result.ingested) == 1
    assert result.ingested[0].source_id == "youtube:abc123"


def test_ingest_mode_no_tavily_call():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock()) as mock_tavily,
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URL))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URL)])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result())),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        research_sync(URL, request_type="ingest")

    mock_tavily.assert_not_called()


def test_ingest_mode_no_synthesis_by_default():
    with (
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URL))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URL)])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result())),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
        patch("tutorial_research.agent._synthesize", AsyncMock()) as mock_synth,
    ):
        from tutorial_research import research_sync

        result = research_sync(URL, request_type="ingest")

    assert result.synthesis is None
    mock_synth.assert_not_called()


def test_ingest_mode_process_video_called_with_agent_output():
    with (
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URL))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URL)])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result())) as mock_pv,
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        research_sync(URL, request_type="ingest")

    mock_pv.assert_called_once_with(
        URL,
        human_output=False,
        agent_output=True,
        collection_name="tutorial_research",
    )
