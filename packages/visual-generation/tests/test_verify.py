"""Tests for knowledge-verify (visual_generation.verify)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.constants import (
    TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
    TUTORIAL_RESEARCH_COLLECTION,
)
from visual_generation.verify import verify_knowledge


def _store() -> MagicMock:
    store = MagicMock()
    store.search_generations = AsyncMock(return_value=[])
    store.search_lessons = AsyncMock(return_value=[])
    store.search_templates = AsyncMock(return_value=[])
    return store


def _memory(counts: dict[str, int]) -> MagicMock:
    mem = MagicMock()
    mem.embedding_client = MagicMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mem.query_by_vector = AsyncMock(return_value=[])  # no canon/mechanics hits
    mem.search = AsyncMock(return_value=[])  # no tutorial/technique hits

    async def _count(name, **kw):
        return counts.get(name, 0)

    mem.count_points = AsyncMock(side_effect=_count)
    return mem


@pytest.mark.asyncio
async def test_verify_flags_nothing_surfaced_and_ignored_content() -> None:
    # Collections HOLD content, but the query surfaces nothing → the loud "ignored" signal.
    counts = {TUTORIAL_RESEARCH_COLLECTION: 2211, TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION: 22}
    report = await verify_knowledge("z-image dreadlocks", _store(), _memory(counts), limit=5)

    assert report.legs == []
    assert report.collection_counts[TUTORIAL_RESEARCH_COLLECTION] == 2211
    joined = " ".join(report.gaps)
    assert "No visual knowledge surfaced" in joined
    assert "tutorial_research holds content but nothing surfaced" in joined
    assert "technique_research_outputs holds content but nothing" in joined


@pytest.mark.asyncio
async def test_verify_flags_unreachable_collection() -> None:
    mem = _memory({})
    mem.count_points = AsyncMock(side_effect=RuntimeError("qdrant down"))
    report = await verify_knowledge("q", _store(), mem, limit=5)
    assert all(v == -1 for v in report.collection_counts.values())
    assert any("unreachable or absent" in g for g in report.gaps)
