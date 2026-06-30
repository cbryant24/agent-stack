# Character LoRA plan — narrator & Celeste (Z-Image)

**Status:** planned, not started. **Written:** 2026-06-29 (machine A).
**Picks up on:** another MacBook / another Claude Code instance — read this top to bottom first.
**Project:** `celeste-you-dangerous`. **Image model:** `z_image_turbo_bf16.safetensors` (Z-Image-Turbo).

This plan extends [`canon-guide.md`](canon-guide.md) (canon `--lora` is the integration point) and
the draft/redraft mechanics in [`draft_redraft_analysis.md`](draft_redraft_analysis.md). The
motivation: per-shot prompt churn is high; recurring cast (narrator, Celeste) drift in appearance
and bloat every prompt with long locked descriptors. Character LoRAs move identity to the model
level — consistent look, much leaner prompts.

---

## 1. TL;DR / verdict

- **Feasible today — this is a "go."** Ostris **ai-toolkit** has first-class Z-Image training; a
  non-distilled **Z-Image-Base** checkpoint shipped 2026-01-28 to train against; a 24 GB RunPod
  4090 is the right rental.
- **Do character LoRAs for the narrator and Celeste. Do NOT do place LoRAs** for the bar
  interior/exterior — canon *text* already renders the sets well, and stacking place + character
  LoRAs at 8 steps invites dilution/identity-bleed.
- **LoRAs fix _identity_, not _placement_.** A LoRA makes the narrator reliably *look* like himself
  and lets you drop his descriptor from the prompt. It does **not** stage the shot — "narrator at
  the door," "Celeste + narrator inside," TV position, etc. stay a prompting/blocking job.
- **Biggest blocker is not training — it's two integration gaps:** (a) **no z-image template has a
  LoRA loader slot** (confirmed, §4 Phase 1), and (b) a **silent ComfyUI LoRA-load failure** from
  Z-Image's fused-QKV key layout (§3). Both have known fixes below.

---

## 2. What a LoRA will / won't change

| Will | Won't |
|---|---|
| Lock the narrator's / Celeste's appearance at the model level across every shot | Place the figure or props in the frame (still prompt-driven) |
| Let you **drop the long locked descriptor** from prompts (kills the bloat we fixed half of in `canon.py`) | Fix the TVs-mount-high prior or other composition issues |
| Make the **two-character interior** scene (narrator + Celeste together) tractable | Remove iteration entirely — each iteration just gets cheaper/leaner |

---

## 3. Key technical facts (from research, 2026-06-29)

- **Architecture:** Z-Image = 6B single-stream DiT ("S3-DiT"), **Lumina2 family**. Text encoder
  **Qwen-3-4B** (`qwen_3_4b.safetensors`), VAE `ae.safetensors`, diffusion weights
  `z_image_turbo_bf16.safetensors`. It loads in ComfyUI via a **diffusion-model loader (+ separate
  text-encoder + VAE)** — NOT a checkpoint loader. (Our `visual-workflow` slot map confirms this: it
  has a `unet` slot, no `ckpt`.)
- **Turbo vs Base:** Turbo is **few-step distilled** (8 steps, CFG≈1, no negative). **Z-Image-Base**
  (non-distilled, ~30–50 steps, CFG 3–5) released **2026-01-28** and is Tongyi's recommended
  fine-tuning foundation.
- **Train-on-base vs train-on-turbo (the crux):**
  1. **Preferred: train the LoRA on Z-Image-Base, run inference on Turbo.** Cleanest; best stylistic
     range for a stop-motion look.
  2. **Or train on Turbo + Ostris `zimage_turbo_training_adapter`** (a de-distill LoRA you attach
     during training and *remove* at inference, keeping 8-step speed). Good for short character runs;
     "distillation still breaks down over long runs."
  3. Avoid naively training directly on Turbo with no mitigation — degrades the few-step speedup
     and/or yields unstable identity.
- **Trainer:** **Ostris ai-toolkit** is the mature/reference path (kohya/OneTrainer/SimpleTuner/
  diffusion-pipe: no verified Z-Image support yet).
