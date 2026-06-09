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
}


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
        target = slot_map.get(slot)
        if target is None:
            unmapped.append(advise_as or slot)
            return
        node = graph.get(target["node_id"])
        if not isinstance(node, dict):
            unmapped.append(advise_as or slot)
            return
        node.setdefault("inputs", {})[target["input_key"]] = value

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

    return graph, unmapped
