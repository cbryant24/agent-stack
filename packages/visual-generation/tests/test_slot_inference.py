from __future__ import annotations

from visual_generation.slot_inference import infer_slots


# ── Flux txt2img (the fixture) ───────────────────────────────────────────────


def test_flux_slot_map_is_correct(flux_graph: dict) -> None:
    inferred = infer_slots(flux_graph)
    sm = inferred.slot_map

    # Sampler-bound slots, resolved off the KSampler node (id "3").
    assert sm["seed"] == {"node_id": "3", "input_key": "seed"}
    assert sm["steps"] == {"node_id": "3", "input_key": "steps"}
    assert sm["cfg"] == {"node_id": "3", "input_key": "cfg"}
    assert sm["sampler"] == {"node_id": "3", "input_key": "sampler_name"}
    assert sm["scheduler"] == {"node_id": "3", "input_key": "scheduler"}

    # Positive resolved by tracing KSampler.positive → FluxGuidance → CLIPTextEncode "6".
    assert sm["positive"] == {"node_id": "6", "input_key": "text"}

    # Flux guidance slot captured off the FluxGuidance node "13".
    assert sm["flux_guidance"] == {"node_id": "13", "input_key": "guidance"}

    # Dimensions from the EmptySD3LatentImage node "5".
    assert sm["width"] == {"node_id": "5", "input_key": "width"}
    assert sm["height"] == {"node_id": "5", "input_key": "height"}

    # UNET loader.
    assert sm["unet"] == {"node_id": "10", "input_key": "unet_name"}


def test_flux_has_no_negative_slot(flux_graph: dict) -> None:
    inferred = infer_slots(flux_graph)
    assert "negative" not in inferred.slot_map
    assert inferred.negative_suppressed is True
    assert inferred.negative_reason == "flux"
    # We still know the empty-text node, offered as the override target.
    assert inferred.negative_candidate == {"node_id": "7", "input_key": "text"}


def test_flux_required_models_extracted(flux_graph: dict) -> None:
    inferred = infer_slots(flux_graph)
    assert inferred.required_models == [
        "flux1-dev.safetensors",
        "ae.safetensors",
        "t5xxl_fp16.safetensors",
        "clip_l.safetensors",
    ]


# ── SDXL-style graph (real negative + CheckpointLoaderSimple + LoRA) ─────────


def _sdxl_graph() -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl_base.safetensors"}},
        "10": {"class_type": "LoraLoader", "inputs": {
            "lora_name": "detail.safetensors", "strength_model": 0.8, "strength_clip": 0.8,
            "model": ["4", 0], "clip": ["4", 1]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a knight", "clip": ["10", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, lowres", "clip": ["10", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 7, "steps": 30, "cfg": 7.5, "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": 1.0, "model": ["10", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
    }


def test_sdxl_resolves_positive_and_negative_by_tracing() -> None:
    inferred = infer_slots(_sdxl_graph())
    sm = inferred.slot_map
    # Positive vs negative resolved by which KSampler input they feed — NOT node order.
    assert sm["positive"] == {"node_id": "6", "input_key": "text"}
    assert sm["negative"] == {"node_id": "7", "input_key": "text"}
    assert inferred.negative_suppressed is False
    # Real CFG meaningful, checkpoint + lora slots present.
    assert sm["cfg"] == {"node_id": "3", "input_key": "cfg"}
    assert sm["checkpoint"] == {"node_id": "4", "input_key": "ckpt_name"}
    assert sm["lora_0"] == {"node_id": "10", "input_key": "lora_name"}
    # No flux_guidance on an SDXL graph.
    assert "flux_guidance" not in sm


def test_negative_polarity_not_decided_by_node_order() -> None:
    # Swap which node feeds KSampler.negative; the slot must follow the wiring.
    graph = _sdxl_graph()
    graph["3"]["inputs"]["positive"] = ["7", 0]
    graph["3"]["inputs"]["negative"] = ["6", 0]
    sm = infer_slots(graph).slot_map
    assert sm["positive"] == {"node_id": "7", "input_key": "text"}
    assert sm["negative"] == {"node_id": "6", "input_key": "text"}


def test_no_sampler_yields_note_not_crash() -> None:
    inferred = infer_slots({"9": {"class_type": "SaveImage", "inputs": {}}})
    assert "seed" not in inferred.slot_map
    assert any("sampler" in n.lower() for n in inferred.notes)
