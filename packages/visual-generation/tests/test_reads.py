"""The shared read-only seams (reads.py, inspect.get_generation, read_batch_diagnosed,
build_refinement_source). The Click commands print these renders unchanged; the chat tool
pack reuses them, so they are tested directly with stores injected."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation import reads
from visual_generation.batch_file import (
    BatchIssue,
    read_batch,
    read_batch_diagnosed,
    write_batch,
)
from visual_generation.canon import ProjectCanon
from visual_generation.constants import IMG2IMG_TEMPLATE_NAME, INPAINT_TEMPLATE_NAME
from visual_generation.draft import RefinementSourceError, build_refinement_source
from visual_generation.inspect import get_generation, render_generation
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    GenerationBatch,
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    VisualSpec,
    WorkflowTemplate,
)


def _store(**methods: object) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    for name, value in methods.items():
        setattr(store, name, AsyncMock(return_value=value))
    return store


# ── digest ────────────────────────────────────────────────────────────────────


def test_digest_view_and_render() -> None:
    gens = [VisualGeneration(caption=f"shot {i}", project="p", reaction="loved", rating=5) for i in range(3)]
    pending = VisualGeneration(caption="waiting", project="p")
    other = VisualGeneration(caption="elsewhere", project="other")
    lesson = TechniqueLesson(statement="CFG>7 washes skin", valence="negative", scope="settings", confirmed=True)
    store = _store(list_generations=gens, list_lessons=[lesson], list_pending=[pending, other])

    d = asyncio.run(reads.build_digest("p", store, limit=2))
    assert d.pending == [pending]                      # other project's pending is excluded
    text = reads.render_digest(d)
    assert "Digest for 'p'" in text and "(2 of 3)" in text
    assert "shot 2" in text and "shot 0" not in text    # newest first, bounded by limit
    assert "Awaiting your reaction (1)" in text and "waiting" in text
    assert "CFG>7 washes skin" in text
    store.list_generations.assert_awaited_once_with(project="p")


def test_digest_render_empty() -> None:
    store = _store(list_generations=[], list_lessons=[], list_pending=[])
    text = reads.render_digest(asyncio.run(reads.build_digest("fresh", store)))
    assert "none yet" in text and "Awaiting" not in text


# ── templates / lessons / models / canon ─────────────────────────────────────


def test_template_listing_flags_missing_models(tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path / "models.json")
    reg.add(ModelAsset(name="have.safetensors"))
    tmpl = WorkflowTemplate(name="t", descriptor="d", graph={}, slot_map={}, required_models=["have.safetensors", "gone.safetensors"])
    store = _store(search_templates=[("id", 0.9, tmpl)])
    listing = asyncio.run(reads.list_templates(store, registry=reg))
    text = reads.render_templates(listing)
    assert "1 template(s):" in text and "missing: gone.safetensors" in text


def test_template_listing_empty() -> None:
    listing = asyncio.run(reads.list_templates(_store(search_templates=[])))
    assert reads.render_templates(listing) == "No workflow templates registered."


def test_lessons_view_passes_filters_and_renders() -> None:
    le = TechniqueLesson(statement="keep denoise 0.5", valence="positive", scope="settings", confirmed=False)
    store = _store(list_lessons=[le])
    out = asyncio.run(reads.list_lessons(store, include_unconfirmed=True, scope="settings", valence="positive"))
    store.list_lessons.assert_awaited_once_with(confirmed_only=False, scope="settings", valence="positive")
    text = reads.render_lessons(out)
    assert le.entry_id in text and "(unconfirmed)" in text
    assert reads.render_lessons([]) == "No technique lessons."


def test_models_render(tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path / "models.json")
    reg.add(ModelAsset(name="narrator.safetensors", kind="lora", identity_bearing=True))
    reg.add(ModelAsset(name="base.safetensors", present_on_endpoint=False))
    text = reads.render_models(reads.list_models(reg))
    assert "2 registered asset(s)" in text
    assert "identity-bearing" in text and "absent-from-last-sync" in text
    assert "Run: agent visual-generation model sync" in reads.render_models([])


def test_canon_view(tmp_path: Path) -> None:
    canon = ProjectCanon("proj", base_dir=tmp_path)
    assert "No canon for 'proj'" in reads.render_canon(reads.show_canon("proj", canon))
    canon.set_subject(["Celeste", "the girl"], wardrobe="coat-v2", hair="auburn")
    text = reads.render_canon(reads.show_canon("proj", canon))
    assert "Canon for 'proj' (1 subject(s))" in text
    assert "aliases: Celeste, the girl" in text and "wardrobe: coat-v2" in text and "hair:     auburn" in text


# ── generation detail ────────────────────────────────────────────────────────


def test_get_generation_and_render() -> None:
    gen = VisualGeneration(caption="c", prompt="a foggy street", project="p", seed=7, width=832, height=1216,
                           notes="too plastic")
    store = _store(get_generation=gen)
    got = asyncio.run(get_generation(gen.entry_id, store=store))
    text = render_generation(got)
    assert gen.entry_id in text and "a foggy street" in text and "832x1216" in text
    assert "too plastic" in text and "stays pending until reported" in text    # KI-4 stated, not hidden
    assert render_generation(None, "abc") == "No generation found with id 'abc'."


# ── batch diagnostics ────────────────────────────────────────────────────────


def _write(tmp_path: Path, *specs: VisualSpec) -> Path:
    path = tmp_path / "batch.md"
    write_batch(GenerationBatch(project="p", specs=list(specs)), path)
    return path


def test_diagnosed_read_matches_read_batch_on_a_clean_file(tmp_path: Path) -> None:
    path = _write(tmp_path, VisualSpec(heading="One", prompt="a", settings={"steps": 8}))
    batch, issues = read_batch_diagnosed(path)
    assert issues == [] and batch == read_batch(path)


def test_diagnosed_read_reports_garbled_metadata_and_keeps_the_prompt(tmp_path: Path) -> None:
    path = _write(tmp_path, VisualSpec(heading="One", prompt="keep me", settings={"steps": 8}))
    path.write_text(path.read_text().replace('"steps": 8', '"steps": 8,,'), encoding="utf-8")
    batch, issues = read_batch_diagnosed(path)
    assert [i.heading for i in issues] == ["One"] and "not valid JSON" in issues[0].problem
    assert batch.specs[0].prompt.startswith("keep me") or "keep me" in batch.specs[0].prompt
    assert batch.specs[0].settings == {}                 # defaults used, and now we are told


def test_diagnosed_read_reports_a_missing_metadata_comment(tmp_path: Path) -> None:
    path = tmp_path / "hand.md"
    path.write_text("## Hand written\n\njust prose\n", encoding="utf-8")
    batch, issues = read_batch_diagnosed(path)
    assert issues == [BatchIssue("Hand written", "no vg-spec metadata comment, so settings are defaults")]
    assert batch.specs[0].prompt == "just prose"


def test_arrow_inside_rationale_truncates_metadata_and_is_reported(tmp_path: Path) -> None:
    """The known first-`-->` limitation: it can no longer fail silently."""
    path = _write(tmp_path, VisualSpec(heading="One", prompt="p", rationale="use a --> b flow", settings={"steps": 8}))
    batch, issues = read_batch_diagnosed(path)
    assert len(issues) == 1 and "'-->'" in issues[0].problem
    assert batch.specs[0].settings == {}


# ── refinement source ────────────────────────────────────────────────────────


def test_no_source_leaves_template_alone() -> None:
    assert build_refinement_source(None, None, None, "mine") == (None, "mine")
    assert build_refinement_source(None, None, None, None) == (None, None)


def test_source_defaults_the_template_by_mask() -> None:
    src, tmpl = build_refinement_source("gen-1", None, None, None)
    assert src is not None and src.from_generation == "gen-1" and tmpl == IMG2IMG_TEMPLATE_NAME
    src, tmpl = build_refinement_source(None, "/x.png", "/m.png", None)
    assert src is not None and src.mask == "/m.png" and tmpl == INPAINT_TEMPLATE_NAME
    assert build_refinement_source("gen-1", None, None, "custom")[1] == "custom"


def test_source_errors_carry_a_code() -> None:
    with pytest.raises(RefinementSourceError) as e:
        build_refinement_source("g", "/x.png", None, None)
    assert e.value.code == "both_origins"
    with pytest.raises(RefinementSourceError) as e:
        build_refinement_source(None, None, "/m.png", None)
    assert e.value.code == "mask_without_source"
