"""Build a concrete ComfyUI prompt graph from a spec + a workflow template.

Parameterizing is literally writing values into node inputs by id: for each
semantic slot the template declares (`slot_map[slot] = {node_id, input_key}`),
the matching spec value is written into `graph[node_id]["inputs"][input_key]`. A
spec value whose slot the template lacks (e.g. a negative prompt against a Flux
template that has none) is collected as an advisory `unmapped` entry, never
forced into the graph.
"""

from __future__ import annotations

import copy
from typing import Any

from visual_generation.models import VisualSpec, WorkflowTemplate

# settings-dict key → slot name (the slot the template declares for it).
_SETTING_SLOTS = {
    "steps": "steps",
    "cfg": "cfg",
    "sampler": "sampler",
    "scheduler": "scheduler",
    "denoise": "denoise",
    "flux_guidance": "flux_guidance",
    # Video clip knobs ride the same model-agnostic settings dict ({"length": 81,
    # "fps": 16}); written only when the template declares the slot (video graphs do).
    "length": "length",
    "fps": "fps",
}


def write_slot(
    graph: dict[str, Any], slot_map: dict[str, Any], slot: str, value: Any
) -> bool:
    """Write `value` into graph[node_id]["inputs"][input_key] for `slot`.

    Returns True if the template exposes the slot (and the target node exists),
    False otherwise — the caller decides whether a miss is advisory. This is the
    single place a value lands in a node input; `build_prompt_graph` (spec values)
    and `apply_source_filenames` (uploaded init_image/mask) both go through it.
    """
    target = slot_map.get(slot)
    if target is None:
        return False
    node = graph.get(target["node_id"])
    if not isinstance(node, dict):
        return False
    node.setdefault("inputs", {})[target["input_key"]] = value
    return True


def apply_source_filenames(
    graph: dict[str, Any],
    slot_map: dict[str, Any],
    *,
    init_image: str | None = None,
    mask: str | None = None,
    first_frame: str | None = None,
    last_frame: str | None = None,
    edit_images: list[str] | None = None,
) -> list[str]:
    """Write uploaded pod-side filenames into the image-input slots.

    Used at spend time (after `ComfyUIClient.upload_image`) to place, per modality:
    img2img/inpaint — `init_image` (+ `mask`); FLF2V — `first_frame` (+ `last_frame`);
    Qwen edit — `edit_image_1..N` (ordered). Returns the names of any requested slots
    the template lacks (advisory) — notably an `init_image`/`first_frame` miss means
    the template can't accept that source.
    """
    unmapped: list[str] = []
    if init_image is not None and not write_slot(graph, slot_map, "init_image", init_image):
        unmapped.append("init_image")
    if mask is not None and not write_slot(graph, slot_map, "mask", mask):
        unmapped.append("mask")
    if first_frame is not None and not write_slot(graph, slot_map, "first_frame", first_frame):
        unmapped.append("first_frame")
    if last_frame is not None and not write_slot(graph, slot_map, "last_frame", last_frame):
        unmapped.append("last_frame")
    for i, name in enumerate(edit_images or [], start=1):
        if not write_slot(graph, slot_map, f"edit_image_{i}", name):
            unmapped.append(f"edit_image_{i}")
    return unmapped


def build_prompt_graph(spec: VisualSpec, template: WorkflowTemplate) -> tuple[dict[str, Any], list[str]]:
    """Return (concrete_graph, unmapped_values).

    `unmapped_values` names spec values that had no slot in the template — surfaced
    as advisory (e.g. a negative prompt on a Flux template, or a model with no
    checkpoint/unet slot, or more LoRAs than the template has loader slots).
    """
    graph = copy.deepcopy(template.graph)
    slot_map = template.slot_map
    unmapped: list[str] = []

    def put(slot: str, value: Any, *, advise_as: str | None = None) -> None:
        if not write_slot(graph, slot_map, slot, value):
            unmapped.append(advise_as or slot)

    if spec.prompt:
        put("positive", spec.prompt)
    if spec.negative_prompt is not None:
        put("negative", spec.negative_prompt)
    if spec.seed is not None:
        put("seed", spec.seed)
    if spec.width is not None:
        put("width", spec.width)
    if spec.height is not None:
        put("height", spec.height)

    for key, slot in _SETTING_SLOTS.items():
        if key in spec.settings:
            put(slot, spec.settings[key], advise_as=key)

    if spec.model:
        # The model writes into whichever loader slot the template exposes.
        if "checkpoint" in slot_map:
            put("checkpoint", spec.model)
        elif "unet" in slot_map:
            put("unet", spec.model)
        else:
            unmapped.append("model")

    for i, lora in enumerate(spec.lora_stack):
        put(f"lora_{i}", lora.name, advise_as=f"lora_{i}")
        # Strength rides a parallel `lora_{i}_strength` slot. Templates that predate
        # it simply lack the slot, so the value is collected as advisory and never
        # forced — the loader node keeps its own default. Backward-compatible.
        put(f"lora_{i}_strength", lora.strength, advise_as=f"lora_{i}_strength")

    return graph, unmapped
