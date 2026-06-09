from __future__ import annotations

from visual_generation.graph_build import build_prompt_graph
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
