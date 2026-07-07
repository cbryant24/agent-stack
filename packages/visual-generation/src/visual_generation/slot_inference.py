"""Infer a WorkflowTemplate slot map from an exported API-format ComfyUI graph.

The slot map is `semantic param → {node_id, input_key}` — the swap-points the
agent writes values into. Inference is **per-graph and wiring-derived**, never
hardcoded per model: Flux vs. SDXL fall out of the graph's topology (a
FluxGuidance node, how the sampler's negative input is wired), not a model name.

The central move is to resolve positive/negative prompts by **tracing the
sampler's `positive`/`negative` conditioning inputs** — they are otherwise
indistinguishable (two CLIPTextEncode nodes look identical; order and labels
don't bind them to a polarity).

Ambiguous spots (an empty-text negative, multiple LoRAs, an unrecognized sampler
topology) are reported, not guessed — the `workflow register` propose→confirm
loop is where the user resolves them once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SAMPLER_CLASSES = {"KSampler", "KSamplerAdvanced"}
_LATENT_CLASSES = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyLatentImageAdvanced"}

# ── Video / edit topology (Wan 2.2 FLF2V / I2V, Qwen-Image-Edit 2511) ─────────
# The Wan video-latent nodes emit conditioning on outputs 0/1 and a latent on 2, so
# the sampler's positive/negative trace THROUGH them (see _resolve_cond). Class names +
# input keys below are confirmed against ComfyUI master (comfy_extras/nodes_wan.py,
# nodes_qwen.py): WanImageToVideo has one image input `start_image`; WanFirstLastFrameToVideo
# adds `end_image`; both output (positive, negative, latent). Still diff a committed
# Phase-0 export before production in case the pinned pod's ComfyUI version differs.
_VIDEO_LATENT_CLASSES = {
    "WanImageToVideo",
    "WanFirstLastFrameToVideo",
    "WanFirstLastFrameToVideoLatent",  # 5B variant name (defensive; not in master extras)
}
_EDIT_ENCODE_CLASSES = {"TextEncodeQwenImageEditPlus", "TextEncodeQwenImageEditPlusAdvance"}
_CREATE_VIDEO_CLASSES = {"CreateVideo"}

# Per-encoder input key holding the prompt text. Confirmed against source: CLIPTextEncode
# uses "text"; TextEncodeQwenImageEditPlus uses "prompt" (with image ports image1/image2/image3).
_TEXT_INPUT_KEYS = {
    "CLIPTextEncode": "text",
    "TextEncodeQwenImageEditPlus": "prompt",
    "TextEncodeQwenImageEditPlusAdvance": "prompt",
}


def _text_key(node: dict[str, Any] | None) -> str:
    """The input key holding a text encoder's prompt string (class-dependent)."""
    if node is None:
        return "text"
    return _TEXT_INPUT_KEYS.get(node.get("class_type", ""), "text")

# Image-input (img2img / inpaint) topology. The sampler's `latent_image` traces back
# through a VAE-encode of an uploaded image instead of an empty latent.
_VAE_ENCODE_CLASSES = {"VAEEncode", "VAEEncodeForInpaint"}
_INPAINT_LATENT_CLASSES = {"SetLatentNoiseMask"}  # wraps an encoded latent + a mask
_IMAGE_LOAD_CLASSES = {"LoadImage"}
_MASK_LOAD_CLASSES = {"LoadImageMask", "LoadImage"}

# Sampler-bound slots: semantic name → the sampler input_key holding the literal.
# `seed` differs between KSampler ("seed") and KSamplerAdvanced ("noise_seed").
_SAMPLER_SCALAR_SLOTS = {
    "steps": "steps",
    "cfg": "cfg",
    "sampler": "sampler_name",
    "scheduler": "scheduler",
    "denoise": "denoise",
}

