from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from technique_research.constants import TECHNIQUE_OUTPUTS_COLLECTION
from technique_research.models import TechniqueFinding
from technique_research.store import TechniqueResearchStore


@pytest.mark.asyncio
async def test_upsert_findings_writes_memory_points() -> None:
    ms = MagicMock()
    ms.ensure_collection = AsyncMock()
    ms.upsert_points = AsyncMock()
    store = TechniqueResearchStore(ms)

    f = TechniqueFinding(technique="Masking", description="isolate a subject")
    ids = await store.upsert_findings([f], "run-7")

    ms.upsert_points.assert_awaited_once()
    collection, points = ms.upsert_points.await_args.args
    assert collection == TECHNIQUE_OUTPUTS_COLLECTION
    assert points[0].source_type == "agent_summary"
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_upsert_empty_is_noop() -> None:
    ms = MagicMock()
    ms.upsert_points = AsyncMock()
    store = TechniqueResearchStore(ms)
    assert await store.upsert_findings([], "r") == []
    ms.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_findings_reconstructs_and_degrades() -> None:
    ms = MagicMock()
    payload = TechniqueFinding(technique="Bloom", description="glow").to_payload()
    ms.search = AsyncMock(return_value=[
        SimpleNamespace(score=0.81, point=SimpleNamespace(metadata=payload)),
    ])
    store = TechniqueResearchStore(ms)
    out = await store.search_findings("glow", limit=3)
    assert out[0][0] == 0.81
    assert out[0][1].technique == "Bloom"

    ms.search = AsyncMock(side_effect=RuntimeError("collection missing"))
    assert await store.search_findings("x") == []
