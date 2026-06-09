from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from visual_generation.models import VisualGeneration
from visual_generation.report import report_sync


def _gen() -> VisualGeneration:
    return VisualGeneration(caption="a wolf", asset_path="/x/a.png", prompt="a wolf")


def _store(gen: VisualGeneration | None) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_generation = AsyncMock(return_value=gen)
    store.update_generation_reaction = AsyncMock()
    return store


def test_report_records_reaction_without_reembed() -> None:
    gen = _gen()
    store = _store(gen)

    out = report_sync(gen.entry_id, "loved", rating=5, notes="great skin",
                      context="exactly the look", store=store)

    assert out is gen
    # No re-embed surface touched; reaction recorded with rating/notes/context.
    store.update_generation_reaction.assert_awaited_once()
    args, kwargs = store.update_generation_reaction.call_args
    assert args[0] == gen.entry_id
    assert args[1] == "loved"
    assert kwargs == {"rating": 5, "notes": "great skin", "context": "exactly the look"}


def test_report_returns_none_when_generation_absent() -> None:
    store = _store(None)
    out = report_sync("missing", "liked", store=store)
    assert out is None
    store.update_generation_reaction.assert_not_called()
