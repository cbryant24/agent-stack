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

from dataclasses import dataclass, field
from typing import Any

_SAMPLER_CLASSES = {"KSampler", "KSamplerAdvanced"}
_LATENT_CLASSES = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyLatentImageAdvanced"}

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
    nid, node = _source(graph, link)
    if node is None or nid in visited:
        return "none", None, None
    visited.add(nid)
    class_type = node.get("class_type")
    inputs = node.get("inputs", {})

    if class_type == "CLIPTextEncode":
        return "text", nid, node
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
        notes.append(
            f"{len(samplers)} sampler nodes found; inferred from the first "
            f"({samplers[0][0]}). Confirm it's the right one."
        )
    nid, node = samplers[0]
    return nid, node, notes


def _empty_text(node: dict[str, Any] | None) -> bool:
    if node is None:
        return False
    text = node.get("inputs", {}).get("text")
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

        # positive prompt — trace the sampler's `positive` conditioning input.
        flux_guidance: dict[str, Any] = {}
        pos_link = s_inputs.get("positive")
        pos_kind, pos_id, _pos_node = _resolve_cond(graph, pos_link, flux_guidance)
        if pos_kind == "text" and pos_id is not None:
            slot_map["positive"] = _slot(pos_id, "text")
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
            slot_map["negative"] = _slot(neg_id, "text")
        else:
            result.negative_suppressed = True
            # If the negative traced to a CLIPTextEncode (an empty-text placeholder),
            # we know the node — offer it as the override target in propose→confirm.
            if neg_kind == "text" and neg_id is not None:
                result.negative_candidate = _slot(neg_id, "text")
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
