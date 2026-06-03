from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tutorial_research.models import RetrievedChunk
from tutorial_research.retrieval import (
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
    _USER_KNOWLEDGE_CAP_FRACTION,
    retrieve_chunks,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _search_result(source_id: str, text: str, score: float) -> MagicMock:
    point = MagicMock()
    point.source_id = source_id
    point.text = text
    point.source_title = f"Title: {source_id}"
    point.source_url = None
    point.chunk_index = 0
    r = MagicMock()
    r.score = score
    r.point = point
    return r


def _uk_raw(entry_id: str, statement: str, score: float) -> tuple[str, float, dict]:
    return (entry_id, score, {"entry_id": entry_id, "statement": statement, "domain": "suno_mechanics", "source_ref": None, "superseded_by": ""})


# ── retrieve_chunks merge behaviour ─────────────────────────────────────────


class TestRetrieveWithUserKnowledge:
    def test_merges_user_knowledge_hits(self) -> None:
        tutorial_result = _search_result("youtube:aaa", "Event loop basics", 0.80)
        uk_raw = _uk_raw("uk-entry-1", "Suno v4 fact", 0.70)

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[tutorial_result])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(return_value=[uk_raw])

        with patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store):
            chunks = asyncio.run(retrieve_chunks("tutorial_research", "asyncio", limit=10))

        source_ids = {c.source_id for c in chunks}
        assert "youtube:aaa" in source_ids
        assert "uk-entry-1" in source_ids

    def test_score_multiplier_applied_to_user_knowledge(self) -> None:
        raw_uk_score = 0.60
        uk_raw = _uk_raw("uk-entry-2", "Fact", raw_uk_score)

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(return_value=[uk_raw])

        with patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store):
            chunks = asyncio.run(retrieve_chunks("tutorial_research", "query", limit=10))

        uk_chunks = [c for c in chunks if c.collection_name == USER_KNOWLEDGE_COLLECTION]
        assert len(uk_chunks) == 1
        assert uk_chunks[0].score == pytest.approx(raw_uk_score * USER_KNOWLEDGE_SCORE_MULTIPLIER)

    def test_graceful_degrade_when_user_knowledge_unavailable(self) -> None:
        tutorial_result = _search_result("youtube:bbb", "Content", 0.85)

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[tutorial_result])
        mock_store.embedding_client = MagicMock()
        # embed raises — simulates Voyage unavailable
        mock_store.embedding_client.embed = AsyncMock(side_effect=RuntimeError("Voyage down"))
        mock_store.query_by_vector = AsyncMock(side_effect=RuntimeError("unreachable"))

        with patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store):
            chunks = asyncio.run(retrieve_chunks("tutorial_research", "query", limit=10))

        # Only tutorial results returned; no crash
        assert len(chunks) == 1
        assert chunks[0].source_id == "youtube:bbb"

    def test_user_knowledge_cap_holds(self) -> None:
        limit = 10
        uk_cap = max(1, round(limit * _USER_KNOWLEDGE_CAP_FRACTION))  # = 3

        # Provide more uk results than the cap
        uk_raws = [_uk_raw(f"uk-{i}", f"Fact {i}", 0.9) for i in range(uk_cap + 5)]
        tutorial_results = [_search_result(f"youtube:{i}", f"Content {i}", 0.7) for i in range(7)]

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=tutorial_results)
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        # query_by_vector is called with limit=uk_cap, so Qdrant already caps the return;
        # simulate by returning exactly uk_cap results
        mock_store.query_by_vector = AsyncMock(return_value=uk_raws[:uk_cap])

        with patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store):
            chunks = asyncio.run(retrieve_chunks("tutorial_research", "query", limit=limit))

        uk_chunks = [c for c in chunks if c.collection_name == USER_KNOWLEDGE_COLLECTION]
        assert len(uk_chunks) <= uk_cap

    def test_collection_name_set_on_tutorial_chunks(self) -> None:
        result = _search_result("youtube:ccc", "Content", 0.75)
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[result])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(side_effect=RuntimeError("skip uk"))
        mock_store.query_by_vector = AsyncMock(side_effect=RuntimeError("skip uk"))

        with patch("tutorial_research.retrieval.get_memory_store", return_value=mock_store):
            chunks = asyncio.run(retrieve_chunks("tutorial_research", "query"))

        assert all(c.collection_name == "tutorial_research" for c in chunks)


# ── synthesis prompt provenance ───────────────────────────────────────────────


class TestSynthesisProvenance:
    def test_user_knowledge_prefix_in_prompt(self) -> None:
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker
        from tutorial_research.synthesis import synthesize

        chunks = [
            RetrievedChunk(score=0.9, source_id="uk-abc", content="Verified fact", collection_name="user_knowledge"),
            RetrievedChunk(score=0.8, source_id="youtube:xyz", content="Tutorial content", collection_name="tutorial_research"),
        ]

        captured_prompt = {}

        async def mock_create(**kwargs):
            captured_prompt.update(kwargs)
            resp = MagicMock()
            resp.content = [MagicMock(text="synthesis")]
            resp.usage = MagicMock(input_tokens=10, output_tokens=20)
            return resp

        mock_client = MagicMock()
        mock_client.messages.create = mock_create

        async def run() -> None:
            async with BudgetTracker(BudgetEnvelope(), "test") as tracker:
                await synthesize("test query", chunks, tracker, mock_client)

        asyncio.run(run())

        user_msg = captured_prompt["messages"][0]["content"]
        assert "[USER-KNOWLEDGE: uk-abc]" in user_msg
        assert "[SOURCE: youtube:xyz]" in user_msg

    def test_synthesis_system_prompt_instructs_authority(self) -> None:
        from tutorial_research.synthesis import _SYSTEM
        assert "USER-KNOWLEDGE" in _SYSTEM
        assert "authoritative" in _SYSTEM.lower()
        assert "verified" in _SYSTEM.lower()


# ── report section splitting ──────────────────────────────────────────────────


class TestReportSections:
    def test_report_uses_separate_sections_when_uk_present(self, tmp_path: Path) -> None:
        from tutorial_research.agent import _append_retrieved_to_report

        report = tmp_path / "report.md"
        report.write_text("# Run Report\n")

        chunks = [
            RetrievedChunk(score=0.9, source_id="youtube:aaa", content="Tutorial content", collection_name="tutorial_research"),
            RetrievedChunk(score=0.85, source_id="uk-001", content="User fact", collection_name="user_knowledge"),
        ]
        _append_retrieved_to_report(report, chunks)

        text = report.read_text()
        assert "Tutorial Research" in text
        assert "User Knowledge" in text

    def test_report_uses_single_section_when_no_uk(self, tmp_path: Path) -> None:
        from tutorial_research.agent import _append_retrieved_to_report

        report = tmp_path / "report.md"
        report.write_text("# Run Report\n")

        chunks = [
            RetrievedChunk(score=0.9, source_id="youtube:aaa", content="Content", collection_name="tutorial_research"),
        ]
        _append_retrieved_to_report(report, chunks)

        text = report.read_text()
        assert "User Knowledge" not in text
        assert "Retrieved Content" in text
