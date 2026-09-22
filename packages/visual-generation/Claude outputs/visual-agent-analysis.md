# Visual Agent — Retrospective Analysis

**Scope:** what the project set out to achieve, the technology stack across iterations, why the previous architecture was scrapped, and why the current iteration has stalled short of its goal.

**Date of this write-up:** 2026-09-22

---

## The goal

A Coraline-style stop-motion short film built end-to-end through a generative pipeline: two puppet characters (Celeste with button eyes and a voluminous curly bun; a narrator with mid-back dreadlocks) rendered consistently across an eight-shot still sequence, then extended into video via first/last-frame interpolation.

Consistency is the whole ballgame — *"same puppet, same set, every shot"* — and success has always required identity that survives changes of pose, camera, and set, plus geometry that survives edits and compositions.

Around this, an agent (`packages/visual-generation` in the `agent-stack` monorepo) was meant to industrialize the loop as **`draft → generate → report`**:

- a Python/Click CLI drafting specs into batch files
- resolving them against a registered ComfyUI workflow template and local model registry
- dispatching to ComfyUI on a RunPod pod
- recording each run into a Qdrant memory collection (`visual_generation_memory`)

…so lineage, corrections and lessons accumulated instead of being lost.

---

## The tech stack, both iterations

### Generation runtime

- **ComfyUI on RunPod**
  - Bake-off: H100 SXM 80 GB
  - Previously RTX PRO 6000 (until US-NE-1 exhausted them)
- **Storage:** network volumes — `gen-usne1` for production, `qwen-eval` for the bake-off
- **Agent side:** Python CLI dispatching workflow API JSON over HTTP
- **Secrets:** 1Password, injected via `op run` — no literal keys touch the code path

### Models tried

| Model | Role | Notes |
|---|---|---|
| Z-Image-Turbo | t2i (stills) | Locked recipe: `steps 8 / cfg 1 / res_multistep / 1024²`; the built stills path |
| FLUX / SDXL | t2i (stills) | Alternate stills paths |
| Character LoRAs via ai-toolkit | Identity injection | Trigger tokens `clstwtrss`, `chrsnrtr`; trained on Z-Image-Turbo + Ostris adapter |
| Qwen-Image-Edit 2511 bf16 | Reference-edit | 3-image conditioning via `TextEncodeQwenImageEditPlus`; current lead |
| FLUX.1 Kontext dev bf16 | Reference-edit | Bake-off contender; one one-stage attempt on file |
| InstantX Qwen ControlNet-Union + Depth Anything V2 | Depth/edge arm | Installed, never executed |
| WAN 2.2 T2V / FLF2V | Video | Manually verified in ComfyUI on the pod; no CLI integration yet |

---

## The previous iteration — what it was and why it failed

The prior architecture leaned on **long prompt assembly + a code-enforced canon layer + two globally-applied character LoRAs + unconstrained fresh t2i**.

- Identity was supposed to come from LoRA trigger tokens.
- Set continuity from repeatable prompt phrasing.
- Character separation from stacking a Celeste LoRA and a narrator LoRA in the same run.

Three independent LLM audits (Claude, ChatGPT, Gemini), consolidated into `Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md`, delivered a **NO-GO on that architecture**. The failure was diagnosed as architectural, not prompt-craft:

### 1. Text canon cannot enforce geometry
Words like "button eyes" lose to the model's prior every time. Identity has to enter as **pixels** (mask, composite, or a reference image), never as description. Every attempt to fix identity with prompt engineering hit a token-vs-prior wall.

### 2. Dual global LoRAs cannot isolate characters
- At usable strength they **cross-contaminate** — background extras clone the character.
- At the safer strength range they **under-apply**.
- Stacking two same-character LoRAs muddied likeness further.

### 3. Fresh t2i cannot preserve a specific set
Whole-scene regeneration re-invents geometry every shot. There is no source of truth for "the same sports bar" other than the pixels of an approved plate.

### 4. Blind forbid-stripping was actively harmful
The canon layer's raw-substring forbid system would strip its own locked text (e.g. a "no blush" forbid removing "blush" from the locked description), silently mangling prompts.