- **ComfyUI LoRA load:** apply with **`LoraLoaderModelOnly`** (LoRA patches the DiT, not Qwen),
  inserted between the diffusion-model loader and the sampler. **GOTCHA:** Z-Image stores attention
  as a **fused QKV** matrix while many trainers export separate `to_q/to_k/to_v` → the **stock loader
  can fail _silently_** (base-model output, no error). Fix: ai-toolkit's ComfyUI-aware export and/or
  the **`Comfyui-ZiT-Lora-loader`** node; always sanity-check that LoRA strength visibly changes
  output.
- **Training spec (character identity LoRA):** ~**9–15 consistent 1024px images**; rare trigger
  token + captions that *also* name the stop-motion/felt style; **rank 8** (sweep 4/8/16);
  **~2–3k steps**, LR **1e-4→5e-5**, batch 1–2, sample every ~250 steps; **24 GB VRAM comfortable**
  (down to 12 GB possible); ~**1–2 h** on a 4090/5090.
- **Stylized gotchas:** style bleed / identity-vs-style collapse is the main failure; put the puppet
  style in captions; keep the felt/material/lighting look consistent across the set; sample on fixed
  seeds to confirm identity holds without collapsing style.

---

## 4. Build plan (phased)

### Phase 0 — decisions before spending anything
- [ ] **Training target:** Z-Image-Base (preferred) vs Turbo+adapter. Default to **Base** unless we
      must keep 8-step inference *during* training iteration.
- [ ] **Order:** narrator first (most reference, most shots), Celeste second.
- [ ] Confirm RunPod budget for a ~1–2 h 24 GB training run (separate from the inference pod).

### Phase 1 — make a LoRA-capable z-image template  ✅ DONE 2026-06-29 (machine B)
Confirmed: `visual-workflow`, `visual-workflow-inpaint`, `visual-workflow-img2img` had **no LoRA
slot**. Mechanics that mattered (from source):
- `graph_build.py:110-111` writes each `spec.lora_stack[i].name` into a template slot named
  **`lora_{i}`** (so `lora_0`, `lora_1`, …). No such slot ⇒ the LoRA is collected as advisory and
  **never applied**. `draft.py` also warns when `lora_stack` is set but no `lora_`-prefixed slot
  exists.
- **Correction to the original worry:** `slot_inference.infer_slots` **already** maps `lora_0` →
  `lora_name` for `LoraLoader`/`LoraLoaderModelOnly` nodes — no manual slot declaration needed.
