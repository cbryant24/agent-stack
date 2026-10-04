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


# ── WAN 2.2 MoE two-stage video graphs (real exported API files) ─────────────


def test_wan_t2v_seed_resolves_to_the_add_noise_enable_sampler(wan_t2v_graph: dict) -> None:
    # Node "78" (low-noise finisher, add_noise: disable) appears before node "81"
    # (high-noise initial pass, add_noise: enable) in the file's key order — a naive
    # "first sampler found" pick would target 78's inert noise_seed. The real seed
    # lives on 81 (research-signals handoff: `81.noise_seed`).
    sm = infer_slots(wan_t2v_graph).slot_map
    assert sm["seed"] == {"node_id": "81", "input_key": "noise_seed"}


def test_wan_t2v_prompts_resolve_despite_two_samplers(wan_t2v_graph: dict) -> None:
    sm = infer_slots(wan_t2v_graph).slot_map
    assert sm["positive"] == {"node_id": "89", "input_key": "text"}
    assert sm["negative"] == {"node_id": "72", "input_key": "text"}


def test_wan_t2v_dims_and_fps_resolve_through_the_sampler_chain(wan_t2v_graph: dict) -> None:
    # Node 78's latent_image points at node 81's OUTPUT, not the empty-latent node
    # directly — dimension tracing must follow that hop to reach node "74"
    # (EmptyHunyuanLatentVideo) for width/height/length; fps lives on CreateVideo "88",
    # which is unreachable from the sampler trace at all (a standalone scan).
    sm = infer_slots(wan_t2v_graph).slot_map
    assert sm["width"] == {"node_id": "74", "input_key": "width"}
    assert sm["height"] == {"node_id": "74", "input_key": "height"}
    assert sm["length"] == {"node_id": "74", "input_key": "length"}
    assert sm["fps"] == {"node_id": "88", "input_key": "fps"}


def test_wan_t2v_has_no_init_image_slot(wan_t2v_graph: dict) -> None:
    # T2V is txt2img-shaped once chain-followed to EmptyHunyuanLatentVideo — no seed frame.
    sm = infer_slots(wan_t2v_graph).slot_map
    assert "init_image" not in sm


def test_wan_i2v_seed_resolves_correctly(wan_i2v_graph: dict) -> None:
    # I2V's add_noise:enable sampler ("129:86") happens to be first in file order —
    # confirm the fix doesn't disturb the already-correct case.
    sm = infer_slots(wan_i2v_graph).slot_map
    assert sm["seed"] == {"node_id": "129:86", "input_key": "noise_seed"}


def test_wan_i2v_init_image_resolves_through_wan_image_to_video(wan_i2v_graph: dict) -> None:
    # latent_image -> WanImageToVideo("129:98").start_image -> LoadImage("97").
    sm = infer_slots(wan_i2v_graph).slot_map
    assert sm["init_image"] == {"node_id": "97", "input_key": "image"}


def test_wan_i2v_dims_and_fps_resolve_off_wan_image_to_video(wan_i2v_graph: dict) -> None:
    sm = infer_slots(wan_i2v_graph).slot_map
    assert sm["width"] == {"node_id": "129:98", "input_key": "width"}
    assert sm["height"] == {"node_id": "129:98", "input_key": "height"}
    assert sm["length"] == {"node_id": "129:98", "input_key": "length"}
    assert sm["fps"] == {"node_id": "129:94", "input_key": "fps"}


def test_wan_i2v_steps_cfg_are_switch_wired_so_not_inferred(wan_i2v_graph: dict) -> None:
    # I2V routes steps/cfg/boundary through ComfySwitchNodes (the 4-step vs 20-step
    # toggle) — they're links, not literals, on the sampler, so recipe-locked `quick`
    # correctly gets nothing to (mis)write here; the graph's baked toggle state rules.
    sm = infer_slots(wan_i2v_graph).slot_map
    assert "steps" not in sm
    assert "cfg" not in sm
