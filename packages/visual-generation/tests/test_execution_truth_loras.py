"""Entry-gate item 3: a LoRA baked into the template must not apply when the spec asks for none."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from visual_generation.batch_file import write_batch
from visual_generation.generate import plan_generation_sync
from visual_generation.graph_build import build_prompt_graph, neutralize_unused_loras
from visual_generation.models import GenerationBatch, LoraRef, VisualSpec, WorkflowTemplate

BAKED = "narrator-zimage.safetensors"


def _loader(template: WorkflowTemplate, i: int = 0) -> dict:
    node = template.graph[template.slot_map[f"lora_{i}"]["node_id"]]
    return node["inputs"]


def _strength_target(template: WorkflowTemplate, i: int = 0) -> tuple[str, str]:
    t = template.slot_map[f"lora_{i}_strength"]
    return t["node_id"], t["input_key"]


def _spec(**kw) -> VisualSpec:
    base = dict(prompt="a plain red mug on a white table", seed=7, width=1024, height=1024,
                settings={"steps": 8, "cfg": 1.0}, workflow_ref="z-image-turbo-lora", project="proj")
    base.update(kw)
    return VisualSpec(**base)


def _plan(tmp_path: Path, template: WorkflowTemplate, spec: VisualSpec):
    path = tmp_path / "b.batch.md"
    write_batch(GenerationBatch(project="proj", specs=[spec]), path)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    store.recent_generation_costs = AsyncMock(return_value=[])
    store.get_model = lambda name: None
    return plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())


def test_the_real_template_really_bakes_a_lora(zimage_lora_template) -> None:
    """Guards the premise: if the workflow stops baking one, this test says so."""
    assert _loader(zimage_lora_template)["lora_name"] == BAKED
    assert _loader(zimage_lora_template)["strength_model"] == 1.0


def test_an_unused_baked_loader_is_set_to_zero_strength(zimage_lora_template) -> None:
    t = zimage_lora_template
    graph, _ = build_prompt_graph(_spec(), t)              # empty lora stack: nothing is written
    assert graph[_strength_target(t)[0]]["inputs"][_strength_target(t)[1]] == 1.0   # the bug: still 1.0

    neutralized, stuck = neutralize_unused_loras(graph, t.slot_map, used_count=0)

    node_id, key = _strength_target(t)
    assert graph[node_id]["inputs"][key] == 0.0
    assert neutralized == [BAKED] and stuck == []


def test_loaders_the_spec_uses_are_left_alone(zimage_lora_template) -> None:
    t = zimage_lora_template
    graph, _ = build_prompt_graph(_spec(lora_stack=[LoraRef(name=BAKED, strength=0.8)]), t)
    neutralized, stuck = neutralize_unused_loras(graph, t.slot_map, used_count=1)
    node_id, key = _strength_target(t)
    assert graph[node_id]["inputs"][key] == 0.8 and neutralized == [] and stuck == []


def test_a_loader_with_no_strength_slot_cannot_be_turned_off(zimage_lora_template) -> None:
    t = zimage_lora_template
    slot_map = {k: v for k, v in t.slot_map.items() if k != "lora_0_strength"}
    graph, _ = build_prompt_graph(_spec(), WorkflowTemplate(
        name=t.name, descriptor=t.descriptor, graph=t.graph, slot_map=slot_map))
    neutralized, stuck = neutralize_unused_loras(graph, slot_map, used_count=0)
    assert neutralized == [] and stuck == [BAKED]


def test_an_empty_loader_name_needs_no_neutralizing(zimage_lora_template) -> None:
    t = zimage_lora_template
    graph, _ = build_prompt_graph(_spec(), t)
    graph[t.slot_map["lora_0"]["node_id"]]["inputs"]["lora_name"] = ""
    assert neutralize_unused_loras(graph, t.slot_map, used_count=0) == ([], [])


def test_the_plan_neutralizes_the_baked_lora_and_says_so(tmp_path: Path, zimage_lora_template) -> None:
    t = zimage_lora_template
    plan = _plan(tmp_path, t, _spec())
    (sp,) = plan.plans
    node_id, key = _strength_target(t)
    assert sp.graph[node_id]["inputs"][key] == 0.0
    assert sp.neutralized_loras == [BAKED]
    assert plan.skipped == []
    # the template itself is never mutated
    assert t.graph[node_id]["inputs"][key] == 1.0


def test_the_plan_leaves_a_requested_lora_at_its_strength(tmp_path: Path, zimage_lora_template) -> None:
    t = zimage_lora_template
    plan = _plan(tmp_path, t, _spec(lora_stack=[LoraRef(name=BAKED, strength=0.9)]))
    (sp,) = plan.plans
    node_id, key = _strength_target(t)
    assert sp.graph[node_id]["inputs"][key] == 0.9 and sp.neutralized_loras == []


def test_a_spec_that_cannot_switch_off_a_baked_lora_is_skipped_with_the_reason(tmp_path: Path, zimage_lora_template) -> None:
    t = zimage_lora_template
    stuck = WorkflowTemplate(name=t.name, descriptor=t.descriptor, graph=t.graph,
                             slot_map={k: v for k, v in t.slot_map.items() if k != "lora_0_strength"})
    plan = _plan(tmp_path, stuck, _spec())
    assert plan.plans == [] and len(plan.skipped) == 1
    reason = plan.skip_reasons[plan.skipped[0]]
    assert BAKED in reason and "strength" in reason


def test_quick_neutralizes_the_baked_lora_too(zimage_lora_template) -> None:
    from visual_generation.comfyui_client import ComfyUIClient
    from visual_generation.quick import quick_generate_sync

    class Fake:
        def __init__(self) -> None:
            self.submitted: list[dict] = []

        async def submit(self, graph, client_id=None):
            self.submitted.append(graph)
            return "pid"

        async def history(self, pid):
            return {"outputs": {"9": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}

        async def view(self, filename, subfolder="", type="output"):
            return b"\x89PNGdata"

        images_from_history = staticmethod(ComfyUIClient.images_from_history)

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=zimage_lora_template)
    fake = Fake()
    quick_generate_sync("a plain red mug", endpoint="x", template_name="z-image-turbo-lora", seed=3,
                        store=store, client=fake)
    t = zimage_lora_template
    node_id, key = _strength_target(t)
    assert fake.submitted[0][node_id]["inputs"][key] == 0.0



def test_a_loraloader_with_a_clip_strength_is_switched_off_on_both_sides() -> None:
    graph = {"5": {"class_type": "LoraLoader", "inputs": {
        "lora_name": "style.safetensors", "strength_model": 1.0, "strength_clip": 0.8}}}
    slot_map = {"lora_0": {"node_id": "5", "input_key": "lora_name"},
                "lora_0_strength": {"node_id": "5", "input_key": "strength_model"}}
    assert neutralize_unused_loras(graph, slot_map, 0) == (["style.safetensors"], [])
    assert graph["5"]["inputs"]["strength_model"] == 0.0 and graph["5"]["inputs"]["strength_clip"] == 0.0


def test_quick_refuses_a_baked_lora_it_cannot_switch_off(zimage_lora_template) -> None:
    import pytest

    from visual_generation.quick import QuickLoraUnsafe, quick_generate_sync

    t = zimage_lora_template
    stuck = WorkflowTemplate(name=t.name, descriptor=t.descriptor, graph=t.graph,
                             slot_map={k: v for k, v in t.slot_map.items() if k != "lora_0_strength"})
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=stuck)
    fake = MagicMock()
    with pytest.raises(QuickLoraUnsafe, match="narrator-zimage"):
        quick_generate_sync("a mug", endpoint="x", template_name="z-image-turbo-lora", seed=3, store=store, client=fake)
    fake.submit.assert_not_called()