- **Strength resolved (was the real gap):** only the LoRA **name** was mapped; `LoraRef.strength`
  (e.g. canon's `narrator-zimage:0.9`) was silently dropped. Fixed by extending **both**
  `graph_build` (writes `lora_{i}_strength`) **and** `slot_inference` (infers `lora_{i}_strength` →
  the loader's `strength_model`), backward-compatible (older templates lack the slot ⇒ advisory).
  Chosen over hardcoding so canon's per-character strength actually applies and the Phase-4
  strength-0-vs-1 sanity check is a one-value change.

Steps:
- [x] Built the **Z-Image-Turbo** LoRA graph from the registered `visual-workflow` base (UNET loader +
      Qwen-3-4B + VAE) with a **`LoraLoaderModelOnly`** (node `30:48`) inserted between the UNET loader
      (`30:46`) and `ModelSamplingAuraFlow` (`30:47`). Saved API-format JSON.
- [x] Committed to `packages/visual-generation/workflows/z-image-turbo-lora-api.json`.
- [x] Registered as **`visual-workflow-lora`** (12 slots incl. `lora_0` + `lora_0_strength`). Verified
      end-to-end: a `LoraRef(name, strength)` lands name + strength on node `30:48`, nothing unmapped.
      Placeholder `lora_name = narrator-zimage.safetensors` (overwritten by the `lora_0` slot at draft
      time; shows as a "missing model" advisory until Phase 3/4 trains it).
- [ ] (Optional but recommended) also make an img2img/inpaint LoRA variant if cast LoRAs are needed in
      refinement passes. **Deferred.**

### Phase 2 — dataset (narrator first)
- [ ] Curate **9–15** of the most *consistent* narrator frames from `~/agent-data/visual-generation/
      assets/celeste-you-dangerous/` (LIKED/★4 gens). Diverse angle/framing, **consistent** felt look,
      hair length, build. Inconsistency here bakes drift into the LoRA.
- [ ] Upscale/clean to 1024px as needed.
- [ ] Caption each: a **rare trigger token** (e.g. `chrsnrtr`) + the stop-motion/felt style + pose.
- [ ] **Celeste bootstrap problem:** she has ~no good reference yet. Before her LoRA, generate a
      small *consistent* reference set (lock her via canon text, fixed-ish seeds) → curate → then train.

### Phase 3 — train (Ostris ai-toolkit on RunPod 24 GB)
- [ ] Spin a **24 GB (4090)** RunPod pod with ai-toolkit. Pull **Z-Image-Base** (or Turbo +
      `zimage_turbo_training_adapter`).
- [ ] Config: rank 8, ~3k steps, LR 5e-5 (tight identity), batch 1–2, sample every ~250 steps on a
      fixed seed. Watch for overfitting / style collapse.
- [ ] Output: `narrator-zimage.safetensors`. **Download and keep it** (it does NOT live in git — see §5).

### Phase 4 — wire inference
- [ ] Upload `narrator-zimage.safetensors` to the inference pod's `models/loras/`.
- [ ] `agent visual-generation model sync --endpoint <url>` to register it; **mark it
      identity-bearing** in the registry (the flag canon's LoRA-pin relies on — see model registry).
- [ ] **Sanity-check the silent-load gotcha:** render with LoRA strength 0 vs 1.0 — output MUST
      change. If not, switch the template's loader to **`Comfyui-ZiT-Lora-loader`** (install the node
      on the pod) and re-register, or re-export from ai-toolkit in ComfyUI-aware format.

### Phase 5 — pin to canon & verify the payoff
- [ ] `agent visual-generation canon edit celeste-you-dangerous "the narrator" --lora
      narrator-zimage:0.9` (tune strength).
- [ ] **Trim the narrator's locked text** once the LoRA carries identity — keep only what the LoRA
      can't (e.g. wardrobe is per-shot anyway). Goal: prompts stop carrying the full descriptor.
- [ ] Draft a test shot using `--template visual-workflow-lora`; confirm the `── Canon enforced ──`
      block pins the LoRA, the descriptor is lean, and the render still *is* the narrator.

### Phase 6 — repeat for Celeste
- [ ] After her reference set exists (Phase 2 bootstrap), repeat 3–5.
- [ ] **Two-LoRA interior shot:** narrator + Celeste in one frame can bleed identities — plan on
      regional prompting / deliberate posing, and test strengths together.

---

## 5. Cross-machine setup (co-located; shared files + shared Qdrant via Tailscale)

Reality for this project: the second MacBook is **physically here**, can receive **all non-git
files** (airdrop/move), and reaches the **same Qdrant database over Tailscale**. The RunPod ComfyUI
pod is a public proxy URL reachable from either machine. So there is **no "rebuild state from a
recipe"** — state is *shared*. The only thing genuinely new on the other machine is the **Claude Code
workspace** (no memory of this session — which is exactly why this doc exists).

| Piece | How it's shared | One-time setup on the other MacBook |
|---|---|---|
| Repo code + this doc + workflow JSON | git (`git pull`) — or airdrop the working tree | pull/clone; include the uncommitted `canon.py` dedup fix if not yet pushed |
| **Qdrant** — the `visual-workflow-lora` registration **and all memory collections** | **shared live over Tailscale** (single DB) | set `QDRANT_URL=http://<tailscale-host>:6333` in `.env`. **No re-`workflow register`** — same DB |
| `~/agent-data/visual-generation/` (canon JSON, `models.json`, assets, batches) | airdrop/move (or a shared mount) | drop into `~/agent-data/visual-generation/` |
| Trained **`.safetensors`** | airdrop/move | place locally + upload to the pod's `models/loras/` |
| API keys | `.env` (`op://` refs) + 1Password | install/auth the `op` CLI, same `.env`; `op run …` wraps API commands |
| Inference pod | public RunPod proxy URL | pass the same `--endpoint <url>` |

**Concurrency — the one rule:** drive the project from **one machine at a time.** Qdrant is shared
*live*, so simultaneous writes race; and if `agent-data` is **copied** (not on a shared mount) the
canon/`models.json` files can **diverge** — re-airdrop after edits, or keep `agent-data` on one shared
location so there's a single source of truth. (If instead each machine ran its *own* Qdrant you'd also
copy the Qdrant storage volume — but the Tailscale-shared single DB is simpler and what's in use.)

**Net:** because both the files and the DB are shared, you can **train and build on either machine**
and the other just picks up — set `QDRANT_URL`, place `agent-data`, point at the same pod, and read
this doc. Train the weights once; both machines consume the one `.safetensors`.

---

## 6. Open decisions / risks
- **Base vs Turbo training target** — pick in Phase 0.
- ~~**LoRA strength not slot-mapped**~~ — ✅ resolved in Phase 1: extended `graph_build` +
  `slot_inference` to carry `lora_{i}_strength` → loader `strength_model`.
- **Silent QKV load failure** — the top risk; mitigated by the strength-0-vs-1 sanity check + ZiT
  loader fallback.
- **Celeste data bootstrap** — she needs a consistent reference set generated first.
- **Identity-bearing flag mechanism** — confirm exactly how `model sync`/registry marks a LoRA
  identity-bearing (canon's pin depends on it).

---

## 7. Sources
- Z-Image-Turbo / S3-DiT — https://comfyui-wiki.com/en/news/2025-11-27-alibaba-z-image-turbo-release
- Z-Image-Base release (2026-01-28) — https://comfyui-wiki.com/en/news/2026-01-28-alibaba-z-image-base-release
- Tongyi-MAI/Z-Image-Turbo (HF) — https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- Official ComfyUI Z-Image-Turbo workflow (loaders, filenames) — https://docs.comfy.org/tutorials/image/z-image/z-image-turbo
- Training a LoRA for Z-Image Turbo with ai-toolkit — https://huggingface.co/blog/content-and-code/training-a-lora-for-z-image-turbo
- ostris/zimage_turbo_training_adapter — https://huggingface.co/ostris/zimage_turbo_training_adapter
- ai-toolkit 12GB training — https://github.com/ostris/ai-toolkit/issues/550
- Turbo vs De-Turbo training — https://www.runcomfy.com/trainer/ai-toolkit/z-image-turbo-lora-training
- Comfyui-ZiT-Lora-loader (fused-QKV fix) — https://github.com/capitan01R/Comfyui-ZiT-Lora-loader
- LoraLoaderModelOnly — https://comfyui-wiki.com/en/comfyui-nodes/loaders/lora-loader-model-only
- RunPod training walkthrough — https://dev.to/promptingpixels/train-a-custom-z-image-turbo-lora-with-the-ostris-ai-toolkit-runpod-edition-1n4h

---

## 8. Command quick-reference
```bash
# Register the LoRA-capable template (after committing the graph JSON)
agent visual-generation workflow register workflows/z-image-turbo-lora-api.json --name visual-workflow-lora

# Register the trained LoRA from the pod (then mark identity-bearing in the registry)
agent visual-generation model sync --endpoint <comfyui-url>

# Pin the LoRA to the character canon
agent visual-generation canon edit celeste-you-dangerous "the narrator" --lora narrator-zimage:0.9

# Draft using the LoRA template (descriptor should now be lean)
agent visual-generation draft --project celeste-you-dangerous --scene "Arrival" \
  --template visual-workflow-lora --canon "the storefront" --points "..."
```
