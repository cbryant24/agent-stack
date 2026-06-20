---
title: Visual Generation Agent — v2 Refinements (deferred)
date: 2026-06-18
agent: visual-generation
status: open
---

# Visual Generation — Deferred Items

The durable record of everything captured-but-not-built for `visual-generation`.
This file is created late: visual-generation reached Phase 2 MVP (stills + img2img,
152 tests) but never ran a Phase 3, so it is the one built agent that lacked a
v2-refinements doc. This file is now its durable home. It folds together (a) the
deferrals the Phase 2 handoff recorded only in prose, and (b) the new deferrals from
the **video (WAN 2.2) discovery** (2026-06-18). This file stays current.

## From the Phase 2 handoff (deferred but never homed)

- **VACE (video-to-video / control).** The third WAN mode (reference/control-driven
  video editing). Out of scope for the video v1, which is T2V + I2V only. VACE is a
  later mode on the same path once T2V/I2V are proven.
- **LoRA training (ai-toolkit).** v1 is LoRA *use*-only (registry entry + workflow
  slot, free). Training is a separate subsystem — dataset prep, training config, a
  long expensive GPU run, a different turn — deferred behind an adoption trigger.
- **RunPod stop-automation (Tier-2).** v1 holds no RunPod credential; pod lifecycle
  is Tier-1 advisory (the agent talks only to the user-supplied `--endpoint` and
  prompts to stop on drain). Real stop-automation (agent holds a key, auto-stops on
  drain/idle) is Tier-2. Start stays advisory even then.
- **Encryption-at-rest for identity artifacts.** Identity-bearing LoRAs and the
  generations using them live in a secured, isolated path under `~/agent-data/`,
  write-guarded against the vault and synced locations. Encryption-at-rest is the
  deferred hardening on top of that path separation.
- **The `reference` memory type.** An image+caption `reference` memory_type (the
  `sound_reference` analog) for reference-driven direction. Deferred, as voiceover
  deferred its reference layer.
- **Graph authoring.** v1 *consumes* API-format ComfyUI graphs the user builds and
  exports; it does not generate graphs from scratch. Authoring is deferred — and it
  is the reason the WAN T2V/I2V graphs are a between-phase user task (see the video
  research-signals doc), not an agent capability.
- **`knowledge ingest-docs` `--decisions` / `--url` refinements.** Now shared at the
  runtime level (`agent_runtime.knowledge.docs_ingest`); these refinements land once
  for all agents, not per-agent.

## From the video (WAN 2.2) discovery — 2026-06-18

These were deliberately deferred during video discovery as non-MVP-blocking. Each has
a clean drop-in point because the video v1 design reuses the existing primitives.

- **Contact-sheet (multi-frame) keyframe embedding.** Video v1 embeds the clip's
  **middle frame** as the search keyframe. A single frame can't encode motion, so two
  clips with the same opening frame but different movement embed near-identically.
  The deferred fix is a 2×2 contact sheet of evenly-spaced frames tiled into one image
  (still a single image to `voyage-multimodal-3`). Clean drop-in: the new
  `keyframe_path` field doesn't care how the image was produced, so switching the
  extraction step is a localized change. Revisit if real-use `recall` proves
  motion-blind. (Recall queries mostly target subject/style, which one frame captures,
  so this is a refinement, not a blocker.)
- **Size-aware GPU cost estimate.** Video v1 segments the learned per-run estimate by
  `output` kind (video averages against video, stills against stills) with a
  video-specific cold-start default. It does **not** bucket by size. A 5s/480p clip
  and a 5s/720p clip have very different costs but would share one average. The
  deferred fix buckets the estimate by resolution × clip-length so the gate figure
  reflects comparable clips. Deferred because the gate is advisory and
  `--max-session-cost` is the real overspend guard, so a roughly-right average plus
  the ceiling is enough for MVP.
- **High-quality WAN path (fp16 experts / full 20-step).** v1 runs the fp8 experts + the
  lightx2v 4-step LoRAs (the ComfyUI template default) with the fp8 text encoder — chosen
  for speed/cost and because it fits the pod's 100 GB `/workspace` volume. The director
  prefers a higher-precision path "when feasible" (e.g. fp16 encoder, and more importantly
  fp16 diffusion experts + the full ~20-step non-LoRA recipe). Deferred because it's gated
  on **infrastructure, not code**: four fp16 14B experts are ~112 GB alone, so the quality
  path needs a larger volume (or per-session model swapping), not just a setting. When the
  volume grows, capture the standard 20-step recipe ranges too (see the video
  research-signals doc — the sanity check keys ranges off the LoRA stack).
- **Finer temporal reaction taxonomy.** Video v1 keeps the five reaction values and
  adds an optional `composition | motion | both` aspect qualifier on video reports
  (threaded into the existing note/lesson plumbing). It does not distinguish *kinds*
  of motion failure (flicker vs. morph vs. object-permanence). A richer temporal
  taxonomy is deferred; the single motion-vs-composition split is the MVP floor that
  makes a video `disliked` actionable.

## Documentation drift to fix (no real work hiding behind these)

Confirmed during discovery by reading the actual code. Both are doc-only fixes; the
code is ahead of the docs.

- **`packages/visual-generation/README.md` stale status header.** The header reads
  "Phase 2 in progress — data foundation only" and says the CLI / ComfyUI client /
  generate turn "land in later steps," while the body, the root README, and the
  director doc all describe a complete agent (152 tests). Update the header to the
  built state.
- **`packages/visual-generation/README.md` "img2img graphs unbuilt" line.** It says
  refinement "has been added in code — the ComfyUI graphs to back it still need
  building/registering." The refinement *code path* is fully built and wired
  (`comfyui_client.upload_image` → `/upload/image`; `VisualSource` / `--from` /
  `--image` / `--mask` / `--denoise`; `generate.py` source provisioning with denoise
  default + lineage). What remains is a user task (register the img2img/inpaint graph
  on a pod), not missing agent code — reword to that effect.
- **Flux vs. Z-Image-Turbo naming.** The spec and Phase 1/2 handoffs name **Flux.1
  dev** as the stills model, but the actual built/used path ran **Z-Image-Turbo**
  (all the troubleshooting, recipe, and subgraph notes are Z-Image). Reconcile the
  model naming in `docs/ai-director-agent-system.md` and the handoffs so the spec
  matches practice (and note that WAN 2.2 — not Flux — is the confirmed video model).
