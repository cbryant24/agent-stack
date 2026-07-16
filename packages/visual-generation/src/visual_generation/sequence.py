"""Read/write a per-scene FLF2V clip sequence file (`<scene>.sequence.md`).

Modeled on `batch_file.py`: hand-editable markdown, per-clip metadata in an HTML
comment carrying JSON (so the model-agnostic `settings` dict round-trips and the
comment stays invisible when the markdown renders). A sequence orders the FLF2V
clips of ONE scene and encodes the boundary-sharing invariant that makes the
"every clip endpoint is an approved still" promise structural: consecutive clips
share a keyframe (`clip[n].last_frame == clip[n+1].first_frame`).

    <!-- vg-sequence: {"project": "short-film", "scene": "bar", "fps": 16, "clip_frames": 81} -->

    ## clip 1 — narrator enters, Celeste looks up
    <!-- vg-clip: {"clip_id": "c1", "first_frame": "<gen A>", "last_frame": "<gen B>",
         "workflow_ref": "wan22-flf2v", "settings": {}, "seed": 123, "order": 1} -->
    stop-motion felt animation, the narrator walks in from the left, Celeste looks up ...

The `motion_prompt` is the human-readable body (edited directly — no duplication in
the JSON); the metadata carries the boundary gen_ids + order. Parsing is
malformed-edit tolerant (a garbled JSON block degrades to defaults, body kept).

Load-bearing invariant: `read_sequence(write_sequence(s)) == s` for well-formed files.
`validate_sequence` enforces order-contiguity + boundary-sharing as HARD errors (the
guard that keeps a scene's clips a continuous chain).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from visual_generation.constants import FLF2V_TEMPLATE_NAME
from visual_generation.models import (
    ClipSpec,
    Sequence,
    VisualResult,
    VisualSource,
    VisualSpec,
    _new_id,
    _now_iso,
)

# `-->` cannot appear inside the JSON, so a non-greedy capture to it is exact even
# with nested braces in `settings`.
_SEQ_META_RE = re.compile(r"<!-- vg-sequence:\s*(.*?)\s*-->", re.DOTALL)
_CLIP_META_RE = re.compile(r"<!-- vg-clip:\s*(.*?)\s*-->", re.DOTALL)
_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

# Fields carried in the per-clip JSON (everything except the motion-prompt body + heading).
_CLIP_META_FIELDS = (
    "clip_id",
    "first_frame",
    "last_frame",
    "workflow_ref",
    "settings",
    "seed",
    "seed_strategy",
    "order",
)


def _clip_meta(clip: ClipSpec) -> dict[str, Any]:
    return clip.model_dump(include=set(_CLIP_META_FIELDS))


def write_sequence(seq: Sequence, path: Path) -> None:
    """Serialize a Sequence to a `.sequence.md` markdown path (atomic write)."""
    header = {
        "project": seq.project,
        "scene": seq.scene,
        "fps": seq.fps,
        "clip_frames": seq.clip_frames,
        "created_at": seq.created_at,
        "source_path": seq.source_path,
    }
    lines: list[str] = [f"<!-- vg-sequence: {json.dumps(header, ensure_ascii=False)} -->", ""]
    for clip in seq.clips:
        heading = clip.heading or (clip.motion_prompt[:60] if clip.motion_prompt else clip.clip_id)
        lines.append(f"## {heading}")
        lines.append(f"<!-- vg-clip: {json.dumps(_clip_meta(clip), ensure_ascii=False)} -->")
        lines.append("")
        lines.append(clip.motion_prompt)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)


def _clip_from(meta: dict[str, Any], motion_prompt: str, heading: str) -> ClipSpec:
    """Build a ClipSpec from parsed metadata + body, defaulting missing keys."""
    fields = {k: v for k, v in meta.items() if k in ClipSpec.model_fields}
    fields["motion_prompt"] = motion_prompt
    fields["heading"] = heading
    return ClipSpec(**fields)


def read_sequence(path: Path) -> Sequence:
    """Read a `.sequence.md` path into a Sequence (malformed-tolerant)."""
    text = path.read_text(encoding="utf-8")

    header_m = _SEQ_META_RE.search(text)
    try:
        doc = json.loads(header_m.group(1)) if header_m else {}
    except json.JSONDecodeError:
        doc = {}

    clips: list[ClipSpec] = []
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        meta_m = _CLIP_META_RE.search(block)
        if meta_m:
            try:
                meta = json.loads(meta_m.group(1))
            except json.JSONDecodeError:
                meta = {}  # garbled edit — fall back to defaults, keep the body
            body = block[meta_m.end():].strip()
        else:
            meta = {}
            body = block.strip()

        clips.append(_clip_from(meta if isinstance(meta, dict) else {}, body, heading))

    return Sequence(
        project=doc.get("project"),
        scene=doc.get("scene"),
        fps=doc.get("fps", 16),
        clip_frames=doc.get("clip_frames", 81),
        created_at=doc.get("created_at") or _now_iso(),
        source_path=doc.get("source_path"),
        clips=clips,
    )


def validate_sequence(seq: Sequence) -> list[str]:
    """Structural validation (HARD errors, not advisories): `order` contiguous 1..N,
    each clip has both frames, and consecutive clips share a boundary
    (`clip[n].last_frame == clip[n+1].first_frame`). Returns a list of error strings
    (empty = valid). Existence of the referenced gen_ids is checked at render time (it
    needs the store); this is the pure, offline structural check."""
    errors: list[str] = []
    clips = sorted(seq.clips, key=lambda c: c.order)
    n = len(clips)
    if n == 0:
        return ["sequence has no clips"]

    orders = [c.order for c in clips]
    if orders != list(range(1, n + 1)):
        errors.append(f"clip `order` must be contiguous 1..{n}; got {orders}")

    for c in clips:
        if not c.first_frame or not c.last_frame:
            errors.append(f"clip {c.clip_id!r} (order {c.order}) is missing a first/last frame")

    for a, b in zip(clips, clips[1:]):
        if a.last_frame and b.first_frame and a.last_frame != b.first_frame:
            errors.append(
                f"boundary break: clip {a.order} last_frame {a.last_frame!r} != "
                f"clip {b.order} first_frame {b.first_frame!r} (consecutive clips must "
                "share a keyframe)"
            )
    return errors


def scaffold_sequence(
    keyframes: list[str],
    *,
    project: str | None = None,
    scene: str | None = None,
    fps: int = 16,
    clip_frames: int = 81,
    workflow_ref: str = FLF2V_TEMPLATE_NAME,
    motion_prompts: list[str] | None = None,
    source_path: str | None = None,
) -> Sequence:
    """Wire an ORDERED list of approved keyframe gen_ids into a boundary-shared clip
    sequence: N keyframes → N-1 clips, clip i spanning keyframes[i]→keyframes[i+1] with
    order i+1, so `clip[n].last_frame == clip[n+1].first_frame` holds by construction.
    `motion_prompts` (optional, one per clip) fills the bodies; otherwise they're left
    empty for the director (or an LLM pass) to write. Deterministic — no LLM, no I/O."""
    if len(keyframes) < 2:
        raise ValueError("a sequence needs at least 2 keyframes (to form 1 clip)")
    clips: list[ClipSpec] = []
    for i in range(len(keyframes) - 1):
        clips.append(
            ClipSpec(
                clip_id=_new_id(),
                motion_prompt=(motion_prompts[i] if motion_prompts and i < len(motion_prompts) else ""),
                first_frame=keyframes[i],
                last_frame=keyframes[i + 1],
                workflow_ref=workflow_ref,
                settings={"length": clip_frames, "fps": fps},
                order=i + 1,
            )
        )
    return Sequence(
        project=project,
        scene=scene,
        fps=fps,
        clip_frames=clip_frames,
        source_path=source_path,
        clips=clips,
    )


def clip_to_spec(clip: ClipSpec, seq: Sequence) -> VisualSpec:
    """Bridge a ClipSpec to a VisualSpec `generate` can spend: the two boundary
    keyframes become an FLF2V source (first_frame + last_frame from_generation refs),
    and length/fps ride `settings`. Used by `sequence render`."""
    settings = dict(clip.settings)
    settings.setdefault("length", seq.clip_frames)
    settings.setdefault("fps", seq.fps)
    return VisualSpec(
        spec_id=clip.clip_id,
        heading=clip.heading,
        prompt=clip.motion_prompt,
        settings=settings,
        seed=clip.seed,
        seed_strategy=clip.seed_strategy,
        workflow_ref=clip.workflow_ref or FLF2V_TEMPLATE_NAME,
        project=seq.project,
        source=VisualSource(
            from_generation=clip.first_frame,
            last_from_generation=clip.last_frame,
        ),
    )


def sequence_to_specs(seq: Sequence) -> list[VisualSpec]:
    """The scene's clips (in `order`) as FLF2V VisualSpecs ready for plan → spend."""
    return [clip_to_spec(c, seq) for c in sorted(seq.clips, key=lambda c: c.order)]


