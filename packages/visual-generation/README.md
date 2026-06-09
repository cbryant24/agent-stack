# visual-generation

A diffusion image/video generation collaborator — prompt-craft, platform tutor,
and generation/iteration over a ComfyUI backend on RunPod. Modeled on
`voiceover-direction` (cost inversion) and `music-curation` (curated memory).

**Status: Phase 2 in progress — data foundation only.** This package currently
contains the storage + retrieval layer:

- `visual_generation_memory` — one Qdrant collection, three memory types
  discriminated by a `memory_type` payload field:
  - `generation` — the core record. Embeds image/keyframe + caption via the
    runtime multimodal surface (`voyage-multimodal-3`). Carries the full settings
    recipe, model/checkpoint, LoRA stack, workflow ref, seed, dimensions,
    asset path, per-run GPU cost, `identity_bearing`, reaction, rating, status,
    and chain lineage. The binary asset is a disk file referenced by
    `asset_path`, never stored in Qdrant.
  - `technique_lesson` — a confirmed lesson learned by doing. Embeds the
    statement (`voyage-3-large`); scope ∈ prompt/settings/workflow/model.
  - `workflow_template` — a reusable parameterized ComfyUI graph + slot map +
    required models. Embeds a short descriptor.
- A local JSON **model/LoRA registry** (the voice-registry analog): concrete
  named assets looked up by name, never embedded. Entries carry an
  `identity_bearing` flag.
- A **three-collection retrieval** composition: own `visual_generation_memory`
  (primary) + `user_knowledge` (`comfyui_mechanics`/`runpod_mechanics`,
  score-boosted) + `tutorial_research`. Each leg degrades silently; usable
  cold-start.

The CLI, the ComfyUI client, the generation turn (`draft`/`generate`/`report`),
`model sync`, and asset writing land in later steps.
