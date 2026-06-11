from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.retrieval import (
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
    KnowledgeResult,
    search_knowledge,
)


def _search_result(source_id: str, text: str, score: float) -> MagicMock:
    point = MagicMock()
    point.source_id = source_id
    point.text = text
    point.source_title = f"Title: {source_id}"
    r = MagicMock()
    r.score = score
    r.point = point
    return r


def _uk_raw(entry_id: str, statement: str, score: float) -> tuple[str, float, dict]:
    return (entry_id, score, {"entry_id": entry_id, "statement": statement,
                              "domain": "music_theory", "superseded_by": ""})


class TestUserKnowledgeBoost:
    def test_user_knowledge_score_boost_applied(self) -> None:
        raw_uk_score = 0.60
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])  # no primary collection hits
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(return_value=[_uk_raw("uk-1", "A music fact", raw_uk_score)])

        results = asyncio.run(
            search_knowledge("dorian mode", "music_curation_memory", store=mock_store)
        )

        uk = [r for r in results if r.collection == USER_KNOWLEDGE_COLLECTION]
        assert len(uk) == 1
        assert uk[0].score == pytest.approx(raw_uk_score * USER_KNOWLEDGE_SCORE_MULTIPLIER)

    def test_merges_primary_and_user_knowledge(self) -> None:
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[_search_result("gen-1", "prior generation", 0.82)])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(return_value=[_uk_raw("uk-2", "fact", 0.5)])

        results = asyncio.run(
            search_knowledge("phonk bass", "music_curation_memory", store=mock_store)
        )

        collections = {r.collection for r in results}
        assert "music_curation_memory" in collections
        assert USER_KNOWLEDGE_COLLECTION in collections

    def test_graceful_degrade_when_everything_unavailable(self) -> None:
        mock_store = MagicMock()
        mock_store.search = AsyncMock(side_effect=RuntimeError("collection missing"))
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(side_effect=RuntimeError("voyage down"))
        mock_store.query_by_vector = AsyncMock(side_effect=RuntimeError("unreachable"))

        results = asyncio.run(
            search_knowledge("anything", "music_curation_memory", store=mock_store)
        )
        assert results == []

    def test_partial_degrade_returns_primary_only(self) -> None:
        # Primary collection works; user_knowledge co-query fails -> primary survives.
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[_search_result("gen-9", "kept", 0.7)])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(side_effect=RuntimeError("voyage down"))
        mock_store.query_by_vector = AsyncMock(side_effect=RuntimeError("unreachable"))

        results = asyncio.run(
            search_knowledge("q", "music_curation_memory", store=mock_store)
        )
        assert len(results) == 1
        assert results[0].collection == "music_curation_memory"


class TestNewAgentDomains:
    """The voiceover-direction and visual-generation memory domains route through
    the generic collection path and apply the boosted user_knowledge co-query."""

    @pytest.mark.parametrize(
        "domain", ["voiceover_direction_memory", "visual_generation_memory"]
    )
    def test_user_knowledge_boost_applied(self, domain: str) -> None:
        raw_uk_score = 0.60
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])  # no primary collection hits
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(
            return_value=[_uk_raw("uk-1", "an authored fact", raw_uk_score)]
        )

        results = asyncio.run(search_knowledge("delivery", domain, store=mock_store))  # type: ignore[arg-type]

        uk = [r for r in results if r.collection == USER_KNOWLEDGE_COLLECTION]
        assert len(uk) == 1
        assert uk[0].score == pytest.approx(raw_uk_score * USER_KNOWLEDGE_SCORE_MULTIPLIER)

    @pytest.mark.parametrize(
        "domain", ["voiceover_direction_memory", "visual_generation_memory"]
    )
    def test_merges_primary_and_user_knowledge(self, domain: str) -> None:
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[_search_result("own-1", "prior work", 0.82)])
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
        mock_store.query_by_vector = AsyncMock(return_value=[_uk_raw("uk-2", "fact", 0.5)])

        results = asyncio.run(search_knowledge("q", domain, store=mock_store))  # type: ignore[arg-type]

        collections = {r.collection for r in results}
        assert domain in collections
        assert USER_KNOWLEDGE_COLLECTION in collections

    @pytest.mark.parametrize(
        "domain", ["voiceover_direction_memory", "visual_generation_memory"]
    )
    def test_graceful_degrade(self, domain: str) -> None:
        mock_store = MagicMock()
        mock_store.search = AsyncMock(side_effect=RuntimeError("collection missing"))
        mock_store.embedding_client = MagicMock()
        mock_store.embedding_client.embed = AsyncMock(side_effect=RuntimeError("voyage down"))
        mock_store.query_by_vector = AsyncMock(side_effect=RuntimeError("unreachable"))

        results = asyncio.run(search_knowledge("anything", domain, store=mock_store))  # type: ignore[arg-type]
        assert results == []


class TestDomainRouting:
    def test_tutorial_research_reuses_retrieve_chunks(self) -> None:
        fake_chunk = MagicMock()
        fake_chunk.score = 0.9
        fake_chunk.source_title = "Suno tutorial"
        fake_chunk.source_id = "youtube:abc"
        fake_chunk.content = "how stems work"
        fake_chunk.collection_name = "tutorial_research"

        with patch("orchestrator.retrieval.retrieve_chunks", AsyncMock(return_value=[fake_chunk])) as rc:
            results = asyncio.run(
                search_knowledge("suno stems", "tutorial_research", store=MagicMock())
            )

        rc.assert_awaited_once()
        assert results[0].collection == "tutorial_research"
        assert results[0].snippet == "how stems work"

    def test_langgraph_mechanics_queries_user_knowledge_domain(self) -> None:
        hit = MagicMock()
        hit.score = 0.88
        hit.domain = "langgraph_mechanics"
        hit.statement = "ToolNode executes tool calls from the last AI message."

        with patch("orchestrator.retrieval.UserKnowledgeStore") as UKS:
            UKS.return_value.search = AsyncMock(return_value=[hit])
            results = asyncio.run(
                search_knowledge("what is ToolNode", "langgraph_mechanics", store=MagicMock())
            )

        UKS.return_value.search.assert_awaited_once()
        _, kwargs = UKS.return_value.search.call_args
        assert kwargs.get("domain") == "langgraph_mechanics"
        assert results[0].collection == USER_KNOWLEDGE_COLLECTION

    def test_unknown_domain_raises(self) -> None:
        with pytest.raises(ValueError):
            asyncio.run(search_knowledge("x", "nonsense_domain", store=MagicMock()))  # type: ignore[arg-type]


def test_knowledge_result_shape() -> None:
    kr = KnowledgeResult(score=1.0, label="L", snippet="S", collection="C")
    assert (kr.score, kr.label, kr.snippet, kr.collection) == (1.0, "L", "S", "C")
