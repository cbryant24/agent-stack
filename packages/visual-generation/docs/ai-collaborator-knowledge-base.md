# Visual Agent — Knowledge Base for External AI Collaborators

**What this document is:** a portable snapshot of the `visual-generation` project — an
image/video generation pipeline built on RunPod + ComfyUI — meant to be pasted wholesale into
a Claude.ai or ChatGPT "Project" knowledge section, so an external chat assistant has enough
grounded context to be useful for research, technique discussion, and troubleshooting on this
project, without living inside the `agent-stack` repository itself.

## How to use this document

**You are a second opinion, not the implementer.** The actual implementation work on this
project happens through Claude Code, working directly in the `agent-stack` repository. A
past iteration of this project relied on Claude Code alone, with no outside check on its
technical decisions, and it made some costly mistakes as a result — wasted GPU spend,
generation settings that silently produced bad output, and at least one incident where
important context was missed entirely. Your job here is different: **weigh proposed
approaches against what's documented below, flag disagreements, and ask what's changed if
something doesn't add up** — don't assume a decision described here is correct just because
it's written down. If you're missing context needed to give a real opinion, say so rather than
guessing.

This document favors completeness over brevity deliberately — condensing it down to headline
bullet points would make it useless for actually verifying a technical decision. Expect real
settings, real numbers, real failure modes, not just topic names.

## System overview

The pipeline, end to end:

- **Compute:** a RunPod GPU pod (RTX PRO 6000 Blackwell, 96GB VRAM), created fresh for each
  work session and deleted afterward (pods are disposable — persistent storage lives
  separately, see "Durable ops/infra knowledge" below).
- **Generation engine:** ComfyUI, installed onto the persistent storage volume and started
  manually per pod session (not baked into the pod image — see the ops section for why).
- **Models currently in use:** **Z-Image-Turbo** for still images (a distilled/turbo diffusion
  model — fast, cheap, specific settings requirements, see the technique section), and
  **Wan 2.2** (14B, T2V and I2V modes) for video, run with the `lightx2v` 4-step
  acceleration LoRAs.
- **The `visual-generation` agent** (Python, in the `agent-stack` monorepo) drives this
  pipeline programmatically: `model sync` reads what's actually loaded on the pod,
  `workflow register` captures a ComfyUI graph as a reusable template, `draft`/`generate`
  turn a written spec into an actual generation call, results get tracked in a memory store.
- **Emerging: Ollama as the prompt-generation engine.** As of this document's creation, the
  project is shifting toward using **Ollama (a local LLM runner)** as the primary generator
  of the actual prompts sent to the diffusion models, with the explicit goal of growing and
  improving that prompt-generation approach over time — replacing or supplementing an
  approach that relied more heavily on Claude Code directly crafting prompts. **This is a new
  initiative and its implementation details are not yet established or documented anywhere in
  the `agent-stack` repository** — do not assume specifics about how it's wired up, what
  model it runs, or what its prompting strategy is; ask for current details rather than
  inferring them from this document. When you're asked to help design or critique this Ollama
  prompt-generation approach, treat it as genuinely early-stage.

## Durable technique knowledge

*Distilled from `fidelity-drift-learnings.md`, `z-image-turbo-craft.md`, `canon-guide.md`, `coraline-visual-quality-analysis.md`, and `coraline-prompt-to-image-evidence.md`. This is deliberately dense, not a summary — enough specificity to independently evaluate a proposed fix, not just recognize the topic.*

### The core mental model: two ways to inject identity, and they fail oppositely

| Lever | How identity enters | Dominant signal | Fails toward |
|---|---|---|---|
| **Character LoRA** | fine-tuned weights, triggered by a rare token (`clstwtrss`, `chrsnrtr`) | the token + training data | over/under-application, identity bleed onto other figures, memorized backgrounds |
| **Reference-edit** (img2img / Qwen-Edit) | pixels of a reference image | the reference image | reference attributes override the prompt text |

These are not interchangeable and must not be mixed philosophically. LoRA wants pose/angle variety with a consistent face across many training frames; reference-edit wants few, clean references because the reference dominates everything, including instructions to the contrary.

