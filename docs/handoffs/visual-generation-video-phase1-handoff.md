---
title: Visual Generation — Video (WAN 2.2) Phase 1 Discovery Handoff
date: 2026-06-18
type: phase-1-handoff
agent: visual-generation
project: agent-stack
status: active
---

# Visual Generation — Video (WAN 2.2) Phase 1 Discovery Handoff

Video is **not a new agent** — it is the largest deferred item inside
`visual-generation`, which the Phase 2 architecture was explicitly built to accept
("One path, not two" — Phase 2 handoff Q7; `models.py`: lineage spans output types so
an I2V clip's parent can be a prior still). So this was a **scoped discovery**, not a
cold-start Phase 1: its job was to *validate* the "one path" claim and resolve the
specifics it waved at, not re-derive the architecture. The validation result: the
claim holds. Video reuses the existing primitives (the `vg-spec`, the workflow
template + slot map, the model registry, the generation record, the
draft→generate→report turn) with new values/keys and a small number of additive code
deltas — no new architecture.

Hands off to **Phase 2 (Implementation)**. Deferred items live in
`docs/v2-refinements/visual-generation-v2-refinements.md`; between-phase knowledge
gathering in `docs/handoffs/visual-generation-video-phase1-research-signals.md`.

## Settled gates

1. **Scope.** Dedicated discovery + produce the missing
   `visual-generation-v2-refinements.md` (done). Not folded into a visual-generation
   Phase 3; not a skip-discovery build.
2. **Model: WAN 2.2.** Open-weights (Apache 2.0), self-hosted on the user's RunPod
   ComfyUI pod — the same property that chose RunPod+ComfyUI originally. WAN 2.5/2.6
   were rejected: both are **closed commercial APIs**, which would break self-hosting,
   the content-permissive posture, and the "no RunPod credential, user-supplied
   `--endpoint`" architecture.
3. **v1 modes: T2V + I2V together.** VACE deferred. I2V is in v1 because the
   img2img/inpaint refinement path it depends on is confirmed fully built (see BP3).

## Break-point decisions (the five places "one path" was pressure-tested)

### BP1 — WAN template + settings schema + model registry (the MoE two-stage)

**Decision: reuse existing primitives; it is a new workflow-template *family* plus
extended settings keys and registry entries, not new architecture.**

- **Workflow template.** WAN 2.2 14B uses a Mixture-of-Experts split by denoising
  stage: a high-noise expert (structure/layout/motion, early steps) hands off to a
  low-noise expert (texture/detail, later steps) at a **boundary step**. The ComfyUI
  graph therefore has **two model-loader nodes** and a sampling chain that switches at
  the boundary. Registered once as a named template, same as stills.
- **Settings schema.** `vg-spec.settings` gains WAN-only keys: frames/length, fps,
  shift, boundary step, per-stage steps. "Schema" = the set of keys the video path
  understands.
- **Model registry.** The two MoE expert files register as **two entries the slot map
  references** — NOT fused into one logical entry. Rationale: the slot map already
  addresses individual nodes, the two samplers are genuinely two graph nodes, and
  fusing them would hide the split the spec deliberately surfaces for the tutor role.
- **Thin WAN-aware sanity check at the gate (additive).** Stills use a free-form,
  unvalidated `settings` dict — the same thing that produced the oversaturated
  Z-Image failure (SDXL recipe applied to a turbo model). On stills a bad recipe costs
  seconds; on a WAN clip it costs minutes of H100-class GPU. So the gate gets a thin
  check that echoes the resolved recipe and flags obviously-wrong values (cfg/steps
  far outside WAN's range, a missing low-noise stage) before spending. Does not fork
  the architecture. Its valid-range source is a between-phase research signal.

### BP2 — Keyframe → multimodal embedding

**Decision: one additive field; everything else reuses the stills embedding path.**

- Stills embed `MultimodalInput(text=caption, image_path=asset_path)` — for a still
  the asset *is* an image. Video's asset is an `.mp4`, which can't be handed to an
  image embedder. **Add an optional `keyframe_path` to `VisualGeneration`;
  `_generation_input` uses `keyframe_path or asset_path`.** Stills leave it unset
  (unchanged behavior); video sets it to an extracted frame. Embedding, caption, and
  query paths are otherwise untouched.
- **Caption: reuse `_caption_for` verbatim** (the prompt text, `[:300]`). For I2V the
  prompt is "the motion to make," which is good index text. No video-specific caption.
- **Keyframe = the middle frame**, extracted via ffmpeg from the **produced clip**.
  For I2V the keyframe comes from the *output*, never the seed image — embedding the
  seed would collapse the I2V record onto its parent still in vector space.
- Contact-sheet (multi-frame) keyframe is deferred (v2-refinements): the
  `keyframe_path` field makes it a clean later swap.

### BP3 — I2V specifics

**Decision: reuses the proven img2img source path; one new wrinkle (denoise
semantics) handled by an explicit output marker.**

- **Already handled (confirmed in code):** getting the seed image into the clip is the
  working img2img path — `--from <gen_id>` (a prior still's saved file) or `--image
  <path>`, then `upload_image` → the graph's load-image slot. Cross-type lineage
  (`parent_id` / `chain_root_id` spanning a still→video edge) is already built.
- **The wrinkle — `denoise` is meaningless for I2V.** img2img auto-fills
  `denoise=DEFAULT_DENOISE` whenever a spec has a source, because img2img dissolves and
  repaints the source. I2V does not dissolve the seed — it keeps it as frame 1 and
  generates motion forward. So that auto-fill must be **skipped** for video.
- **Decision: add an explicit `output` field to the spec (`image | video`, default
  `image`), visible in the batch file; the registered template also declares its kind;
  cross-check at generate flags a mismatch.** Source-handling then branches: image
  target → img2img (denoise applies); video target → I2V seed frame (no denoise,
  written to the I2V graph's load-image slot). This same marker tells the BP1 sanity
  check which recipe ranges to validate, and the BP4 estimator which kind to segment.
  (Inferring kind purely from the template was considered and rejected: the kind isn't
  visible until generate resolves the template, and the batch file should be readable.)

### BP4 — GPU cost model

**Decision: keep the tracker architecture; make the estimate kind-aware.**

- The tracker already shows a history-learned **per-run estimate at the gate**
  (`estimate_per_run_cost`: mean of recent non-zero per-run costs, else a cold-start
  default), plus the `GpuLedger`, optional declared budget, and the
  `--max-session-cost` between-clip ceiling. Architecture is right; video needs no new
  cost system.
- **The one break: the estimate is a flat average of all runs.** Fine for uniform,
  seconds-long stills; wrong for video (minutes per clip, cost swings with
  length/resolution) — and pooling stills + video blends them into a number fitting
  neither. **Decision: segment the learned estimate by the `output` kind, and give
  video its own cold-start default (minutes, not seconds).** Everything else unchanged;
  `--max-session-cost` remains the real overspend guard.
- Size-aware bucketing (resolution × length) is deferred (v2-refinements) — the gate
  is advisory and the ceiling guards real overspend, so a kind-segmented average is
  the MVP floor.

### BP5 — Reaction vocabulary

**Decision: keep the five values; add an optional video aspect qualifier.**

- The five reactions (`loved`, `liked`, `liked_with_changes`, `disliked`,
  `render_failed`) and the load-bearing `disliked` (recipe was wrong — weighs against
  it) vs. `render_failed` (recipe fine, render missed — retry, territory open) split
  hold for video unchanged (a resolution-hang clip is a clean `render_failed`).
- **The new need: a plain `disliked` can't say whether the *look* or the *motion*
  failed** — and motion is video's whole new failure surface, with a different fix
  (settings: frames/shift/steps) than a look miss (prompt/cfg). **Decision: add an
  optional `composition | motion | both` aspect qualifier on video reports, riding
  along with `disliked` / `liked_with_changes` and feeding the existing note/lesson
  plumbing.** Stills don't set it.
- Finer temporal taxonomy (flicker vs. morph vs. object-permanence) is deferred
  (v2-refinements); motion-vs-composition is the MVP floor.

## Net code deltas for Phase 2 (all additive)

- `VisualSpec`: new `output: "image" | "video"` field (default `image`); WAN settings
  keys accepted in `settings`.
- `WorkflowTemplate`: declares its kind (image/video) for the BP3 cross-check.
- `VisualGeneration`: new optional `keyframe_path`; `_generation_input` prefers it.
- `generate.py`: branch source-provisioning on `output` (skip denoise default for
  video); after writing an `.mp4` asset, extract the middle frame to `keyframe_path`
  via ffmpeg; the thin WAN-aware recipe sanity check at the gate.
- `gpu_tracker.estimate_per_run_cost`: segment prior costs by `output` kind; add a
  video cold-start default constant.
- `report`: optional `composition | motion | both` aspect on video reports → note/
  lesson plumbing.
- Registry + slot map: two WAN expert entries; slot map targets both loaders + the
  WAN settings.
- ffmpeg becomes a runtime dependency (already used elsewhere in the workspace —
  yt-intelligence-pipeline, edit-brief's ffprobe).

## What is a user/between-phase task, not agent code

- Building and exporting (API format) the WAN **T2V** and **I2V** ComfyUI graphs, then
  `workflow register`-ing them (graph authoring is deferred; the agent consumes graphs).
- Closing the WAN knowledge gap and supplying the sanity-check recipe ranges (see the
  research-signals doc).

## Phase 2 verification target

A real-use smoke test: a T2V clip and an I2V clip (seed = a prior still) generated
end-to-end against a WAN-loaded RunPod pod, each recorded with a middle-frame
keyframe, retrievable via `recall`, with the gate showing a kind-correct cost estimate
and the sanity check catching a deliberately-bad recipe before spend.
