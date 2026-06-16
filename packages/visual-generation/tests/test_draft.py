from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.batch_file import read_batch
from visual_generation.models import (
    ModelAsset,
    TechniqueLesson,
    VisualGeneration,
    VisualSource,
    WorkflowTemplate,
)
from visual_generation.retrieval import RetrievedContext


def _template(name: str, slots: set[str]) -> WorkflowTemplate:
    """A slot-explicit template — the inert-inheritance advisory only reads slot_map."""
    return WorkflowTemplate(
        name=name, descriptor="d", graph={},
        slot_map={s: {"node_id": "1", "input_key": s} for s in slots},
    )


def _crafted(**overrides) -> dict:
    base = dict(
        prompt="a cinematic wolf in neon rain",
        negative_prompt=None,
        settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5},
        model="flux1-dev.safetensors",
        seed_strategy="fixed",
        seed=42,
        width=1024,
        height=1024,
        lora_stack=[],
        rationale="Flux runs CFG≈1.0; guidance 3.5 keeps it crisp.",
    )
    base.update(overrides)
    return base


def _store(flux_template, models) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.list_models = MagicMock(return_value=models)
    by_name = {m.name: m for m in models}
    store.get_model = lambda name: by_name.get(name)
    return store


def _patch_chain(monkeypatch, ctx: RetrievedContext, crafted: dict) -> None:
    # NB: the `draft` FUNCTION exported in __init__ shadows the `draft` submodule for
    # both dotted-string targets and `import ... as` (which uses attribute access), so
    # fetch the real module from sys.modules via importlib and patch its globals.
    import importlib

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(draft_mod, "craft_spec", AsyncMock(return_value=crafted))


def test_draft_appends_spec_and_surfaces_lessons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    ctx = RetrievedContext(
        technique_lessons=[
            (0.9, TechniqueLesson(statement="CFG>7 washes skin on flux1-dev.",
                                  valence="negative", scope="settings", confirmed=True))
        ]
    )
    _patch_chain(monkeypatch, ctx, _crafted())
    store = _store(flux_template, [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")])

    out = tmp_path / "p.batch.md"
    result = draft_sync(
        "a wolf in neon rain", batch_path=out, template_name="flux-txt2img",
        project="proj", store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )

    # Spec appended to the batch file.
    batch = read_batch(out)
    assert len(batch.specs) == 1
    assert batch.specs[0].prompt == "a cinematic wolf in neon rain"
    assert batch.specs[0].workflow_ref == "flux-txt2img"
    # Own technique lesson surfaced inline.
    assert any("washes skin" in n for n in result.tutor_notes)
    # Missing required models advised (template needs ae/t5xxl/clip_l; registry has only flux1-dev).
    assert "ae.safetensors" in result.missing_models
    # Strong local context → no research offer.
    assert result.research_offer is None


def test_draft_offers_research_on_a_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    _patch_chain(monkeypatch, RetrievedContext(), _crafted())  # empty context → gap
    store = _store(flux_template, [])

    result = draft_sync(
        "an esoteric WAN VACE control trick", batch_path=tmp_path / "p.batch.md",
        template_name="flux-txt2img", store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )
    # Gap → research is OFFERED (the topic), never run here.
    assert result.research_offer == "an esoteric WAN VACE control trick"


def test_draft_prefills_identity_from_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(lora_stack=[{"name": "char-lora.safetensors", "strength": 0.8}])
    _patch_chain(monkeypatch, RetrievedContext(
        technique_lessons=[(0.9, TechniqueLesson(statement="x", valence="positive", confirmed=True))]
    ), crafted)
    store = _store(flux_template, [
        ModelAsset(name="flux1-dev.safetensors", kind="checkpoint"),
        ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True),
    ])

    result = draft_sync(
        "portrait", batch_path=tmp_path / "p.batch.md", template_name="flux-txt2img",
        store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )
    # The honest pre-fill derives identity from the registry's LoRA flag.
    assert result.spec.identity_bearing is True


def _refinement_store(template: WorkflowTemplate, parent: VisualGeneration | None) -> MagicMock:
    store = _store(template, [ModelAsset(name="z.safetensors", kind="checkpoint")])
    store.get_generation = AsyncMock(return_value=parent)
    return store


def test_draft_warns_inherited_lora_and_dims_template_lacks_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    parent = VisualGeneration(caption="c", lora_stack=[], width=832, height=1216)
    # img2img-style template: no LoRA loader slot, no width/height slots.
    template = _template("z-img2img", {"positive", "init_image", "steps", "denoise"})
    store = _refinement_store(template, parent)

    result = draft_sync(
        "warmer key light", batch_path=tmp_path / "p.batch.md", template_name="z-img2img",
        source=VisualSource(from_generation="gen-p"),
        store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )

    assert len(result.inert_inheritance) == 2
    assert any("LoRA" in w for w in result.inert_inheritance)
    assert any("dimensions" in w for w in result.inert_inheritance)


def test_draft_no_warning_when_template_exposes_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    parent = VisualGeneration(caption="c", lora_stack=[], width=832, height=1216)
    template = _template("z-i2i-lora", {"lora_0", "width", "height", "positive", "init_image"})
    store = _refinement_store(template, parent)

    result = draft_sync(
        "warmer key light", batch_path=tmp_path / "p.batch.md", template_name="z-i2i-lora",
        source=VisualSource(from_generation="gen-p"),
        store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )

    assert result.inert_inheritance == []


def test_draft_txt2img_has_no_inert_inheritance_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from visual_generation.draft import draft_sync

    # A txt2img draft (no source/parent) carries LoRAs + dims but the gate is off.
    crafted = _crafted(
        lora_stack=[{"name": "felt.safetensors", "strength": 0.7}], width=832, height=1216,
    )
    _patch_chain(monkeypatch, RetrievedContext(), crafted)
    template = _template("txt2img", {"positive", "steps"})  # no lora/dim slots either
    store = _refinement_store(template, parent=None)

    result = draft_sync(
        "a wolf in neon rain", batch_path=tmp_path / "p.batch.md", template_name="txt2img",
        store=store, memory_store=MagicMock(), llm_client=MagicMock(),
    )

    assert result.inert_inheritance == []
