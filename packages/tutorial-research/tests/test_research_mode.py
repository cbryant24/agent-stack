from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from agent_runtime import TraceEvent

from tutorial_research.models import CandidateEntry, RetrievedChunk, ScoredCandidate


def _candidate(url: str) -> CandidateEntry:
    return CandidateEntry(
        url=url,
        title="Python Asyncio Deep Dive",
        channel="TechChannel",
        description="Comprehensive asyncio tutorial.",
        duration_seconds=1200,
        view_count=50000,
        upload_date="20240101",
        has_captions=True,
    )


def _scored(url: str, score: int = 5) -> ScoredCandidate:
    return ScoredCandidate(
        url=url,
        title="Python Asyncio Deep Dive",
        channel="TechChannel",
        duration_seconds=1200,
        view_count=50000,
        has_captions=True,
        score=score,
        rationale="Excellent coverage of asyncio patterns.",
    )


def _pipeline_result(source_id: str) -> MagicMock:
    r = MagicMock()
    r.agent_output = MagicMock()
    r.agent_output.source_id = source_id
    return r


URLS = [
    "https://youtube.com/watch?v=aaa",
    "https://youtube.com/watch?v=bbb",
]


def test_research_mode_happy_path():
    chunks = [RetrievedChunk(score=0.9, source_id="youtube:aaa", content="event loop internals")]
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(side_effect=lambda u, **kw: _pipeline_result(f"youtube:{u.split('=')[1]}"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=chunks)),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="Synthesis result")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio patterns")

    assert result.request_type == "research"
    assert result.status == "completed"
    assert len(result.ingested) == 2
    assert result.synthesis == "Synthesis result"
    assert result.plan is not None
    assert result.plan.estimated_items == 2
    assert result.report_path == Path("/tmp/report.md")


def test_render_report_failure_is_logged_not_raised():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=[URLS[0]])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URLS[0]))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URLS[0])])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result("youtube:aaa"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", side_effect=FileNotFoundError("trace missing")),
        patch("tutorial_research.agent.notify_run_complete"),
        patch("tutorial_research.agent.logger") as mock_logger,
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio patterns")

    assert result.status == "completed"
    assert result.report_path is None
    mock_logger.warning.assert_called()
    assert "report" in str(mock_logger.warning.call_args).lower()


def test_research_mode_synthesis_on_by_default():
    chunks = [RetrievedChunk(score=0.9, source_id="youtube:aaa", content="asyncio basics")]
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(side_effect=lambda u, **kw: _pipeline_result(f"youtube:{u.split('=')[1]}"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=chunks)),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="Synthesis")) as mock_synth,
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        research_sync("python asyncio patterns")

    mock_synth.assert_called_once()


def test_research_mode_synthesis_off():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(side_effect=lambda u, **kw: _pipeline_result(f"youtube:{u.split('=')[1]}"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock()) as mock_synth,
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio patterns", synthesize=False)

    assert result.synthesis is None
    mock_synth.assert_not_called()


def test_tavily_failure_falls_back_to_retrieve():
    chunks = [RetrievedChunk(score=0.8, source_id="youtube:existing", content="existing content")]
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(side_effect=Exception("Tavily unavailable"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=chunks)),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="Fallback synthesis")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio patterns")

    assert result.request_type == "research"
    assert result.status == "completed"
    assert result.plan is not None
    assert result.plan.candidates == []
    assert result.ingested == []
    assert len(result.retrieved) == 1


def test_research_mode_metadata_filter_drop_propagates():
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=["https://youtube.com/watch?v=live"])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=None)),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[])),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio patterns")

    assert result.plan is not None
    assert result.plan.candidates == []
    assert result.ingested == []


