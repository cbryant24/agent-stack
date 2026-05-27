from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent_runtime import BudgetEnvelope

from tutorial_research.models import CandidateEntry, ScoredCandidate


def _candidate(url: str) -> CandidateEntry:
    return CandidateEntry(
        url=url,
        title="Tutorial",
        channel="Channel",
        description="desc",
        duration_seconds=600,
        view_count=1000,
        upload_date="20240101",
        has_captions=True,
    )


def _scored(url: str) -> ScoredCandidate:
    return ScoredCandidate(
        url=url,
        title="Tutorial",
        channel="Channel",
        duration_seconds=600,
        view_count=1000,
        has_captions=True,
        score=4,
        rationale="Good tutorial.",
    )


URLS = [
    "https://youtube.com/watch?v=vid1",
    "https://youtube.com/watch?v=vid2",
]


def _pipeline_result(source_id: str) -> MagicMock:
    r = MagicMock()
    r.agent_output = MagicMock()
    r.agent_output.source_id = source_id
    return r


def test_budget_exhaustion_produces_partial_result():
    # max_items=1 — second candidate triggers BudgetExhaustedError
    tight_budget = BudgetEnvelope(
        max_items=1,
        max_depth=0,
        max_cost_usd=10.0,
        max_wall_time_sec=900,
    )

    call_count = 0

    async def mock_process(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        return _pipeline_result(f"youtube:vid{call_count}")

    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", mock_process),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", budget=tight_budget)

    assert result.status == "partial"
    assert result.items_processed == 1


def test_budget_exhaustion_report_path_still_set():
    tight_budget = BudgetEnvelope(
        max_items=1,
        max_depth=0,
        max_cost_usd=10.0,
        max_wall_time_sec=900,
    )

    call_count = 0

    async def mock_process(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        return _pipeline_result(f"youtube:vid{call_count}")

    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", mock_process),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", budget=tight_budget)

    assert result.report_path is not None


def test_budget_exhaustion_run_id_present():
    tight_budget = BudgetEnvelope(
        max_items=1,
        max_depth=0,
        max_cost_usd=10.0,
        max_wall_time_sec=900,
    )

    call_count = 0

    async def mock_process(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        return _pipeline_result(f"youtube:vid{call_count}")

    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", mock_process),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", budget=tight_budget)

    assert result.run_id != ""
