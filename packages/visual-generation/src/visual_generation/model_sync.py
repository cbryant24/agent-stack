"""Parse ComfyUI /object_info into ModelAssets, and reconcile a sync against the
existing registry.

`parse_object_info` reads the COMBO option lists off the loader nodes (a loader's
model field is a COMBO whose first element is the list of installed filenames) and
maps each to a `ModelAsset(source="synced")`.

`reconcile` is the merge-aware writer of the step-2 `replace()` seam. A sync must
NOT clobber manual opsec metadata — chiefly `identity_bearing` — on assets the
user previously registered by name. The rule (keyed by name):

  - on pod AND existed before  → merge: preserve identity_bearing/base_model/
    metadata/source from the existing entry, refresh kind from sync, mark present.
  - on pod AND new             → add as source="synced".
  - absent, existing manual     → keep + flag present_on_endpoint=False (a
    deliberately-registered asset, often identity-bearing, must not vanish
    because a given pod is down or lacks it).
  - absent, existing synced      → drop (it was only ever a mirror of the pod).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from visual_generation.constants import (
    ASSET_KIND_CHECKPOINT,
    ASSET_KIND_CLIP,
    ASSET_KIND_CONTROLNET,
    ASSET_KIND_LORA,
    ASSET_KIND_VAE,
)
from visual_generation.models import ModelAsset

# (node class_type, input field) → asset kind. The mapping is by loader node, not
# by model name — the same way the slot heuristic is wiring-derived, not hardcoded.
_LOADER_FIELDS: list[tuple[str, str, str]] = [
    ("CheckpointLoaderSimple", "ckpt_name", ASSET_KIND_CHECKPOINT),
    ("UNETLoader", "unet_name", ASSET_KIND_CHECKPOINT),
    ("LoraLoader", "lora_name", ASSET_KIND_LORA),
    ("LoraLoaderModelOnly", "lora_name", ASSET_KIND_LORA),
    ("VAELoader", "vae_name", ASSET_KIND_VAE),
    ("ControlNetLoader", "control_net_name", ASSET_KIND_CONTROLNET),
    ("DualCLIPLoader", "clip_name1", ASSET_KIND_CLIP),
    ("DualCLIPLoader", "clip_name2", ASSET_KIND_CLIP),
    ("CLIPLoader", "clip_name", ASSET_KIND_CLIP),
]


def _combo_options(node_def: dict[str, Any], field_name: str) -> list[str]:
    """Return the COMBO option list for `field_name` on a node definition, or [].

    /object_info shapes a field as `[options_list, {metadata}]` (or just
    `[options_list]`); a COMBO is identified by its first element being a list.
    The field may live under `input.required` or `input.optional`.
    """
    inputs = node_def.get("input", {})
    for group in ("required", "optional"):
        spec = inputs.get(group, {}).get(field_name)
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return [str(o) for o in spec[0]]
    return []


def parse_object_info(object_info: dict[str, Any]) -> list[ModelAsset]:
    """Build synced ModelAssets from a /object_info payload (deduped by name)."""
    assets: dict[str, ModelAsset] = {}
    for class_type, field_name, kind in _LOADER_FIELDS:
        node_def = object_info.get(class_type)
        if not isinstance(node_def, dict):
            continue
        for filename in _combo_options(node_def, field_name):
            if filename and filename not in assets:
                assets[filename] = ModelAsset(name=filename, kind=kind, source="synced")
    return list(assets.values())


@dataclass
class ReconcileResult:
    """The merged registry plus a breakdown of what the sync did."""

    merged: list[ModelAsset] = field(default_factory=list)
    added: list[str] = field(default_factory=list)        # new, synced in
    refreshed: list[str] = field(default_factory=list)     # existed + present → merged
    kept_absent: list[str] = field(default_factory=list)   # manual, absent → kept + flagged
    dropped: list[str] = field(default_factory=list)       # previously-synced, now absent


def reconcile(existing: list[ModelAsset], synced: list[ModelAsset]) -> ReconcileResult:
    """Merge a fresh sync against the existing registry per the (b) rule."""
    existing_by_name = {a.name: a for a in existing}
    synced_names = {a.name for a in synced}
    result = ReconcileResult()

    for syn in synced:
        prior = existing_by_name.get(syn.name)
        if prior is None:
            result.merged.append(syn)
            result.added.append(syn.name)
        else:
            # Preserve manual/opsec fields; refresh kind from the pod; mark present.
            result.merged.append(
                prior.model_copy(update={"kind": syn.kind, "present_on_endpoint": True})
            )
            result.refreshed.append(syn.name)

    for prior in existing:
        if prior.name in synced_names:
            continue
        if prior.source == "registered":
            result.merged.append(prior.model_copy(update={"present_on_endpoint": False}))
            result.kept_absent.append(prior.name)
        else:
            result.dropped.append(prior.name)

    return result