### 5. The v2 Celeste LoRA was never actually validated
The strongest-looking evidence turned out to be **training inputs**, not outputs. Genuine outputs were waxy, drifted identity, and painted blush the design forbade.

### 6. Real-photo → puppet restyle had no viable denoise
- ≥0.7 repainted her face into a generic Pixar-child prior (losing likeness and buttons)
- ≤0.5 kept human eyes and real skin

Attempts to bootstrap the LoRA from converted real photos would have poisoned the dataset.

### 7. Cost discipline was not enforced
Pod uptime through review, seed sweeps and dual-LoRA regenerations burned budget on structurally doomed spend.

### Phase 0 cleanup — still pending

The corrective plan calls for:

- halt the dual-LoRA path
- stop retraining on the current dataset
- delete forbid-strip and locked-text injection
- kill full eight-shot regenerations
- never leave the pod running during review

That code cleanup is planned and approved (`~/.claude/plans/goal-retrospective-analysis-warm-peach.md`) but **not yet executed** — a separate track from the bake-off.

---

## The current iteration — what changed and where it stands

The rebuild is around **persistent canonical assets and constrained image transformation**:

- one approved hero per character
- one master plate per set with derived framings
- **sequential single-character edits** instead of dual-LoRA co-generation
- AI models used as controlled editors rather than as authority for identity or camera

Phase 3A — the **editor bake-off** — picks the editing stack (Qwen-Image-Edit 2511 vs FLUX.1 Kontext dev, plus a depth/edge arm) that will run the downstream proof phases.

### What has been validated

A **two-stage decomposition** recipe on Qwen-Image-Edit 2511:

1. **Convert-in-pose** — profile source → profile puppet, no invented geometry
2. **Re-stage** — turn to front as its own edit
3. **Refine** — name object *construction*, not category ("four thread holes, like Coraline's button eyes" beat two prior button-eye failures)

This produced `celeste_hero_draft_v1` (attempt 9), the first cleanly-banked hero the project has ever produced.

**The strategic insight is now the load-bearing pipeline principle:** any edit asking for view synthesis and style conversion in a single pass will invent the missing geometry from the model's doll prior.

### Why it stalled again

Everything downstream of v1 exposed the same root cause in a new form: **the source photos are all profile / near-profile in dim bar lighting**.

- The **resolution pass** on v1 (attempt 10 = v2 candidate) cleared criterion 9 (1088×1272 vs the 944×1104 floor) but regressed on face structure (longer, flatter, less like her), skin (cooled from warm peach-ivory to pale cream) and eyebrows (lost) — the stage-2 turn is *inventing* a front view every time it runs, and each invention diverges.
- **Hair-fix attempts 11–13** then drifted the near-black curly bun to a light-brown braided ponytail. Three strikes closed the hair track.
- Every downstream refinement re-invents what stage 2 invents, so **refinement compounds error instead of reducing it**.

### Also open

- Sheet-1 was **never formally scored**
- Sheet-2 Tests A / B1 / B2 / D **never ran**
- FLUX.1 Kontext has **exactly one one-stage attempt** on file — no two-stage try, so no fair comparison to Qwen
- The **depth/edge arm never executed**
- Cost **drifted past the $10 cap** on day 1 and was flagged late, reinforcing the rule that pod-session reports must reconcile actual spend against cap at close

---

## Why we failed to produce the intended result

Reduced to one line:

> **At every iteration, the load-bearing signal was upstream of where we were trying to fix it.**

- **Previous iteration:** fixing identity in the prompt when identity had to be in the pixels; fixing character separation with LoRA strength when it needed architectural separation (sequential, masked, single-character edits).
- **Current iteration:** fixing hero identity with recipe changes when the recipe is now correct — the failure is that the **inputs** to that recipe don't contain the geometry the model needs to preserve, so the model invents it and every attempt at refinement chases an invention that won't converge.

The durable fix is on the queue and **it isn't a pod experiment**: a controlled Celeste photo shoot in even diffuse light (front, three-quarter, profile). Nothing downstream — Sheet-1 gate, Sheet-2 tests, narrator hero, depth arm, video — usefully advances until those exist, and every paid experiment run before they exist would answer a question we've already answered three ways.
