"""Read/write the editable generation batch file (`<name>.batch.md`).

Modeled on voiceover-direction's `.directed.md`: hand-editable markdown,
per-item metadata in an HTML comment carrying JSON (so the model-agnostic
`settings` dict round-trips losslessly and comments stay invisible when the
markdown renders), extended to hold MULTIPLE specs — one per generation.

    <!-- vg-batch: {"project": "...", "created_at": "...", "source_path": null} -->

    ## a wolf in neon rain
    <!-- vg-spec: {"spec_id": "spec-1", "negative_prompt": null, "settings": {...},
      "model": "flux1-dev.safetensors", "seed": 42, "seed_strategy": "fixed",
      "width": 1024, "height": 1024, "lora_stack": [...], "workflow_ref": "flux-txt2img",
      "identity_bearing": false, "rationale": "..."} -->

    a cinematic portrait of a wolf in neon rain

The `prompt` is the human-readable body (edited directly — no duplication in the
JSON); the `spec_id` lives in the metadata so duplicate headings round-trip and
it's the `generate --section <id>` target. Parsing is malformed-edit tolerant: a
spec whose JSON is missing/garbled degrades to defaults with the body still read
as the prompt (nothing is dropped).

Load-bearing invariant: `read_batch(write_batch(b)) == b` for well-formed files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from visual_generation.models import GenerationBatch, LoraRef, VisualSpec, _now_iso

# `-->` cannot appear inside the JSON, so a non-greedy capture to it is exact even
# with nested braces in `settings`.
_BATCH_META_RE = re.compile(r"<!-- vg-batch:\s*(.*?)\s*-->", re.DOTALL)
_SPEC_META_RE = re.compile(r"<!-- vg-spec:\s*(.*?)\s*-->", re.DOTALL)
_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

# Fields carried in the per-spec JSON (everything except the prompt body + heading).
_SPEC_META_FIELDS = (
    "spec_id",
    "negative_prompt",
    "settings",
    "model",
    "seed",
    "seed_strategy",
    "width",
    "height",
    "lora_stack",
    "workflow_ref",
    "source",
    "project",
    "identity_bearing",
    "rationale",
    "revised_from",
    "created_at",
)


def _spec_meta(spec: VisualSpec) -> dict:
    d = spec.model_dump(include=set(_SPEC_META_FIELDS))
    d["lora_stack"] = [lr.model_dump() for lr in spec.lora_stack]
    return d


def write_batch(batch: GenerationBatch, path: Path) -> None:
    """Serialize a GenerationBatch to a batch-file markdown path."""
    header = {
        "project": batch.project,
        "created_at": batch.created_at,
        "source_path": batch.source_path,
    }
    lines: list[str] = [f"<!-- vg-batch: {json.dumps(header, ensure_ascii=False)} -->", ""]
    for spec in batch.specs:
        heading = spec.heading or (spec.prompt[:60] if spec.prompt else spec.spec_id)
        lines.append(f"## {heading}")
        lines.append(f"<!-- vg-spec: {json.dumps(_spec_meta(spec), ensure_ascii=False)} -->")
        lines.append("")
        lines.append(spec.prompt)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _spec_from(meta: dict, prompt: str, heading: str) -> VisualSpec:
    """Build a VisualSpec from parsed metadata + body prompt, defaulting missing keys."""
    fields = {k: v for k, v in meta.items() if k in VisualSpec.model_fields}
    fields["prompt"] = prompt
    fields["heading"] = heading
    if "lora_stack" in fields and isinstance(fields["lora_stack"], list):
        fields["lora_stack"] = [
            LoraRef(**lr) if isinstance(lr, dict) else lr for lr in fields["lora_stack"]
        ]
    return VisualSpec(**fields)


def read_batch(path: Path) -> GenerationBatch:
    """Read a batch-file markdown path into a GenerationBatch (malformed-tolerant)."""
    text = path.read_text(encoding="utf-8")

    header_m = _BATCH_META_RE.search(text)
    try:
        doc = json.loads(header_m.group(1)) if header_m else {}
    except json.JSONDecodeError:
        doc = {}

    specs: list[VisualSpec] = []
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        meta_m = _SPEC_META_RE.search(block)
        if meta_m:
            try:
                meta = json.loads(meta_m.group(1))
            except json.JSONDecodeError:
                meta = {}  # garbled edit — fall back to defaults, keep the prompt
            prose = block[meta_m.end():].strip()
        else:
            meta = {}
            prose = block.strip()

        specs.append(_spec_from(meta if isinstance(meta, dict) else {}, prose, heading))

    return GenerationBatch(
        project=doc.get("project"),
        created_at=doc.get("created_at") or _now_iso(),
        source_path=doc.get("source_path"),
        specs=specs,
    )


def append_spec(path: Path, spec: VisualSpec, *, project: str | None = None) -> GenerationBatch:
    """Append a spec to an existing batch file (or create a new one), and persist."""
    if path.exists():
        batch = read_batch(path)
    else:
        batch = GenerationBatch(project=project, source_path=str(path))
    if project and not batch.project:
        batch.project = project
    batch.specs.append(spec)
    write_batch(batch, path)
    return batch


def remove_spec(batch: GenerationBatch, spec_id: str) -> GenerationBatch:
    """Drop the spec with `spec_id` from the batch (in-memory; mutates and returns it).

    Raises ValueError on an unknown id so the caller can report it. Pure — the caller
    pairs this with read_batch → write_batch for the lossless round-trip."""
    matches = [s for s in batch.specs if s.spec_id == spec_id]
    if not matches:
        known = ", ".join(s.spec_id for s in batch.specs) or "(none)"
        raise ValueError(f"Unknown spec id {spec_id!r}. Known specs: {known}")
    batch.specs = [s for s in batch.specs if s.spec_id != spec_id]
    return batch


def replace_spec(batch: GenerationBatch, spec_id: str, new_spec: VisualSpec) -> GenerationBatch:
    """Swap the spec with `spec_id` for `new_spec`, preserving order (in-memory).

    Raises ValueError on an unknown id. Pure — caller pairs with read_batch → write_batch."""
    for i, s in enumerate(batch.specs):
        if s.spec_id == spec_id:
            batch.specs[i] = new_spec
            return batch
    known = ", ".join(s.spec_id for s in batch.specs) or "(none)"
    raise ValueError(f"Unknown spec id {spec_id!r}. Known specs: {known}")