def build_scene_manifest(
    seq: Sequence, results_by_clip: dict[str, VisualResult]
) -> dict[str, Any]:
    """Build the scene-manifest.json payload edit-brief discovers by project_id: the
    scene's rendered clips in order (asset path, duration, boundary gen_ids) plus the
    ordered shared-boundary gen_ids. `results_by_clip` maps clip_id → the spend result;
    clips that didn't render (skipped) are omitted."""
    fps = seq.fps or 16
    manifest_clips: list[dict[str, Any]] = []
    for c in sorted(seq.clips, key=lambda c: c.order):
        res = results_by_clip.get(c.clip_id)
        if res is None:
            continue
        frames = c.settings.get("length", seq.clip_frames)
        manifest_clips.append(
            {
                "clip_id": c.clip_id,
                "order": c.order,
                "generation_id": res.generation_id,
                "asset_path": res.asset_path,
                "duration_sec": round(frames / fps, 4),
                "first_frame": c.first_frame,
                "last_frame": c.last_frame,
            }
        )
    boundaries = [
        a["last_frame"]
        for a, b in zip(manifest_clips, manifest_clips[1:])
        if a["last_frame"] == b["first_frame"]
    ]
    return {
        "project": seq.project,
        "scene": seq.scene,
        "fps": fps,
        "clip_frames": seq.clip_frames,
        "clips": manifest_clips,
        "boundaries": boundaries,
    }


def write_scene_manifest(manifest: dict[str, Any], path: Path) -> None:
    """Atomically write a scene-manifest.json payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(path)