# Loader (class_type, field) pairs whose literal values are required model files.
_REQUIRED_MODEL_FIELDS: list[tuple[str, str]] = [
    ("CheckpointLoaderSimple", "ckpt_name"),
    ("UNETLoader", "unet_name"),
    ("VAELoader", "vae_name"),
    ("LoraLoader", "lora_name"),
    ("LoraLoaderModelOnly", "lora_name"),
    ("ControlNetLoader", "control_net_name"),
    ("DualCLIPLoader", "clip_name1"),
    ("DualCLIPLoader", "clip_name2"),
    ("CLIPLoader", "clip_name"),
]


@dataclass
class InferredSlots:
    slot_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    required_models: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    negative_suppressed: bool = False
    negative_reason: str | None = None  # "flux" | "zeroed" | "empty" | None
    # The {node_id, input_key} to use if the user overrides suppression and wants a
    # negative slot — set only when the negative traced to a (empty-text) CLIPTextEncode.
    negative_candidate: dict[str, Any] | None = None


def _is_link(value: Any) -> bool:
    """An API-format input link is `[source_node_id, output_index]`."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def _source(graph: dict[str, Any], link: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not _is_link(link):
        return None, None
    nid = str(link[0])
    return nid, graph.get(nid)


def _slot(node_id: str, input_key: str) -> dict[str, Any]:
    return {"node_id": node_id, "input_key": input_key}


def _resolve_cond(
    graph: dict[str, Any],
    link: Any,
    flux_guidance: dict[str, Any],
    visited: set[str] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Follow a conditioning link to its text source.

    Returns (kind, node_id, node) where kind is:
      "text"   — a CLIPTextEncode node (the prompt lives in its `text` input)
      "zeroed" — a ConditioningZeroOut (an explicit empty negative)
      "none"   — dead end / unresolvable
    A FluxGuidance encountered en route captures the `flux_guidance` slot and is
    transparently traversed via its `conditioning` input.
    """
    visited = visited if visited is not None else set()
    out_idx = link[1] if _is_link(link) else None
    nid, node = _source(graph, link)
    if node is None or nid is None or nid in visited:
        return "none", None, None
    visited.add(nid)
    class_type = node.get("class_type")
    inputs = node.get("inputs", {})

    if class_type == "CLIPTextEncode":
        return "text", nid, node
    if class_type in _EDIT_ENCODE_CLASSES:
        # A Qwen edit-encode node IS the text source (prompt lives under a non-"text"
        # key — see _text_key); its conditioning is a terminal for tracing.
        return "text", nid, node
    if class_type in _VIDEO_LATENT_CLASSES:
        # Wan video-latent nodes fuse conditioning: output 0 is positive, 1 is negative
        # (2 is the latent). The sampler links to one of these outputs, so continue the
        # trace into the matching conditioning INPUT of this node.
        if out_idx == 0:
            return _resolve_cond(graph, inputs.get("positive"), flux_guidance, visited)
        if out_idx == 1:
            return _resolve_cond(graph, inputs.get("negative"), flux_guidance, visited)
        return "none", None, None
    if class_type == "FluxGuidance":
        if "guidance" in inputs and not _is_link(inputs["guidance"]):
            flux_guidance.setdefault("node_id", nid)
            flux_guidance.setdefault("input_key", "guidance")
        return _resolve_cond(graph, inputs.get("conditioning"), flux_guidance, visited)
    if class_type == "ConditioningZeroOut":
        return "zeroed", nid, node
    # Generic single-conditioning passthrough (combine/concat-style nodes).
    if "conditioning" in inputs:
        return _resolve_cond(graph, inputs.get("conditioning"), flux_guidance, visited)
    return "none", None, None


