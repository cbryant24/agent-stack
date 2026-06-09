from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.constants import (
    COLLECTION_NAME,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TECHNIQUE_LESSON,
    MEMORY_TYPE_WORKFLOW_TEMPLATE,
    STATUS_COMPLETE,
)
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    LoraRef,
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)
from visual_generation.store import VisualGenerationStore


def _make_store(registry: ModelRegistry | None = None) -> tuple[VisualGenerationStore, MagicMock]:
    mock_memory = MagicMock()
    mock_memory.embedding_client = MagicMock()
    mock_memory.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mock_memory.embedding_client.embed_multimodal = AsyncMock(return_value=[[0.2] * 1024])
    mock_memory.upsert_raw_points = AsyncMock()
    mock_memory.set_payload = AsyncMock()
    mock_memory.retrieve_points = AsyncMock(return_value=[])
    mock_memory.query_by_vector = AsyncMock(return_value=[])
    mock_memory.ensure_collection = AsyncMock()
    store = VisualGenerationStore(mock_memory, model_registry=registry)
    return store, mock_memory


def _gen(asset_path: Path, **overrides) -> VisualGeneration:
    base = dict(
        caption="A neon-lit cyberpunk alley at night",
        asset_path=str(asset_path),
        prompt="cyberpunk alley, neon, rain",
        model="flux1-dev",
        lora_stack=[LoraRef(name="char-lora", strength=0.8)],
        seed=12345,
        width=1024,
        height=1024,
    )
    base.update(overrides)
    return VisualGeneration(**base)


def _match_values(filters) -> dict[str, object]:
    """Collapse a qdrant Filter's must-conditions into {key: value}."""
    return {c.key: c.match.value for c in filters.must}


def _record(gen: VisualGeneration) -> SimpleNamespace:
    return SimpleNamespace(id=gen.entry_id, payload=gen.to_payload())


# ── Construction ─────────────────────────────────────────────────────────────


def test_default_collection() -> None:
    store, _ = _make_store()
    assert store._collection == COLLECTION_NAME


def test_custom_collection() -> None:
    store = VisualGenerationStore(MagicMock(), collection_name="test_collection")
    assert store._collection == "test_collection"


@pytest.mark.asyncio
async def test_ensure_collection_uses_embedding_dim() -> None:
    store, mock_memory = _make_store()
    await store.ensure_collection()
    mock_memory.ensure_collection.assert_awaited_once_with(COLLECTION_NAME, vector_size=1024)


# ── Generation writes (multimodal) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_generation_embeds_multimodal_and_sets_memory_type(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    gen = _gen(png_asset)
    await store.upsert_generation(gen)

    # Embedded via the multimodal surface, NOT the text surface.
    mock_memory.embedding_client.embed_multimodal.assert_awaited_once()
    mock_memory.embedding_client.embed.assert_not_called()
    mm_input = mock_memory.embedding_client.embed_multimodal.call_args[0][0][0]
    assert mm_input.text == gen.caption
    assert mm_input.image_path == png_asset

    point = mock_memory.upsert_raw_points.call_args[0][1][0]
    assert point.id == gen.entry_id
    assert point.payload["memory_type"] == MEMORY_TYPE_GENERATION
    # Asset is referenced by path; no binary bytes in the payload.
    assert point.payload["asset_path"] == str(png_asset)