### Z-Image-Turbo — the locked recipe (proven, repeated)

- `steps: 8, cfg: 1.0, sampler: res_multistep, scheduler: simple, resolution: 1024×1024`
- **`1152×896` stalls/wedges the model** — a hard, repeatable trap. Stay at 1024×1024.
- `cfg≈1` means classifier-free guidance is effectively off — no negative prompt has a control surface (the graph uses `ConditioningZeroOut`). Exclusions must be stated as positive constructions ("blue jeans, no shoes" works; bare "no shoes" alone caused pants to vanish and duplicate shoes to spawn — Technique 14).
- Because cfg≈1 gives the model little steering room, prompt adherence is weaker than a cfg-7 model — staging must be described as subject orientation/state ("rear view", "facing the stage"), not camera-angle math ("rotate 75 degrees" never worked).
- Checkpoint: `z_image_turbo_bf16.safetensors`. Design docs historically said "Flux (stills)" — that's stale; the actually-built and evidence-backed path is Z-Image-Turbo.
- **Status as of 2026-07-15 (Coraline audit):** Z-Image-Turbo is scoped to **ideation only** (thumbnails, style exploration, storyboards) — not the source of truth for recurring production assets. Identity/continuity authority is plate-first (reference packs + approved plates + masked edits), not this model's text-to-image path.

### LoRA training — the single biggest gotcha

A LoRA **trained on Z-Image-Base under-applies on Z-Image-Turbo**: it only registers around strength 2.0+, and at that strength it overrides prompt adherence (pose/staging/background ignored) *and* bleeds identity onto background figures. **Fix: train on Z-Image-Turbo itself, with the Ostris `zimage_turbo_training_adapter` (de-distill adapter) attached during training** — then it applies cleanly near strength 1.0. This is not optional or a minor tuning detail; it's the difference between a usable and unusable LoRA. Recipe that won twice: rank 8 (`linear 8 / alpha 8`, conv 16), LR 5e-5, batch 2, 3000-step cap, checkpoint every 250, `flowmatch` + `adamw8bit`, bf16, qfloat8 quantization + `low_vram`. Trigger tokens carry identity (`clstwtrss`, `chrsnrtr`) — caption the *constant* identity attributes (face/eyes/skin/hair) as nothing (so the token absorbs them) and caption the *variable* ones (pose, wardrobe, setting) explicitly (so they stay promptable and don't fuse into identity).

**Silent QKV load failure is the top LoRA risk**: Z-Image stores fused QKV attention, so a LoRA can appear loaded in the graph but do nothing. Guard: a fixed-seed A/B at strength 0.05 vs 2.0 must look night-and-day different; if identical, it isn't really loading.

### The drift taxonomy — cause → fix for every documented failure mode

