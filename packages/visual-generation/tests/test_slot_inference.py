from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_generation.draft import _template_modality
from visual_generation.models import WorkflowTemplate
from visual_generation.slot_inference import infer_slots

_WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"
_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _template_from(graph: dict) -> WorkflowTemplate:
    inferred = infer_slots(graph)
    return WorkflowTemplate(name="t", descriptor="d", graph=graph, slot_map=inferred.slot_map)


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
    # The model-side strength gets its own slot so canon `name:strength` applies.
    assert sm["lora_0_strength"] == {"node_id": "10", "input_key": "strength_model"}
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


# ── img2img / inpaint (image-input topologies) ───────────────────────────────


def _img2img_graph() -> dict:
    """KSampler.latent_image ← VAEEncode(pixels ← LoadImage) — the img2img shape."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "z-image-turbo.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "init.png"}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 1, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal",
            "denoise": 0.5, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["11", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
    }


def test_img2img_infers_init_image_slot() -> None:
    sm = infer_slots(_img2img_graph()).slot_map
    assert sm["init_image"] == {"node_id": "10", "input_key": "image"}
    assert "mask" not in sm
    # Prompts still resolve by wiring; denoise is sampler-bound as usual.
    assert sm["positive"] == {"node_id": "6", "input_key": "text"}
    assert sm["denoise"] == {"node_id": "3", "input_key": "denoise"}
    # No empty-latent → no width/height (img2img inherits the init image's size).
    assert "width" not in sm and "height" not in sm


def test_inpaint_vae_encode_for_inpaint_infers_init_and_mask() -> None:
    graph = _img2img_graph()
    graph["12"] = {"class_type": "LoadImageMask", "inputs": {"image": "mask.png", "channel": "red"}}
    graph["11"] = {"class_type": "VAEEncodeForInpaint", "inputs": {
        "pixels": ["10", 0], "vae": ["4", 2], "mask": ["12", 0], "grow_mask_by": 6}}
    sm = infer_slots(graph).slot_map
    assert sm["init_image"] == {"node_id": "10", "input_key": "image"}
    assert sm["mask"] == {"node_id": "12", "input_key": "image"}


def test_inpaint_set_latent_noise_mask_infers_init_and_mask() -> None:
    graph = _img2img_graph()
    graph["12"] = {"class_type": "LoadImageMask", "inputs": {"image": "mask.png"}}
    graph["13"] = {"class_type": "SetLatentNoiseMask", "inputs": {
        "samples": ["11", 0], "mask": ["12", 0]}}
    graph["3"]["inputs"]["latent_image"] = ["13", 0]
    sm = infer_slots(graph).slot_map
    assert sm["init_image"] == {"node_id": "10", "input_key": "image"}
    assert sm["mask"] == {"node_id": "12", "input_key": "image"}


def test_ambiguous_pixels_source_is_noted_not_guessed() -> None:
    # The VAEEncode's pixels come from another node, not a LoadImage → no slot, a note.
    graph = _img2img_graph()
    graph["11"]["inputs"]["pixels"] = ["8", 0]  # from the VAEDecode, not LoadImage
    inferred = infer_slots(graph)
    assert "init_image" not in inferred.slot_map
    assert any("init_image" in n for n in inferred.notes)


def test_txt2img_graph_has_no_image_slots(flux_graph: dict) -> None:
    # Regression: an empty-latent (txt2img) graph proposes no init_image/mask.
    sm = infer_slots(flux_graph).slot_map
    assert "init_image" not in sm
    assert "mask" not in sm


# ── Wan 2.2 I2V (committed graph): dual-sampler seed + video conditioning ─────


def _i2v_graph() -> dict:
    return json.loads((_WORKFLOWS_DIR / "wan2.2-i2v-14B-lightx2v-api.json").read_text())


def test_i2v_seed_is_the_noise_adding_sampler() -> None:
    # Dual high/low-noise samplers: 129:86 adds noise (seed carrier), 129:85 doesn't.
    inferred = infer_slots(_i2v_graph())
    assert inferred.slot_map["seed"] == {"node_id": "129:86", "input_key": "noise_seed"}


def test_i2v_positive_negative_trace_through_wan_node() -> None:
    # The sampler's positive/negative point at WanImageToVideo outputs 0/1, not directly
    # at a CLIPTextEncode — the trace must walk THROUGH the Wan node.
    sm = infer_slots(_i2v_graph()).slot_map
    assert sm["positive"] == {"node_id": "129:93", "input_key": "text"}
    assert sm["negative"] == {"node_id": "129:89", "input_key": "text"}


def test_i2v_frame_length_fps_slots() -> None:
    sm = infer_slots(_i2v_graph()).slot_map
    assert sm["first_frame"] == {"node_id": "97", "input_key": "image"}
    assert "last_frame" not in sm  # single-image I2V
    assert sm["length"] == {"node_id": "129:98", "input_key": "length"}
    assert sm["fps"] == {"node_id": "129:94", "input_key": "fps"}
    assert sm["width"] == {"node_id": "129:98", "input_key": "width"}
    assert sm["height"] == {"node_id": "129:98", "input_key": "height"}


def test_i2v_switch_fed_steps_cfg_unmapped_and_noted() -> None:
    inferred = infer_slots(_i2v_graph())
    # steps/cfg are links to ComfySwitchNode → NOT slot-mapped (no switch resolver).
    assert "steps" not in inferred.slot_map
    assert "cfg" not in inferred.slot_map
    # Literal sampler_name/scheduler on the sampler ARE mapped.
    assert inferred.slot_map["sampler"] == {"node_id": "129:86", "input_key": "sampler_name"}
    assert any("ComfySwitchNode" in n or "not slot-mapped" in n for n in inferred.notes)


def test_i2v_modality_is_i2v() -> None:
    assert _template_modality(_template_from(_i2v_graph())) == "i2v"


# ── Wan 2.2 FLF2V (inline synthetic — logic test until Phase-0 export lands) ──


def _flf2v_graph() -> dict:
    # Mirrors the I2V topology but with WanFirstLastFrameToVideo + a second frame.
    # Input key names (end_image, etc.) are TODO(phase0)-verified against the export.
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "first.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "last.png"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "walks in", "clip": ["4", 0]}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5.safetensors", "type": "wan"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 0]}},
        "6": {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "width": 832, "height": 480, "length": 81,
            "positive": ["3", 0], "negative": ["5", 0], "vae": ["7", 0],
            "start_image": ["1", 0], "end_image": ["2", 0]}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "8": {"class_type": "KSamplerAdvanced", "inputs": {
            "add_noise": "enable", "noise_seed": 42, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "model": ["9", 0], "positive": ["6", 0], "negative": ["6", 1],
            "latent_image": ["6", 2]}},
        "9": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_high.safetensors"}},
        "10": {"class_type": "CreateVideo", "inputs": {"fps": 16, "images": ["11", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["7", 0]}},
        "12": {"class_type": "SaveVideo", "inputs": {"video": ["10", 0]}},
    }


def test_flf2v_infers_both_frames() -> None:
    sm = infer_slots(_flf2v_graph()).slot_map
    assert sm["first_frame"] == {"node_id": "1", "input_key": "image"}
    assert sm["last_frame"] == {"node_id": "2", "input_key": "image"}
    assert sm["length"] == {"node_id": "6", "input_key": "length"}
    assert sm["fps"] == {"node_id": "10", "input_key": "fps"}


def test_flf2v_positive_negative_trace_through_wan_node() -> None:
    sm = infer_slots(_flf2v_graph()).slot_map
    assert sm["positive"] == {"node_id": "3", "input_key": "text"}
    assert sm["negative"] == {"node_id": "5", "input_key": "text"}


def test_flf2v_modality() -> None:
    assert _template_modality(_template_from(_flf2v_graph())) == "flf2v"


# ── Qwen-Image-Edit 2511 (inline synthetic — logic test) ─────────────────────


def _qwen_edit_graph() -> dict:
    # TextEncodeQwenImageEditPlus prompt key + ordered image inputs are
    # TODO(phase0)-verified against the export.
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "base.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
        "3": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "prompt": "same shot, Celeste reaches for the door", "clip": ["4", 0],
            "vae": ["5", 0], "image1": ["1", 0], "image2": ["2", 0]}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b.safetensors"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "6": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "prompt": "", "clip": ["4", 0], "vae": ["5", 0], "image1": ["1", 0]}},
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "seed": 7, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0, "model": ["9", 0], "positive": ["3", 0], "negative": ["6", 0],
            "latent_image": ["7", 0]}},
        "9": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2511.safetensors"}},
    }


def test_qwen_edit_positive_uses_prompt_key() -> None:
    # The Qwen edit-encode's text lives under "prompt", not "text".
    sm = infer_slots(_qwen_edit_graph()).slot_map
    assert sm["positive"] == {"node_id": "3", "input_key": "prompt"}


def test_qwen_edit_infers_ordered_edit_images() -> None:
    sm = infer_slots(_qwen_edit_graph()).slot_map
    assert sm["edit_image_1"] == {"node_id": "1", "input_key": "image"}
    assert sm["edit_image_2"] == {"node_id": "2", "input_key": "image"}


def test_qwen_edit_modality() -> None:
    assert _template_modality(_template_from(_qwen_edit_graph())) == "edit"


# ── Phase-0 real exports (fixture-gated; skip until the API JSONs are committed) ──

_FLF2V_FIXTURE = _FIXTURES_DIR / "wan2.2-flf2v-14B-lightx2v-api.json"
_QWEN_FIXTURE = _FIXTURES_DIR / "qwen-image-edit-2511-api.json"


@pytest.mark.skipif(
    not _FLF2V_FIXTURE.exists(), reason="Phase-0 FLF2V API JSON not yet exported/committed"
)
def test_real_flf2v_export_infers_frames() -> None:
    sm = infer_slots(json.loads(_FLF2V_FIXTURE.read_text())).slot_map
    assert "first_frame" in sm and "last_frame" in sm
    assert "length" in sm and "fps" in sm
    assert _template_modality(WorkflowTemplate(
        name="flf2v", descriptor="d", graph={}, slot_map=sm)) == "flf2v"


@pytest.mark.skipif(
    not _QWEN_FIXTURE.exists(), reason="Phase-0 Qwen-edit API JSON not yet exported/committed"
)
def test_real_qwen_edit_export_infers_edit_images() -> None:
    sm = infer_slots(json.loads(_QWEN_FIXTURE.read_text())).slot_map
    assert "edit_image_1" in sm
    assert _template_modality(WorkflowTemplate(
        name="edit", descriptor="d", graph={}, slot_map=sm)) == "edit"
