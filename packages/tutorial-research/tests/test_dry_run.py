from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tutorial_research.models import CandidateEntry, ScoredCandidate


def _candidate(url: str = "https://youtube.com/watch?v=abc") -> CandidateEntry:
    return CandidateEntry(
        url=url,
        title="Test Video",
        channel="Test Channel",
        description="A test video about asyncio.",
        duration_seconds=600,
        view_count=10000,
        upload_date="20240101",
        has_captions=True,
    )


def _scored(url: str = "https://youtube.com/watch?v=abc") -> ScoredCandidate:
    return ScoredCandidate(
        url=url,
        title="Test Video",
        channel="Test Channel",
        duration_seconds=600,
        view_count=10000,
        has_captions=True,
        score=4,
        rationale="Highly relevant asyncio tutorial.",
    )


def test_dry_run_does_not_call_process_video():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=["https://youtube.com/watch?v=abc"])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate())),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored()])),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
        patch("yt_intelligence_pipeline.process_video", AsyncMock()) as mock_pv,
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", dry_run=True)

    assert result.plan is not None
    assert result.plan.estimated_items == 1
    assert result.ingested == []
    mock_pv.assert_not_called()


def test_dry_run_returns_plan_no_synthesis():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=["https://youtube.com/watch?v=abc"])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate())),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored()])),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio", dry_run=True)

    assert result.status == "completed"
    assert result.synthesis is None
    assert len(result.plan.selected) == 1
    assert result.plan.selected[0].score == 4