- **Style baked in at 4 independent layers** (e.g. a persistent "felt" look that survives prompt edits): (1) LoRA training data/captions, (2) canon locked text, (3) taste-memory priors steering every draft, (4) per-prompt vocabulary. Changing one layer leaves the other three pulling back. **Fix requires attacking all four simultaneously** — retrain, rewrite canon text, add a deterministic style channel that bypasses stale priors, and rewrite the per-prompt block. Lesson: a look you can't prompt away is baked at a layer you aren't editing.
- **Reference dominance** (reference-edit models): text is a weak modifier against the reference image at denoise 1.0. Fix that actually worked: composite the needed attribute *into the reference pixels themselves* (e.g. pre-painting button-eye photos onto a reference image), not into the prompt text. Fewer, cleaner references (2–4) beat a large noisy set.
- **Button eyes** (recurring nemesis): a weak text token loses to a strong "eyes = human/cartoon" prior. What worked: masked eye-only inpaint (denoise ~0.85, mask *only* the glass/socket, never the surrounding frame) or backs-to-camera staging (no faces to resolve). What didn't: chained img2img (degrades every pass), plain text at denoise ≤0.7 (never forms buttons), tiny eye-region inpaints on full-body frames (mangles the whole small face). This is a pixel problem, not a wording problem.
- **Real-photo → puppet conversion — an unsolvable dead end in this pipeline.** There is no working denoise value: high enough to read as a puppet (≥0.7) repaints the face into the model's generic-cute prior (losing likeness); low enough to preserve the real face (≤0.5) keeps human eyes/real skin. img2img restyle preserves *composition*, not *identity*, at high denoise — it's a style tool, not a likeness tool.
- **LoRA over/under-application & stacking:** under-apply is the Base-vs-Turbo training mismatch above. Over-apply/bleed clones the character onto background figures. **Stacking two LoRAs for the same character muddies likeness — pin exactly one LoRA per character, and let canon (not the drafter) own which file+strength represents that character.**
- **Hair color/style drift:** forcing a color change (e.g. brown→black) needs pre-darkening the actual pixels in code *before* a whole-frame img2img pass (denoise ~0.80) — a masked hair-ring inpaint erases the hair mass entirely (0-for-3, retired). Style changes (curl→sleek) need straight-lean language; "loosely wavy" loses to the curl prior.
- **Wardrobe recolor:** same pre-darken-then-whole-frame-img2img pattern as hair; a masked inpaint on a garment color-blocks into a flat gray box because the model can't infer folds from a flat fill.
- **Props degrade under chained local edits** but render correctly in a fresh whole-scene text2img. Fix: re-roll the whole shot fresh and scavenge the good frame — never surgically edit a broken prop repeatedly (12 chained attempts on one controller all failed).
- **Canon "forbid" is a raw substring strip** — it can strip its own canon text (a "no blush" forbid removing "blush" from the locked description itself, or an "ashen" forbid stripping the word out of a "NOT ashen" negation). Use multi-word phrases, never bare short words, and verify the actually-injected prompt after any canon edit.

### Canon — what it is, and critically, what it is NOT