def test_research_mode_scores_candidates_with_correct_model():
    """Verify that score_candidates is called (implying MODEL_SCORER is used inside)."""
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=[URLS[0]])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URLS[0]))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URLS[0])])) as mock_score,
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result("youtube:aaa"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        research_sync("python asyncio patterns")

    mock_score.assert_called_once()
    topic_arg = mock_score.call_args[0][0]
    assert topic_arg == "python asyncio patterns"


# ── Coverage assessment tests ────────────────────────────────────────────────

def _coverage_event(mock_persister: MagicMock) -> TraceEvent | None:
    for c in mock_persister.record.call_args_list:
        event = c.args[0]
        if isinstance(event, TraceEvent) and event.metadata.get("event_subtype") == "coverage_assessment":
            return event
    return None


def _make_chunks(
    count: int,
    score: float,
    source_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    ids = source_ids or [f"youtube:src{i}" for i in range(count)]
    return [
        RetrievedChunk(score=score, source_id=ids[i % len(ids)], content=f"chunk {i}")
        for i in range(count)
    ]


def _research_with_chunks(chunks: list[RetrievedChunk]) -> MagicMock:
    mock_persister = MagicMock()
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=[URLS[0]])),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(return_value=_candidate(URLS[0]))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(URLS[0])])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(return_value=_pipeline_result("youtube:aaa"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=chunks)),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.get_current_persister", return_value=mock_persister),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync
        research_sync("python asyncio patterns")
    return mock_persister


def test_coverage_assessment_empty():
    mock_persister = _research_with_chunks([])
    event = _coverage_event(mock_persister)
    assert event is not None
    assert event.metadata["assessment"] == "empty"
    assert event.metadata["retrieved_count"] == 0
    assert event.metadata["max_score"] is None


def test_coverage_assessment_sparse():
    chunks = _make_chunks(count=3, score=0.40, source_ids=["youtube:a", "youtube:b", "youtube:c"])
    mock_persister = _research_with_chunks(chunks)
    event = _coverage_event(mock_persister)
    assert event is not None
    assert event.metadata["assessment"] == "sparse"
    assert event.metadata["max_score"] == pytest.approx(0.40)


def test_coverage_assessment_thin():
    # 5 chunks, high score (0.9), but only 2 distinct source_ids → thin
    chunks = _make_chunks(count=5, score=0.90, source_ids=["youtube:a", "youtube:b"])
    mock_persister = _research_with_chunks(chunks)
    event = _coverage_event(mock_persister)
    assert event is not None
    assert event.metadata["assessment"] == "thin"
    assert event.metadata["distinct_sources"] == 2


def test_coverage_assessment_adequate():
    # 10 chunks, 5 distinct sources, high scores
    chunks = _make_chunks(
        count=10,
        score=0.85,
        source_ids=[f"youtube:src{i}" for i in range(5)],
    )
    mock_persister = _research_with_chunks(chunks)
    event = _coverage_event(mock_persister)
    assert event is not None
    assert event.metadata["assessment"] == "adequate"
    assert event.metadata["retrieved_count"] == 10
    assert event.metadata["distinct_sources"] == 5


# ── Bug 2 — partial/completed status logic ───────────────────────────────────

def test_successful_run_at_max_items_returns_completed():
    """A run where exactly max_items succeed should be completed, not partial."""
    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(side_effect=lambda u, **kw: _pipeline_result(f"youtube:{u.split('=')[1]}"))),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from agent_runtime import BudgetEnvelope
        from tutorial_research import research_sync

        result = research_sync(
            "python asyncio",
            budget=BudgetEnvelope(max_items=2),
        )

    assert result.status == "completed"
    assert result.items_processed == 2


def test_one_failed_item_returns_partial():
    """A run where one process_video call fails silently should be marked partial."""
    def _fail_second(url: str, **kw: object) -> object:
        if "bbb" in url:
            raise RuntimeError("video unavailable")
        return _pipeline_result(f"youtube:{url.split('=')[1]}")

    with (
        patch("tutorial_research.agent.search_for_tutorials", AsyncMock(return_value=URLS)),
        patch("tutorial_research.agent.fetch_video_metadata", AsyncMock(side_effect=lambda u: _candidate(u))),
        patch("tutorial_research.agent.score_candidates", AsyncMock(return_value=[_scored(u) for u in URLS])),
        patch("yt_intelligence_pipeline.process_video", AsyncMock(side_effect=_fail_second)),
        patch("tutorial_research.agent.retrieve_chunks", AsyncMock(return_value=[])),
        patch("tutorial_research.agent._synthesize", AsyncMock(return_value="")),
        patch("tutorial_research.agent.render_run_report", return_value=Path("/tmp/report.md")),
        patch("tutorial_research.agent.notify_run_complete"),
    ):
        from tutorial_research import research_sync

        result = research_sync("python asyncio")

    assert result.status == "partial"
    assert result.items_processed == 1
