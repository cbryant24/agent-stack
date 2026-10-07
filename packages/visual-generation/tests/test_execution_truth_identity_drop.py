"""Entry-gate item 4: an identity LoRA the template cannot load must stop the render, not vanish."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.batch_file import write_batch
from visual_generation.generate import plan_generation_sync
from visual_generation.graph_build import build_prompt_graph, dropped_identity_loras
from visual_generation.models import GenerationBatch, LoraRef, ModelAsset, VisualSpec, WorkflowTemplate

ID_LORA = "celeste-zimage-v2.safetensors"
STYLE_LORA = "paper-texture.safetensors"
REGISTRY = {
    ID_LORA: ModelAsset(name=ID_LORA, kind="lora", identity_bearing=True),
    STYLE_LORA: ModelAsset(name=STYLE_LORA, kind="lora", identity_bearing=False),
    "narrator-zimage.safetensors": ModelAsset(name="narrator-zimage.safetensors", kind="lora", identity_bearing=True),
}


def _spec(*loras: str, **kw) -> VisualSpec:
    base = dict(prompt="a plain red mug", seed=7, width=1024, height=1024, settings={"steps": 8, "cfg": 1.0},
                model="flux1-dev.safetensors", project="proj", workflow_ref="t",
                lora_stack=[LoraRef(name=n, strength=1.0) for n in loras])
    base.update(kw)
    return VisualSpec(**base)


def _is_identity(name: str) -> bool:
    return name in REGISTRY and REGISTRY[name].identity_bearing


def _plan(tmp_path: Path, template: WorkflowTemplate, spec: VisualSpec):
    path = tmp_path / "b.batch.md"
    write_batch(GenerationBatch(project="proj", specs=[spec]), path)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    store.recent_generation_costs = AsyncMock(return_value=[])
    store.get_model = REGISTRY.get
    return plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())


# ── the pure check ────────────────────────────────────────────────────────────


def test_identity_loras_beyond_the_loader_count_are_reported() -> None:
    spec = _spec("narrator-zimage.safetensors", ID_LORA)
    assert dropped_identity_loras(spec, ["lora_1", "lora_1_strength"], _is_identity) == [ID_LORA]


def test_non_identity_loras_that_do_not_fit_are_not_reported() -> None:
    assert dropped_identity_loras(_spec(STYLE_LORA), ["lora_0", "lora_0_strength"], _is_identity) == []


def test_other_unmapped_values_are_ignored_and_names_are_not_repeated() -> None:
    spec = _spec(ID_LORA)
    assert dropped_identity_loras(spec, ["negative", "model", "steps"], _is_identity) == []
    assert dropped_identity_loras(spec, ["lora_0", "lora_0_strength"], _is_identity) == [ID_LORA]


def test_an_unmapped_index_outside_the_stack_is_ignored() -> None:
    assert dropped_identity_loras(_spec(ID_LORA), ["lora_5"], _is_identity) == []


# ── the plan ──────────────────────────────────────────────────────────────────


def test_a_spec_whose_identity_lora_has_no_loader_is_skipped_with_the_reason(tmp_path: Path, flux_template) -> None:
    plan = _plan(tmp_path, flux_template, _spec(ID_LORA))              # the Flux fixture has no LoRA loader
    assert plan.plans == [] and len(plan.skipped) == 1
    reason = plan.skip_reasons[plan.skipped[0]]
    assert ID_LORA in reason and "identity" in reason and "loader" in reason


def test_the_same_spec_with_a_non_identity_lora_still_renders_with_a_warning(tmp_path: Path, flux_template) -> None:
    plan = _plan(tmp_path, flux_template, _spec(STYLE_LORA))
    assert len(plan.plans) == 1 and "lora_0" in plan.plans[0].unmapped and plan.skipped == []


def test_an_identity_lora_that_fits_the_template_is_planned(tmp_path: Path, zimage_lora_template) -> None:
    plan = _plan(tmp_path, zimage_lora_template,
                 _spec("narrator-zimage.safetensors", workflow_ref="t", model=None))
    assert len(plan.plans) == 1 and plan.skipped == []


def test_a_second_identity_lora_with_no_second_loader_stops_the_render(tmp_path: Path, zimage_lora_template) -> None:
    plan = _plan(tmp_path, zimage_lora_template, _spec("narrator-zimage.safetensors", ID_LORA, model=None))
    assert plan.plans == [] and ID_LORA in plan.skip_reasons[plan.skipped[0]]


def test_quick_refuses_a_dropped_identity_lora(flux_template) -> None:
    from visual_generation.quick import QuickLoraUnsafe, quick_generate_sync

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.get_model = REGISTRY.get
    client = MagicMock()
    with pytest.raises(QuickLoraUnsafe, match=ID_LORA):
        quick_generate_sync("a mug", endpoint="x", template_name="flux-txt2img", seed=1, store=store, client=client,
                            lora_stack=[LoraRef(name=ID_LORA, strength=1.0)])
    client.submit.assert_not_called()


def test_the_graph_builder_itself_is_unchanged(flux_template) -> None:
    """The refusal lives in the plan, not in build_prompt_graph (its contract stays advisory)."""
    graph, unmapped = build_prompt_graph(_spec(ID_LORA), flux_template)
    assert "lora_0" in unmapped and isinstance(graph, dict)