Canon (`visual-generation`'s subject registry) does three things: (1) cast-weaving — names a scene's subjects by alias so the LLM renders them by name/asset id, not by re-describing appearance; (2) deterministic LoRA pinning — every named subject gets its registered LoRA pinned into the spec, with canon's strength value overriding whatever the LLM guessed; (3) an absent-cast advisory when a named subject drops out of the composed prompt.

**As of the 2026-07-15 rewrite, canon is explicitly NOT an identity authority.** The earlier mechanism (locked-descriptor text injection + forbid substring stripping) has been deleted from the code — text descriptors were a prompt macro that raised the probability of broad semantic traits but could not pin geometry, materials, camera, or region assignment. **Identity and set authority are versioned reference images and approved plates (plate-first), not text.** If an external assistant suggests fixing an identity problem by "improving the canon text," that's stale advice from before this architectural correction.

### The architectural root-cause findings (why the current pipeline has a real ceiling)

From the Coraline quality post-mortem, ordered by how much each matters:

1. **Diffusion T2I gives no identity or continuity guarantee, structurally.** A LoRA biases the sampling distribution toward a character but never collapses it to one exact model — pose, framing, seed, and the presence of other subjects all move the sampled identity. Consistency has to be bolted on with extra conditioning (reference images, control maps, or generate-once-then-reuse); none of that exists in the base pipeline. This single fact explains identity drift shot-to-shot, multi-character cross-bleed, wardrobe drift, and set discontinuity.
2. **The base model is a distilled turbo model**, trading away fine detail, prompt adherence (fewer steps + no CFG = weaker steering), and controllability, in exchange for speed.
3. **No spatial/regional/reference conditioning exists anywhere in the pipeline** — no ControlNet (pose/depth/lineart), no IP-Adapter/reference-image identity conditioning, no regional prompting/attention masking, no camera control. This is *why* two LoRAs in one frame paint the whole canvas and bleed into each other — there's no way to say "this region is character A." It's expected behavior given the missing tooling, not a bug fixable by better prompting.
4. **The LoRAs were trained on small (~11 frames), synthetic, single-source data** (a copy of a copy — AI-generated hero images converted through the pipeline again) — too few images and too little viewpoint variety for the model to generalize without drifting, and no true multi-view character sheet of one consistent sculpt.
5. **The model's internal style prior fights the target look** (generic 3D/Pixar-cute, not authentic LAIKA texture), and the project's own canon text ("smooth sculpted clay-resin") accidentally reinforces that CGI-plastic direction rather than the tactile-imperfection look actually wanted.

**The honest ceiling, stated plainly in that post-mortem:** with the current architecture (no reference-image identity conditioning, no regional conditioning, no set-continuity conditioning), the realistic output is nice individual concept-art frames — not a continuous, identity-locked stop-motion film look. No amount of prompt tuning, strength adjustment, or seed sweeping fixes this, because the missing pieces are architectural conditioning surfaces, not prompt quality. **This is the single most important thing an external reviewer should push back on if it isn't being actively addressed**: the fix path researched and prioritized was (1) decide the base model (ControlNet/IP-Adapter ecosystem maturity matters more than raw image quality), (2) add reference-image identity conditioning + retrain on a real multi-view dataset, (3) add regional conditioning for two-shots + depth-conditioned set plates for continuity, (4) re-aim style language toward tactile imperfection. As of the source documents, none of items 1–3 had been implemented — the pipeline was still running the architecturally-limited Turbo + LoRA + text-canon stack.

## Durable ops/infra knowledge

*Distilled from `runpod-setup-context.md`. These are standing facts about the infrastructure, not point-in-time session notes.*

### The Global Volume model

Everything persistent (models, the ComfyUI install itself) lives on a RunPod **Global Volume** (currently named `stably_diffused`), mounted at `/workspace`, referenced via the `IMAGE_NETWORK_VOLUME_ID` env var (the name predates this volume type and is kept for continuity). Key properties:

- **Region-independent** — any datacenter's GPU can mount it; no datacenter lock (unlike the old regional network-volume model this replaced).
- **Elastic** — billed on stored data, nothing to provision or run out of. The old fixed-size "disk quota exceeded" failure class (which caused indirect corruption like 0-byte downloads) does not apply.
- **Backed by object storage via a FUSE layer (`fuse.geesefs`), not local disk** — measured ~181 MB/s cold sequential read. RunPod documents it as poor for frequent writes. Practical consequence: ComfyUI's `output/`/`input/`/`temp/`/`user/` directories and the Python venv are deliberately kept on the pod's *container disk*, never the volume.
- **No real permission model.** Every file reports owner `nobody:nogroup`; an explicit `chown()`/`chmod()` call against a path on this volume fails with `EPERM`. It also doesn't support atomic rename (mkstemp-then-rename), which both `git` and `rsync -a` depend on internally. **Practical rule, load-bearing, not cosmetic:** never run `rsync -a`, `cp -p`/`cp -a`, `mv` (its cross-device fallback still preserves mode), or any explicit `chown`/`chmod` against a path under `/workspace`. Plain `cp -r` (no `-p`) or a fresh `git clone` *into* a path there is fine.
- The pod's *container disk* (150GB, everything outside `/workspace`) is the opposite: **wiped on every stop/terminate.** Nothing meant to persist should live there.

### Why pods are always create/delete, never start/stop

RunPod pins a stopped pod to its original physical host. For this project's GPU (a scarce high-VRAM card), that host's GPUs are almost always already taken by the time you'd resume — `pod start` reliably fails, and a stopped pod can be reclaimed anyway. The tooling therefore always creates a fresh pod (schedulable onto any host with capacity) and deletes it when done, relying entirely on the volume for persistence. Direct consequence: **every new pod pays a "cold load" cost again for every model, the first time it's used on that pod** (see below) — this isn't a one-time setup cost, it recurs on every fresh pod.

### The specific incompatibility to never repeat

A RunPod *template* built on the `runpod/comfyui` image bakes ComfyUI into the image and auto-starts it via an entrypoint script that runs `rsync -a --delete` to sync onto `/workspace` on every boot. `rsync -a` needs `chown`, which this volume rejects (`EPERM`), and the entrypoint runs under `set -e`, so the container crash-loops forever at full GPU cost with zero processes actually running — and critically, the pod's own `desiredStatus` reports `RUNNING` the *entire time*, so a naive status check can't detect it. **Do not deploy any template/image with a baked ComfyUI-sync-on-boot entrypoint against this volume.** ComfyUI is installed as a separate, deliberate step after the pod boots (a plain PyTorch image/template with no such entrypoint), specifically to avoid this class of operation entirely.

### Cold-vs-warm model load times — a real, recurring cost characteristic

Model weights must stream from the Global Volume into VRAM before any compute happens; this is slow the first time a given model is used on a given pod, and fast (VRAM-resident) afterward. Measured: Z-Image-Turbo (~19.5GB combined) — 477s cold vs. 2.03s warm. Wan 2.2 T2V (~34GB combined) — 2339s (~39 min) cold vs. 8.55s warm. **A long stall with 0% GPU utilization right after starting a generation on a fresh pod is expected, not a hang** — it only becomes a real problem if there's genuinely zero compute activity (checkable via `nvidia-smi dmon`) well past when the model's size would predict, or an outright error.

### Two separate pods/volumes exist — don't confuse them

The **inference** pod (`scripts/pod`, this Global Volume, RTX PRO 6000, any datacenter) runs ComfyUI for generation. A separate **training** pod (`scripts/lora-train`, a different, region-locked volume historically named `zimage-lora-factory`, RTX 5090, EU-RO-1) trains character LoRAs via Ostris ai-toolkit. As of the last verification, the training volume's continued existence was **unverified** — confirm before relying on it, the same way the old inference volume turned out to be gone.

## Recent history

A running log of significant sessions, most recent first. Each entry is a condensed version
of a fuller point-in-time record kept in `agent-stack`'s `docs/handoffs/` — see that file for
the full narrative and reasoning if you need more depth than the summary below provides.

**Process note (so this stays current, not a one-off snapshot):** after each significant
session, `agent-stack`'s `CLAUDE.md` now instructs Claude Code to offer writing a dated
point-in-time handoff doc under `docs/handoffs/`. When that happens, fold a condensed version
of it into this section (newest entry on top) and update the copy of this file pasted into
the external chat project. If this section looks stale relative to a conversation you're
having, say so — it means the fold-in step got skipped.

### 2026-09-20 — RunPod Global Volume migration & recovery

The old persistent storage volume was lost: the RunPod account balance hit zero during an
extended absence, and RunPod reclaims an unfunded volume after it sits empty too long
(balance auto-reload is now set up to prevent recurrence). Recovery required rebuilding the
pod/ComfyUI setup against a new **Global Volume** (region-independent, elastic,
object-storage-backed via FUSE — see "Durable ops/infra knowledge" above for what that means
practically) and surfaced several real bugs along the way, all now fixed:

- **Crash-loop incident:** the old default RunPod template baked ComfyUI into the pod image
  and synced it onto the volume via `rsync -a` on every boot; that sync needs to `chown`
  files, which the FUSE-backed Global Volume rejects (no real permission model — every file
  reports owner `nobody:nogroup`, and `chown`/`chmod` fail with `EPERM`). The entrypoint
  script died on that failure and RunPod kept restarting the container, burning GPU cost with
  nothing actually running. Fixed by switching to a plain template with no baked ComfyUI,
  installing ComfyUI separately via a script that avoids ownership-preserving operations
  entirely (plain `cp -r`, never `rsync -a`/`cp -p`/`mv`), and adding a hard guard that
  refuses to even attempt the old known-bad template/image.
- **Health-check fix:** the pod-creation script initially checked a RunPod API field
  (`.runtime`) that turned out not to exist at all in live responses; replaced with a
  confirmed-real field (`uptimeSeconds`) that directly detects a container restart (a
  crash-loop signature) rather than guessing.
- **Cold-vs-warm model load times measured:** loading model weights off the volume into GPU
  memory is slow the *first* time per pod (Z-Image-Turbo ~8 min, Wan 2.2 T2V ~39 min) but fast
  on every subsequent generation once weights are resident in VRAM (2-9 seconds) — expected
  behavior, not a bug, but a real cost factor since pods are always created fresh rather than
  stopped/resumed.
- **Outcome:** both Z-Image-Turbo (stills) and Wan 2.2 T2V (video) confirmed generating
  correctly end to end against the rebuilt volume. Full narrative:
  `docs/handoffs/visual-generation-2026-09-20-runpod-global-volume-handoff.md`.