@pytest.mark.asyncio
async def test_generation_round_trip_preserves_settings_and_lineage(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    gen = _gen(png_asset, settings={"sampler": "euler", "steps": 28, "cfg": 3.5}, identity_bearing=True)
    await store.upsert_generation(gen)
    payload = mock_memory.upsert_raw_points.call_args[0][1][0].payload

    restored = VisualGeneration.from_payload(payload)
    assert restored.settings == {"sampler": "euler", "steps": 28, "cfg": 3.5}
    assert restored.identity_bearing is True
    assert restored.lora_stack[0].name == "char-lora"
    assert restored.lora_stack[0].strength == 0.8
    # chain_root_id self-fills to entry_id for a root generation.
    assert restored.chain_root_id == gen.entry_id


@pytest.mark.asyncio
async def test_bulk_upsert_generations(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    mock_memory.embedding_client.embed_multimodal = AsyncMock(
        return_value=[[0.2] * 1024, [0.3] * 1024]
    )
    await store.upsert_generations_bulk([_gen(png_asset), _gen(png_asset, caption="other")])
    points = mock_memory.upsert_raw_points.call_args[0][1]
    assert len(points) == 2


@pytest.mark.asyncio
async def test_bulk_upsert_generations_empty_is_noop() -> None:
    store, mock_memory = _make_store()
    await store.upsert_generations_bulk([])
    mock_memory.upsert_raw_points.assert_not_called()
    mock_memory.embedding_client.embed_multimodal.assert_not_called()


@pytest.mark.asyncio
async def test_update_generation_reaction_flips_status_without_reembedding() -> None:
    store, mock_memory = _make_store()
    await store.update_generation_reaction("gen-1", "loved", rating=5, notes="great skin")

    mock_memory.embedding_client.embed.assert_not_called()
    mock_memory.embedding_client.embed_multimodal.assert_not_called()
    coll, entry_id, payload = mock_memory.set_payload.call_args[0]
    assert coll == COLLECTION_NAME
    assert entry_id == "gen-1"
    assert payload["reaction"] == "loved"
    assert payload["status"] == STATUS_COMPLETE
    assert payload["rating"] == 5
    assert payload["notes"] == "great skin"
    assert "reacted_at" in payload


@pytest.mark.asyncio
async def test_get_generation_returns_none_when_absent() -> None:
    store, _ = _make_store()
    assert await store.get_generation("missing") is None


@pytest.mark.asyncio
async def test_get_generation_parses_record_payload(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    gen = _gen(png_asset)
    record = MagicMock()
    record.payload = gen.to_payload()
    mock_memory.retrieve_points = AsyncMock(return_value=[record])

    restored = await store.get_generation(gen.entry_id)
    assert restored is not None
    assert restored.entry_id == gen.entry_id
    assert restored.model == "flux1-dev"


@pytest.mark.asyncio
async def test_get_generation_rejects_wrong_memory_type() -> None:
    store, mock_memory = _make_store()
    record = MagicMock()
    record.payload = {"memory_type": MEMORY_TYPE_WORKFLOW_TEMPLATE}
    mock_memory.retrieve_points = AsyncMock(return_value=[record])
    assert await store.get_generation("x") is None


# ── Generation search (multimodal query path) ─────────────────────────────────


@pytest.mark.asyncio
async def test_search_generations_uses_multimodal_query(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    gen = _gen(png_asset, reaction="loved")
    mock_memory.query_by_vector = AsyncMock(return_value=[(gen.entry_id, 0.9, gen.to_payload())])

    results = await store.search_generations("neon alley")

    # The query is embedded through the multimodal surface, not the text surface,
    # so it shares the stored vectors' voyage-multimodal-3 space.
    mock_memory.embedding_client.embed_multimodal.assert_awaited_once()
    mock_memory.embedding_client.embed.assert_not_called()
    mm_input = mock_memory.embedding_client.embed_multimodal.call_args[0][0][0]
    assert mm_input.text == "neon alley"
    assert mm_input.image_path is None

    filters = mock_memory.query_by_vector.call_args.kwargs["filters"]
    matched = _match_values(filters)
    assert matched["memory_type"] == MEMORY_TYPE_GENERATION
    assert matched["status"] == STATUS_COMPLETE  # exclude_pending default

    assert len(results) == 1
    pid, score, parsed = results[0]
    assert pid == gen.entry_id
    assert score == 0.9
    assert isinstance(parsed, VisualGeneration)


@pytest.mark.asyncio
async def test_search_generations_can_include_pending() -> None:
    store, mock_memory = _make_store()
    await store.search_generations("x", exclude_pending=False)
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert "status" not in matched


# ── list_pending / get_chain (scroll) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_filters_pending_and_sorts(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    older = _gen(png_asset, created_at="2026-06-01T00:00:00+00:00")
    newer = _gen(png_asset, created_at="2026-06-02T00:00:00+00:00")
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(return_value=([_record(newer), _record(older)], None))

    pending = await store.list_pending()

    assert [g.created_at for g in pending] == [older.created_at, newer.created_at]
    matched = _match_values(mock_memory._client.scroll.call_args.kwargs["scroll_filter"])
    assert matched["memory_type"] == MEMORY_TYPE_GENERATION
    assert matched["status"] == "pending"


@pytest.mark.asyncio
async def test_list_pending_paginates_without_truncation(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    page1 = [_record(_gen(png_asset)) for _ in range(100)]
    page2 = [_record(_gen(png_asset))]
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(side_effect=[(page1, "next"), (page2, None)])

    pending = await store.list_pending()

    assert len(pending) == 101
    assert mock_memory._client.scroll.await_count == 2


@pytest.mark.asyncio
async def test_get_chain_filters_by_root_and_orders(png_asset: Path) -> None:
    store, mock_memory = _make_store()
    root = _gen(png_asset, created_at="2026-06-01T00:00:00+00:00")
    child = _gen(
        png_asset,
        created_at="2026-06-02T00:00:00+00:00",
        parent_id=root.entry_id,
        chain_root_id=root.entry_id,
    )
    mock_memory._client = MagicMock()
    mock_memory._client.scroll = AsyncMock(return_value=([_record(child), _record(root)], None))

    chain = await store.get_chain(root.entry_id)

    assert [g.entry_id for g in chain] == [root.entry_id, child.entry_id]
    matched = _match_values(mock_memory._client.scroll.call_args.kwargs["scroll_filter"])
    assert matched["chain_root_id"] == root.entry_id


# ── Technique lessons ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_lesson_embeds_statement_as_text() -> None:
    store, mock_memory = _make_store()
    lesson = TechniqueLesson(
        statement="CFG above 7 washes out skin on flux1-dev.", valence="negative", scope="settings"
    )
    await store.upsert_lesson(lesson)

    # Text surface, not multimodal.
    assert lesson.statement in mock_memory.embedding_client.embed.call_args[0][0]
    mock_memory.embedding_client.embed_multimodal.assert_not_called()
    point = mock_memory.upsert_raw_points.call_args[0][1][0]
    assert point.payload["memory_type"] == MEMORY_TYPE_TECHNIQUE_LESSON


@pytest.mark.asyncio
async def test_search_lessons_filters() -> None:
    store, mock_memory = _make_store()
    await store.search_lessons("cfg skin", scope="settings", valence="negative")
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert matched["memory_type"] == MEMORY_TYPE_TECHNIQUE_LESSON
    assert matched["confirmed"] is True  # confirmed_only default
    assert matched["scope"] == "settings"
    assert matched["valence"] == "negative"


@pytest.mark.asyncio
async def test_search_lessons_can_include_unconfirmed() -> None:
    store, mock_memory = _make_store()
    await store.search_lessons("x", confirmed_only=False)
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert "confirmed" not in matched


# ── Workflow templates ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_template_embeds_descriptor_and_stores_graph() -> None:
    store, mock_memory = _make_store()
    tmpl = WorkflowTemplate(
        name="flux-txt2img",
        descriptor="basic flux text-to-image still",
        graph={"3": {"class_type": "KSampler", "inputs": {"seed": 0}}},
        slot_map={"positive": {"node_id": "6", "input_key": "text"}},
        required_models=["flux1-dev"],
    )
    await store.upsert_template(tmpl)

    assert tmpl.descriptor in mock_memory.embedding_client.embed.call_args[0][0]
    point = mock_memory.upsert_raw_points.call_args[0][1][0]
    assert point.payload["memory_type"] == MEMORY_TYPE_WORKFLOW_TEMPLATE
    # Graph + slot map round-trip faithfully.
    restored = WorkflowTemplate.from_payload(point.payload)
    assert restored.graph == tmpl.graph
    assert restored.slot_map == {"positive": {"node_id": "6", "input_key": "text"}}
    assert restored.required_models == ["flux1-dev"]


@pytest.mark.asyncio
async def test_search_templates_filters_by_memory_type() -> None:
    store, mock_memory = _make_store()
    await store.search_templates("flux still")
    matched = _match_values(mock_memory.query_by_vector.call_args.kwargs["filters"])
    assert matched["memory_type"] == MEMORY_TYPE_WORKFLOW_TEMPLATE


# ── Model/LoRA registry passthrough (no sync_models on the store) ─────────────


def test_registry_passthrough_register_list_get(tmp_path: Path) -> None:
    registry = ModelRegistry(path=tmp_path / "models.json")
    store, _ = _make_store(registry=registry)

    store.register_model(ModelAsset(name="flux1-dev", kind="checkpoint"))
    store.register_model(
        ModelAsset(name="char-lora", kind="lora", identity_bearing=True)
    )
    names = {a.name for a in store.list_models()}
    assert names == {"flux1-dev", "char-lora"}

    lora = store.get_model("char-lora")
    assert lora is not None and lora.identity_bearing is True
    assert store.get_model("nope") is None


def test_store_has_no_sync_models() -> None:
    # Step 3 owns the sync entry point and wires it through ModelRegistry.replace();
    # the store exposes register/list/get only.
    store, _ = _make_store()
    assert not hasattr(store, "sync_models")
