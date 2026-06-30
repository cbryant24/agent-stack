from __future__ import annotations

from visual_generation.graph_build import (
    apply_source_filenames,
    build_prompt_graph,
    write_slot,
)
from visual_generation.models import LoraRef, VisualSpec


def test_flux_values_land_at_the_right_node_inputs(flux_template) -> None:
    spec = VisualSpec(
        prompt="a wolf in neon rain",
        model="flux1-dev.safetensors",
        seed=99,
        width=768,
        height=1024,
        settings={"steps": 24, "cfg": 1.0, "sampler": "euler", "scheduler": "simple", "flux_guidance": 3.2},
        workflow_ref="flux-txt2img",
    )
    graph, unmapped = build_prompt_graph(spec, flux_template)

    # Positive prompt written into the CLIPTextEncode (node 6) the FluxGuidance feeds.
    assert graph["6"]["inputs"]["text"] == "a wolf in neon rain"
    # Sampler-bound values on node 3.
    assert graph["3"]["inputs"]["seed"] == 99
    assert graph["3"]["inputs"]["steps"] == 24
    assert graph["3"]["inputs"]["sampler_name"] == "euler"
    # Flux guidance on node 13.
    assert graph["13"]["inputs"]["guidance"] == 3.2
    # Dimensions on the latent node 5.
    assert graph["5"]["inputs"]["width"] == 768
    assert graph["5"]["inputs"]["height"] == 1024
    # Model into the UNET loader (node 10).
    assert graph["10"]["inputs"]["unet_name"] == "flux1-dev.safetensors"


def test_negative_on_flux_is_unmapped_not_forced(flux_template) -> None:
    spec = VisualSpec(prompt="x", negative_prompt="blurry, lowres", workflow_ref="flux-txt2img")
    graph, unmapped = build_prompt_graph(spec, flux_template)
    # Flux template has no negative slot → the value is reported, never written.
    assert "negative" in unmapped
    # The empty-text placeholder node 7 is untouched.
    assert graph["7"]["inputs"]["text"] == ""


def test_build_does_not_mutate_the_template(flux_template) -> None:
    original_seed = flux_template.graph["3"]["inputs"]["seed"]
    spec = VisualSpec(prompt="x", seed=12345, workflow_ref="flux-txt2img")
    build_prompt_graph(spec, flux_template)
    # The template's own graph is unchanged (deep-copied).
    assert flux_template.graph["3"]["inputs"]["seed"] == original_seed


def test_extra_lora_beyond_slots_is_unmapped(flux_template) -> None:
    # The Flux fixture has no LoRA loader → any lora is advisory-unmapped.
    spec = VisualSpec(
        prompt="x", lora_stack=[LoraRef(name="char.safetensors", strength=0.7)], workflow_ref="flux-txt2img"
    )
    _graph, unmapped = build_prompt_graph(spec, flux_template)
    assert "lora_0" in unmapped


def test_lora_name_and_strength_land_in_a_lora_template() -> None:
    # A Z-Image-style txt2img graph with a LoraLoaderModelOnly between the UNET
    # loader and the sampler — the shape visual-workflow-lora is built from.
    from visual_generation.models import WorkflowTemplate
    from visual_generation.slot_inference import infer_slots

    graph = {
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image.safetensors"}},
        "11": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["10", 0], "lora_name": "placeholder.safetensors", "strength_model": 1.0}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["13", 0]}},
        "13": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors"}},
        "14": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["12", 0]}},
        "15": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 1, "steps": 8, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple",
            "denoise": 1.0, "model": ["11", 0], "positive": ["12", 0], "negative": ["14", 0],
            "latent_image": ["15", 0]}},
    }
    inferred = infer_slots(graph)
    # Both the name and the model-side strength get their own slots.
    assert inferred.slot_map["lora_0"] == {"node_id": "11", "input_key": "lora_name"}
    assert inferred.slot_map["lora_0_strength"] == {"node_id": "11", "input_key": "strength_model"}

    template = WorkflowTemplate(
        name="z-lora", descriptor="x", graph=graph,
        slot_map=inferred.slot_map, required_models=inferred.required_models,
    )
    spec = VisualSpec(
        prompt="a felt puppet",
        lora_stack=[LoraRef(name="narrator-zimage.safetensors", strength=0.9)],
        workflow_ref="z-lora",
    )
    out, unmapped = build_prompt_graph(spec, template)
    # The canon-pinned name AND its 0.9 strength both reach the loader node.
    assert out["11"]["inputs"]["lora_name"] == "narrator-zimage.safetensors"
    assert out["11"]["inputs"]["strength_model"] == 0.9
    assert "lora_0" not in unmapped
    assert "lora_0_strength" not in unmapped


# ── source filenames (img2img / inpaint init_image + mask) ───────────────────


def _img2img_graph_and_map() -> tuple[dict, dict]:
    """A minimal img2img graph + slot_map with init_image and mask slots."""
    graph = {
        "10": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "12": {"class_type": "LoadImageMask", "inputs": {"image": "", "channel": "red"}},
        "3": {"class_type": "KSampler", "inputs": {"latent_image": ["11", 0]}},
    }
    slot_map = {
        "init_image": {"node_id": "10", "input_key": "image"},
        "mask": {"node_id": "12", "input_key": "image"},
    }
    return graph, slot_map


def test_apply_source_filenames_writes_init_and_mask() -> None:
    graph, slot_map = _img2img_graph_and_map()
    unmapped = apply_source_filenames(
        graph, slot_map, init_image="spec1_init.png", mask="spec1_mask_m.png"
    )
    assert unmapped == []
    assert graph["10"]["inputs"]["image"] == "spec1_init.png"
    assert graph["12"]["inputs"]["image"] == "spec1_mask_m.png"


def test_apply_source_filenames_reports_missing_init_slot() -> None:
    # A txt2img template (no init_image slot) → init_image is advisory-unmapped.
    graph = {"10": {"class_type": "LoadImage", "inputs": {"image": ""}}}
    unmapped = apply_source_filenames(graph, {}, init_image="x.png")
    assert unmapped == ["init_image"]


def test_apply_source_filenames_reports_missing_mask_slot() -> None:
    graph, slot_map = _img2img_graph_and_map()
    slot_map.pop("mask")
    unmapped = apply_source_filenames(graph, slot_map, init_image="i.png", mask="m.png")
    assert unmapped == ["mask"]
    # init_image still landed.
    assert graph["10"]["inputs"]["image"] == "i.png"


def test_write_slot_returns_false_for_unknown_slot() -> None:
    graph = {"3": {"class_type": "KSampler", "inputs": {}}}
    assert write_slot(graph, {}, "denoise", 0.5) is False
    assert write_slot(graph, {"denoise": {"node_id": "3", "input_key": "denoise"}}, "denoise", 0.5) is True
    assert graph["3"]["inputs"]["denoise"] == 0.5


def test_sourceless_build_unaffected(flux_template) -> None:
    # A spec with no source builds exactly as before — no init_image/mask written.
    spec = VisualSpec(prompt="a wolf", seed=5, workflow_ref="flux-txt2img")
    graph, _unmapped = build_prompt_graph(spec, flux_template)
    for node in graph.values():
        assert "init_image" not in node.get("inputs", {})
