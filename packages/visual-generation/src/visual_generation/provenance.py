"""Execution provenance: the exact graph that was submitted, and hashes of every input and output.

Saved beside each output (`<stem>.graph.json`, `<stem>.provenance.json`) so a render can be
audited and replayed without trusting the spec or the stored record. The graph is hashed from
the bytes captured immediately before submit, so the hash is of what the pod actually received.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from visual_generation.assets import guard_asset_path
from visual_generation.models import VisualSpec, WorkflowTemplate

SCHEMA_VERSION = 1


def canonical_json(obj: Any) -> bytes:
    """Stable bytes for hashing and saving: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def graph_seed(graph_json: bytes, slot_map: dict[str, Any]) -> int | None:
    """The sampler seed actually present in the submitted graph (via the template's seed slot)."""
    target = slot_map.get("seed")
    if target is None:
        return None
    node = json.loads(graph_json).get(target["node_id"])
    if not isinstance(node, dict):
        return None
    value = node.get("inputs", {}).get(target["input_key"])
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class ProvenanceFiles:
    graph_path: Path
    provenance_path: Path
    graph_sha256: str


def provenance_record(
    *,
    generation_id: str,
    spec: VisualSpec,
    template: WorkflowTemplate,
    graph_json: bytes,
    prompt_id: str,
    endpoint: str,
    resolved_seed: int | None,
    effective_settings: dict[str, Any],
    sources: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    unmapped: list[str],
    neutralized_loras: list[str],
    started_at: str,
    completed_at: str,
    seconds: float,
    identity_bearing: bool,
) -> dict[str, Any]:
    model_note = "file hash lives on the pod's volume; not computed locally"
    return {
        "schema": SCHEMA_VERSION,
        "generation_id": generation_id,
        "spec_id": spec.spec_id,
        "project": spec.project,
        "prompt_id": prompt_id,
        "endpoint": endpoint,
        "identity_bearing": identity_bearing,
        "resolved_seed": resolved_seed,
        "seed_strategy": spec.seed_strategy,
        "graph_seed": graph_seed(graph_json, template.slot_map),
        "seed_slot": template.slot_map.get("seed"),
        "workflow": {
            "name": template.name,
            "template_entry_id": template.entry_id,
            "sha256": sha256_hex(canonical_json(template.graph)),
        },
        "model": {"name": spec.model, "sha256": None, "note": model_note},
        "loras": [{"name": lr.name, "strength": lr.strength, "sha256": None} for lr in spec.lora_stack],
        "neutralized_loras": list(neutralized_loras),
        "settings": effective_settings,
        "size": {"width": spec.width, "height": spec.height},
        "unmapped": list(unmapped),
        "sources": sources,
        "outputs": outputs,
        "timing": {"started_at": started_at, "completed_at": completed_at, "seconds": seconds},
    }


def write_provenance(
    asset_path: Path,
    *,
    identity_bearing: bool,
    graph_json: bytes,
    record: dict[str, Any],
    guard: bool = True,
) -> ProvenanceFiles:
    """Write the graph and provenance files next to `asset_path` (same directory, so an
    identity-bearing output's sidecars stay under the secured root). Returns their paths and
    the graph's sha256. Raises on any write failure: an output must not go without its record."""
    graph_path = asset_path.parent / f"{asset_path.stem}.graph.json"
    prov_path = asset_path.parent / f"{asset_path.stem}.provenance.json"
    if guard:
        guard_asset_path(graph_path, identity_bearing)
        guard_asset_path(prov_path, identity_bearing)
    graph_sha = sha256_hex(graph_json)
    graph_path.write_bytes(graph_json)
    full = {**record, "submitted_graph_path": str(graph_path), "submitted_graph_sha256": graph_sha}
    prov_path.write_text(json.dumps(full, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return ProvenanceFiles(graph_path=graph_path, provenance_path=prov_path, graph_sha256=graph_sha)