def _infer_image_input_slots(
    graph: dict[str, Any], latent_link: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """Detect an img2img / inpaint topology off the sampler's `latent_image`.

    Returns (init_image_slot, mask_slot, notes). Both slots are the `image` input of
    a LoadImage/LoadImageMask node (the runtime-uploaded filename lands there).

    Recognized shapes:
      img2img : latent_image ← VAEEncode(pixels ← LoadImage)
      inpaint : latent_image ← VAEEncodeForInpaint(pixels ← LoadImage, mask ← *)
                latent_image ← SetLatentNoiseMask(samples ← VAEEncode…, mask ← *)
    An empty-latent (txt2img) or an unrecognized source yields (None, None, []) — no
    image slots, behavior unchanged. Partial recognition is reported as a note, never
    guessed (manual declaration in `workflow register` is the fallback).
    """
    nid, node = _source(graph, latent_link)
    if node is None:
        return None, None, []
    class_type = node.get("class_type")
    if class_type in _LATENT_CLASSES:
        return None, None, []  # txt2img — no image input

    inputs = node.get("inputs", {})
    pixels_link: Any = None
    mask_link: Any = None

    if class_type in _VAE_ENCODE_CLASSES:
        pixels_link = inputs.get("pixels")
        mask_link = inputs.get("mask")  # present on VAEEncodeForInpaint
    elif class_type in _INPAINT_LATENT_CLASSES:
        mask_link = inputs.get("mask")
        # Follow `samples` to the VAE-encode that holds the pixels source.
        s_nid, s_node = _source(graph, inputs.get("samples"))
        if s_node is not None and s_node.get("class_type") in _VAE_ENCODE_CLASSES:
            pixels_link = s_node.get("inputs", {}).get("pixels")
            if mask_link is None:
                mask_link = s_node.get("inputs", {}).get("mask")
    else:
        # Some other latent-producing node — not an image input we recognize.
        return None, None, []

    notes: list[str] = []
    init_slot: dict[str, Any] | None = None
    mask_slot: dict[str, Any] | None = None

    if pixels_link is not None:
        p_nid, p_node = _source(graph, pixels_link)
        if p_nid is not None and p_node is not None and p_node.get("class_type") in _IMAGE_LOAD_CLASSES:
            init_slot = _slot(p_nid, "image")
        elif p_node is not None:
            notes.append(
                f"img2img/inpaint: the latent's pixels source is "
                f"{p_node.get('class_type')!r}, not a LoadImage. Declare the "
                "init_image slot manually."
            )

    if mask_link is not None:
        m_nid, m_node = _source(graph, mask_link)
        if m_nid is not None and m_node is not None and m_node.get("class_type") in _MASK_LOAD_CLASSES:
            mask_slot = _slot(m_nid, "image")
        elif m_node is not None:
            notes.append(
                f"inpaint: the mask source is {m_node.get('class_type')!r}, not a "
                "LoadImageMask/LoadImage. Declare the mask slot manually."
            )

    return init_slot, mask_slot, notes


def _find_sampler(graph: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    samplers = [
        (nid, node)
        for nid, node in graph.items()
        if node.get("class_type") in _SAMPLER_CLASSES
    ]
    notes: list[str] = []
    if not samplers:
        notes.append(
            "No KSampler/KSamplerAdvanced found. Custom-sampler topologies "
            "(SamplerCustomAdvanced + BasicScheduler/KSamplerSelect/RandomNoise) are "
            "not auto-inferred — declare seed/steps/sampler slots manually."
        )
        return None, None, notes
    if len(samplers) > 1:
        # Dual-sampler (high/low-noise MoE) graphs: the seed lives on the pass that
        # ADDS noise (add_noise == "enable"); the other pass continues from its latent.
        # Pick that one deterministically instead of relying on dict order.
        noise_adders = [
            (nid, node)
            for nid, node in samplers
            if node.get("class_type") == "KSamplerAdvanced"
            and node.get("inputs", {}).get("add_noise") == "enable"
        ]
        if len(noise_adders) == 1:
            nid, node = noise_adders[0]
            notes.append(
                f"{len(samplers)} samplers found; using the noise-adding pass ({nid}) "
                "as the seed/param carrier (high/low-noise dual-sampler graph)."
            )
            return nid, node, notes
        notes.append(
            f"{len(samplers)} sampler nodes found; inferred from the first "
            f"({samplers[0][0]}). Confirm it's the right one."
        )
    nid, node = samplers[0]
    return nid, node, notes


def _video_latent_node(
    graph: dict[str, Any], latent_link: Any
) -> tuple[str | None, dict[str, Any] | None]:
    """The Wan video-latent node (WanImageToVideo / WanFirstLastFrameToVideo…): the one
    the sampler's latent traces to, else the first such node in the graph."""
    nid, node = _source(graph, latent_link)
    if node is not None and node.get("class_type") in _VIDEO_LATENT_CLASSES:
        return nid, node
    for nid, node in graph.items():
        if node.get("class_type") in _VIDEO_LATENT_CLASSES:
            return nid, node
    return None, None


def _infer_video_frame_slots(
    graph: dict[str, Any], node: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Map first_frame/last_frame to their LoadImage `image` inputs off a Wan video-latent
    node. WanImageToVideo has one image input (start_image → first_frame); FLF2V adds
    end_image → last_frame. A non-LoadImage source is noted, never guessed."""
    slots: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    inputs = node.get("inputs", {})
    for input_key, slot_name in (("start_image", "first_frame"), ("end_image", "last_frame")):
        link = inputs.get(input_key)
        if link is None:
            continue
        src_nid, src = _source(graph, link)
        if src_nid is not None and src is not None and src.get("class_type") in _IMAGE_LOAD_CLASSES:
            slots[slot_name] = _slot(src_nid, "image")
        elif src is not None:
            notes.append(
                f"video: {input_key} traces to {src.get('class_type')!r}, not a LoadImage. "
                f"Declare the {slot_name} slot manually."
            )
    return slots, notes


def _infer_edit_image_slots(
    graph: dict[str, Any], node: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Map edit_image_1..N to the Qwen edit-encode node's image inputs, IN ORDER (order is
    semantic — 'the person from image 1'). Image ports are `image`/`image1`/`image2`/…"""
    slots: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    inputs = node.get("inputs", {})
    img_keys = [k for k in inputs if re.match(r"^image\d*$", k)]
    img_keys.sort(key=lambda k: int(m.group(1)) if (m := re.search(r"(\d+)$", k)) else 0)
    i = 1
    for k in img_keys:
        src_nid, src = _source(graph, inputs.get(k))
        if src_nid is not None and src is not None and src.get("class_type") in _IMAGE_LOAD_CLASSES:
            slots[f"edit_image_{i}"] = _slot(src_nid, "image")
            i += 1
        elif src is not None:
            notes.append(
                f"edit: image input {k!r} traces to {src.get('class_type')!r}, not a "
                "LoadImage. Declare the edit_image slot manually."
            )
    return slots, notes


def _empty_text(node: dict[str, Any] | None) -> bool:
    if node is None:
        return False
    text = node.get("inputs", {}).get(_text_key(node))
    return isinstance(text, str) and text.strip() == ""


def infer_slots(graph: dict[str, Any]) -> InferredSlots:
    """Walk an API-format graph and propose a slot map + required models."""
    result = InferredSlots()
    slot_map = result.slot_map
    flux_present = any(n.get("class_type") == "FluxGuidance" for n in graph.values())

    sampler_id, sampler, sampler_notes = _find_sampler(graph)
    result.notes.extend(sampler_notes)

    if sampler is not None and sampler_id is not None:
        s_inputs = sampler.get("inputs", {})
        s_class = sampler.get("class_type")

        # seed (class-dependent key)
        seed_key = "noise_seed" if s_class == "KSamplerAdvanced" else "seed"
        if seed_key in s_inputs and not _is_link(s_inputs[seed_key]):
            slot_map["seed"] = _slot(sampler_id, seed_key)

        for slot_name, input_key in _SAMPLER_SCALAR_SLOTS.items():
            if input_key in s_inputs and not _is_link(s_inputs[input_key]):
                slot_map[slot_name] = _slot(sampler_id, input_key)

        # Switch-fed scalars (dual-recipe Wan graphs route steps/cfg/end_at_step through
        # ComfySwitchNode/Primitive toggles): they're links, so NOT slot-mapped above.
        # Report it instead of resolving the switch (register propose→confirm can add a
        # manual slot if runtime control is wanted). We do not build a switch resolver.
        linked_scalars = [
            k for k in ("steps", "cfg", "sampler_name", "scheduler")
            if _is_link(s_inputs.get(k))
        ]
        if linked_scalars:
            result.notes.append(
                f"Sampler {', '.join(linked_scalars)} are driven by upstream nodes "
                "(e.g. ComfySwitchNode/Primitive toggles), not literals — not slot-mapped. "
                "Declare them at register time if runtime control is wanted."
            )

        # positive prompt — trace the sampler's `positive` conditioning input.
        flux_guidance: dict[str, Any] = {}
        pos_link = s_inputs.get("positive")
        pos_kind, pos_id, _pos_node = _resolve_cond(graph, pos_link, flux_guidance)
        if pos_kind == "text" and pos_id is not None:
            slot_map["positive"] = _slot(pos_id, _text_key(_pos_node))
        else:
            result.notes.append(
                "Could not resolve the positive prompt by tracing the sampler's "
                "`positive` input. Declare it manually."
            )

        # negative prompt — trace the sampler's `negative` input; suppress unless it
        # resolves to a distinct CLIPTextEncode with non-empty literal text.
        neg_link = s_inputs.get("negative")
        neg_flux: dict[str, Any] = {}
        neg_kind, neg_id, neg_node = _resolve_cond(graph, neg_link, neg_flux)
        pos_node_id = slot_map.get("positive", {}).get("node_id")
        if neg_kind == "text" and neg_id is not None and neg_id != pos_node_id and not _empty_text(neg_node):
            slot_map["negative"] = _slot(neg_id, _text_key(neg_node))
        else:
            result.negative_suppressed = True
            # If the negative traced to a CLIPTextEncode (an empty-text placeholder),
            # we know the node — offer it as the override target in propose→confirm.
            if neg_kind == "text" and neg_id is not None:
                result.negative_candidate = _slot(neg_id, _text_key(neg_node))
            if flux_present:
                result.negative_reason = "flux"
                result.notes.append(
                    "No negative slot: this is a Flux graph (FluxGuidance present, "
                    "CFG≈1.0). The flux_guidance slot is the control instead of a "
                    "negative prompt. Add a negative slot only if you know the graph uses one."
                )
            elif neg_kind == "zeroed":
                result.negative_reason = "zeroed"
                result.notes.append(
                    "No negative slot: the sampler's negative is a ConditioningZeroOut "
                    "(an explicit empty negative)."
                )
            elif neg_kind == "text" and _empty_text(neg_node):
                result.negative_reason = "empty"
                result.notes.append(
                    "No negative slot: the sampler's negative traces to an empty-text "
                    "CLIPTextEncode (a placeholder). Override to add one if intended."
                )
            else:
                result.negative_reason = "empty"
                result.notes.append(
                    "No negative slot inferred (negative input did not resolve to a "
                    "distinct non-empty prompt)."
                )

        # flux_guidance slot (captured during positive resolution, else search)
        if flux_guidance:
            slot_map["flux_guidance"] = _slot(flux_guidance["node_id"], flux_guidance["input_key"])
        elif flux_present:
            for nid, node in graph.items():
                if node.get("class_type") == "FluxGuidance":
                    g = node.get("inputs", {}).get("guidance")
                    if not _is_link(g):
                        slot_map["flux_guidance"] = _slot(nid, "guidance")
                    break

        # dimensions — trace latent_image, fall back to any empty-latent node.
        dim_id, dim_node = _source(graph, s_inputs.get("latent_image"))
        if dim_node is None or dim_node.get("class_type") not in _LATENT_CLASSES:
            for nid, node in graph.items():
                if node.get("class_type") in _LATENT_CLASSES:
                    dim_id, dim_node = nid, node
                    break
        if dim_node is not None and dim_id is not None:
            d_inputs = dim_node.get("inputs", {})
            if "width" in d_inputs and not _is_link(d_inputs["width"]):
                slot_map["width"] = _slot(dim_id, "width")
            if "height" in d_inputs and not _is_link(d_inputs["height"]):
                slot_map["height"] = _slot(dim_id, "height")

        # image input (img2img / inpaint) — trace latent_image to a VAE-encoded
        # upload. Empty-latent topologies return nothing here (txt2img unchanged).
        init_slot, mask_slot, image_notes = _infer_image_input_slots(
            graph, s_inputs.get("latent_image")
        )
        if init_slot is not None:
            slot_map["init_image"] = init_slot
        if mask_slot is not None:
            slot_map["mask"] = mask_slot
        result.notes.extend(image_notes)

        # video input (Wan I2V / FLF2V) — the sampler's latent traces to a Wan
        # video-latent node carrying the frame image inputs + length; width/height/
        # (via CreateVideo) fps are literals these graphs use instead of EmptyLatent.
        video_id, video_node = _video_latent_node(graph, s_inputs.get("latent_image"))
        if video_node is not None and video_id is not None:
            frame_slots, frame_notes = _infer_video_frame_slots(graph, video_node)
            slot_map.update(frame_slots)
            result.notes.extend(frame_notes)
            v_inputs = video_node.get("inputs", {})
            if "length" in v_inputs and not _is_link(v_inputs["length"]):
                slot_map["length"] = _slot(video_id, "length")
            # Dimensions live on the video-latent node (no EmptyLatent to read).
            if "width" not in slot_map and "width" in v_inputs and not _is_link(v_inputs["width"]):
                slot_map["width"] = _slot(video_id, "width")
            if "height" not in slot_map and "height" in v_inputs and not _is_link(v_inputs["height"]):
                slot_map["height"] = _slot(video_id, "height")
            for nid, node in graph.items():
                if node.get("class_type") in _CREATE_VIDEO_CLASSES:
                    fps = node.get("inputs", {}).get("fps")
                    if fps is not None and not _is_link(fps):
                        slot_map["fps"] = _slot(nid, "fps")
                    break

        # edit images (Qwen-Image-Edit): the positive prompt resolves to an edit-encode
        # node; its ordered image inputs become edit_image_1..N.
        if _pos_node is not None and _pos_node.get("class_type") in _EDIT_ENCODE_CLASSES:
            edit_slots, edit_notes = _infer_edit_image_slots(graph, _pos_node)
            slot_map.update(edit_slots)
            result.notes.extend(edit_notes)

    # checkpoint / unet loaders
    for nid, node in graph.items():
        ct = node.get("class_type")
        if ct == "CheckpointLoaderSimple" and "checkpoint" not in slot_map:
            slot_map["checkpoint"] = _slot(nid, "ckpt_name")
        elif ct == "UNETLoader" and "unet" not in slot_map:
            slot_map["unet"] = _slot(nid, "unet_name")

    # LoRA loaders → lora_0, lora_1, … in graph-stable (node-id-sorted) order.
    lora_ids = sorted(
        nid for nid, node in graph.items()
        if node.get("class_type") in {"LoraLoader", "LoraLoaderModelOnly"}
    )
    for i, nid in enumerate(lora_ids):
        slot_map[f"lora_{i}"] = _slot(nid, "lora_name")
        # Map the model-side strength too (both LoraLoader and LoraLoaderModelOnly
        # expose `strength_model`), so a canon-pinned `name:strength` reaches the
        # graph — graph_build writes the matching `lora_{i}_strength` slot.
        if "strength_model" in graph[nid].get("inputs", {}):
            slot_map[f"lora_{i}_strength"] = _slot(nid, "strength_model")
    if len(lora_ids) > 1:
        result.notes.append(
            f"{len(lora_ids)} LoRA loaders found (lora_0..lora_{len(lora_ids) - 1}); "
            "confirm the intended order/strengths."
        )

    result.required_models = _extract_required_models(graph)
    return result


def _extract_required_models(graph: dict[str, Any]) -> list[str]:
    """Collect literal model filenames from all loader nodes (deduped, stable order)."""
    seen: set[str] = set()
    out: list[str] = []
    for class_type, field_name in _REQUIRED_MODEL_FIELDS:
        for node in graph.values():
            if node.get("class_type") != class_type:
                continue
            value = node.get("inputs", {}).get(field_name)
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                out.append(value)
    return out
