"""Inspect commands — review-pending, chain show, recall (mocked store)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.inspect import (
    get_chain,
    list_pending,
    recall,
    render_chain,
    render_pending,
    render_recall,
)
from visual_generation.models import (
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)


def _gen(**overrides) -> VisualGeneration:
    base = dict(
        caption="a neon wolf in the rain",
        prompt="a cinematic wolf, neon rain, volumetric light",
        asset_path="/data/visual-generation/assets/wolf.png",
        model="flux1-dev.safetensors",
        settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5, "sampler": "euler"},
        reaction="loved",
        rating=5,
    )
    base.update(overrides)
    return VisualGeneration(**base)


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    return store


# ── review-pending ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_renders_settings_and_asset() -> None:
    store = _mock_store()
    pend = _gen(reaction="pending", rating=None, status="pending")
    store.list_pending = AsyncMock(return_value=[pend])

    gens = await list_pending(store=store)
    out = render_pending(gens)

    assert "1 pending generation(s)" in out
    assert pend.entry_id in out
    assert "flux1-dev.safetensors" in out
    assert "flux_guidance=3.5" in out
    assert "wolf.png" in out
    assert "report" in out  # next-step hint


def test_render_pending_empty() -> None:
    assert render_pending([]) == "No pending generations."


def test_render_pending_marks_identity_bearing() -> None:
    out = render_pending([_gen(reaction="pending", status="pending", identity_bearing=True)])
    assert "[identity-bearing]" in out


# ── chain show ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_chain_renders_root_and_children() -> None:
    store = _mock_store()
    root = _gen(caption="root frame", reaction="liked", rating=4)
    child = _gen(
        caption="refined frame",
        parent_id=root.entry_id,
        chain_root_id=root.entry_id,
        reaction="loved",
        rating=5,
        created_at="2026-06-09T01:00:00+00:00",
    )
    root.created_at = "2026-06-09T00:00:00+00:00"
    store.get_chain = AsyncMock(return_value=[root, child])

    gens = await get_chain(root.entry_id, store=store)
    out = render_chain(root.entry_id, gens)

    assert "2 generation(s)" in out
    assert root.entry_id[:12] in out
    assert child.entry_id[:12] in out
    assert "LOVED ★5" in out
    assert "LIKED ★4" in out
    # The child is rendered indented beneath the root.
    root_line = next(i for i, ln in enumerate(out.splitlines()) if root.entry_id[:12] in ln)
    child_line = next(i for i, ln in enumerate(out.splitlines()) if child.entry_id[:12] in ln)
    assert child_line > root_line
    assert out.splitlines()[child_line].startswith("  ")  # indented


def test_render_chain_empty() -> None:
    assert "No generations found" in render_chain("root-xyz", [])


# ── recall ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_surfaces_all_three_kinds_via_multimodal_query() -> None:
    store = _mock_store()
    gen = _gen()
    lesson = TechniqueLesson(statement="CFG>7 washes skin on flux1-dev.",
                             valence="negative", scope="settings", confirmed=True)
    tmpl = WorkflowTemplate(name="flux-txt2img", descriptor="basic flux still",
                            slot_map={"positive": {"node_id": "6", "input_key": "text"}})

    store.search_generations = AsyncMock(return_value=[(gen.entry_id, 0.91, gen)])
    store.search_lessons = AsyncMock(return_value=[(lesson.entry_id, 0.80, lesson)])
    store.search_templates = AsyncMock(return_value=[(tmpl.entry_id, 0.70, tmpl)])

    gens, lessons, templates = await recall("neon wolf", store=store, limit=5)

    # Generations go through the store's multimodal query-space surface.
    store.search_generations.assert_awaited_once_with("neon wolf", exclude_pending=True, limit=5)
    store.search_lessons.assert_awaited_once()
    store.search_templates.assert_awaited_once()

    out = render_recall(gens, lessons, templates)
    assert "Prior Generations (1)" in out
    assert "Technique Lessons (1)" in out
    assert "Workflow Templates (1)" in out
    assert "wolf.png" in out
    assert "CFG>7" in out
    assert "flux-txt2img" in out


@pytest.mark.asyncio
async def test_recall_includes_unconfirmed_lessons() -> None:
    store = _mock_store()
    store.search_generations = AsyncMock(return_value=[])
    store.search_templates = AsyncMock(return_value=[])
    store.search_lessons = AsyncMock(return_value=[])

    await recall("x", store=store)
    # recall surfaces everything: confirmed_only is False.
    _, kwargs = store.search_lessons.call_args
    assert kwargs["confirmed_only"] is False


def test_render_recall_empty() -> None:
    assert render_recall([], [], []) == "No results found."


def test_render_recall_shows_chain_root_when_not_self() -> None:
    root_id = "11111111-1111-1111-1111-111111111111"
    gen = _gen(chain_root_id=root_id)  # entry_id != chain_root_id
    out = render_recall([(gen.entry_id, 0.9, gen)], [], [])
    assert "chain root:" in out
