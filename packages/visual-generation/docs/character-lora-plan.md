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

### Phase 2 — dataset (narrator first)  ◧ IN PROGRESS 2026-06-29 (machine B)
**Audit done** (59 assets, 3 parallel vision passes). Full results + inventory (in-repo, canonical):
[`character-lora-narrator-audit.md`](character-lora-narrator-audit.md). Curated 12-frame set + caption
sidecars staged in `~/agent-data/visual-generation/lora/narrator/dataset/` (off-git; airdrop-synced).
- [x] **Angle audit vs. how he's shot:** the narrator is **NOT rear-only** — he's shown **front-on, face
      visible** in the interior beats (couch/gaming) and **rear** at the storefront. So front-on identity
      is in scope, and **face reference already exists** (no Celeste-style bootstrap needed for him).
- [x] **Style decision = FELT** (canon). Two of the director's 4 favorites (`a77c6bb1`, `bfed13d5`) are a
      smoother/CGI-ish render and a glossy-photoreal storefront cluster exists — **all excluded** from
      training to avoid a muddy mixed-style LoRA; kept as look-reference only.
- [x] Curated **12** consistent felt frames (6 front/face + 5 rear + 1 rear-¾), deduped, angle-balanced,
      anchored on the felt favorites (`0a25cbb2`, `ce0be66f`).
- [x] **Cropped** the 5 Celeste-in-frame front shots to narrator-only (single-subject LoRA → avoid bleed).
- [x] **Captioned** all 12 (`.txt` sidecars, ai-toolkit convention). Trigger token **`chrsnrtr`**; token absorbs
      constant identity, captions describe the controllable variables (angle / framing / pose / wardrobe / setting).
- [ ] ⚠ **Pose monotony:** fronts are mostly couch-pointing, rears mostly storefront-standing; profile is a
      gap. Risk of overfitting to those two compositions — consider generating 2–3 fresh poses/expressions.
- [ ] **Celeste bootstrap problem (her LoRA, later):** she has ~no good reference yet. Before her LoRA,
      generate a small *consistent* reference set (lock her via canon text, fixed-ish seeds) → curate → train.

### Phase 3 — train  ✅ DONE 2026-07-01 (machine B, RunPod 5090)
- [x] Trained on **Z-Image-Base** (`Tongyi-MAI/Z-Image`) — rank 8, LR 5e-5, **batch 2**, 3000-step cap,
      ai-toolkit on a RunPod **5090**. Picked **step 1500** (identity locked, no overfit); 1000/1250 kept as
      backups. All 6 checkpoints (41 MB each) saved to the **`/mnt` volume** + Mac `~/Downloads/narrator-lora/`.
- [x] Pose-monotony risk did **NOT** materialize — samples in park/beach/kitchen rendered varied/clean
      (flip aug + caption strategy worked). Loss 0.49→0.41 across 1500 steps.
- [x] ⚠ Ran training **directly via CLI** (`python run.py <config>`) because the ai-toolkit UI worker
      queue was wedged. See §Operational gotchas.

### Phase 4 — wire inference  ✅ DONE 2026-07-01
- [x] Uploaded `narrator-zimage_000001500.safetensors` → inference pod `…/ComfyUI/models/loras/` as
      **`narrator-zimage.safetensors`**; `model sync` registered it; set **`"identity_bearing": true`
      manually in `models.json`** (⚠ there is **no CLI** for this — `model sync` only *preserves* the flag).
- [x] **Silent-QKV sanity check PASSED** — strength 0 vs 1.0 clearly differ, so stock `LoraLoaderModelOnly`
      loads the LoRA on Turbo; **the ZiT-loader fallback was NOT needed.**
- [x] ⚠ **Base→Turbo attenuation is real:** the Base-trained LoRA needs **high strength (~2.0)** to express
      on distilled Turbo, and **skin tone under-expresses** (renders pale) — fixed by keeping one skin cue in
      canon (Phase 5). Identity (dreads, button eyes, felt, build) locks in by ~2.0.

### Phase 5 — pin to canon & verify  ✅ DONE 2026-07-01
- [x] `canon edit celeste-you-dangerous "the narrator" --lora narrator-zimage.safetensors:2.0`
- [x] Trimmed locked text to **`"a young Black man, deep caramel-brown felt skin"`** (LoRA carries
      dreads/eyes/felt/build; only skin needs a cue on Turbo). Forbid guards kept. *Original (restore if
      needed):* "a felt-and-clay stop-motion puppet of a young Black man, short and stocky with a compact
      broad-shouldered build and a large head-to-body ratio, deep caramel-brown felt skin, thick full long
      black yarn dreadlocks falling to mid-back".
- [x] Confirmed: bar + portrait renders at strength 2.0 + skin cue → on-model narrator in fresh scenes.
      Wardrobe (hoodie/jeans/AJ1s) is now **per-shot promptable**.

### Phase 6 — repeat for Celeste  ◧ IN PROGRESS 2026-07-02 (dataset staged, training NEXT)
- [x] **Look locked (director-approved, 2026-07-01/02):** the `ed49b68c` bar-frame look — **large
      glossy black four-hole button eyes**, **long straight loose black yarn hair just past the
      shoulders** (explicitly NOT the twin-pigtail braids the first probe batch converged on), **no
      blush**, **always long sleeves**. Canon locked text enriched accordingly + forbids
      (`braid`, `pigtail`, `blush`, `rosy`, `short sleeve`, `short-sleeve`, `bare arms`, `sleeveless`,
      `small button eyes`, `stitched eyelash`, `human eyes`).
- [x] **Bootstrap set generated from canon text alone** (base `visual-workflow`, no LoRA, random
      seeds — cross-seed identity held on canon text, fixed seeds never needed). 2 probe rounds
      (pigtails → straight hair → no-blush) then 10 + 5 + 2 batch shots.
- [x] **15-frame dataset staged** in `~/agent-data/visual-generation/lora/celeste/dataset/` (off-git),
      `.txt` sidecars per narrator convention. Trigger token **`clstwtrss`**. 9 front (incl. close
      portrait, tray, hands-on-hips, seated-with-controller) / 4 ¾+profile / 2 rear; wardrobe split
      waitress vs casual. **Blush handling:** model's felt-doll prior re-adds faint blush under warm
      light and Turbo has no negative slot → kept clean frames where possible and **captioned the
      blush where visible** so it stays promptable instead of fusing into identity.
- [x] Edits: couch frame cropped to Celeste-only (photobomb figure removed); rear-bar frame
      pixel-patched (model stitched 2 buttons into the back of her hair).
- **Staging lessons (save for future casts):** "seen from behind" prompts LOSE to the face-forward
  prior (0/3) — rear views need **scene-motivated staging** ("standing at the window looking out",
  "watching the wall TV from across the room": 2/2). Strict profiles come out ¾ but that's usable.
  **Cool TV-glow rim light broke a button eye into a cartoon eye** — keep profiles warm-lit.
  When the Anthropic API is unavailable, specs can be **hand-cloned in the batch file** (copy a
  proven vg-spec JSON + prompt, new UUID) and `generate` runs fine — only `draft` needs the LLM.
- [x] **Trained 2026-07-02** — fully CLI-driven via the new `scripts/lora-train` (no ai-toolkit UI:
      config = `docs/celeste-zimage.yaml`, hand-derived from the committed `docs/narrator-zimage.yaml`).
      Same recipe (Z-Image-Base, rank 8, LR 5e-5, batch 2), RunPod 5090 EU-RO-1. Run was cut at step
      ~1596/3000 by an accidental pod deletion — **harmless**: checkpoints save every 250 straight to
      `/mnt/output` (the lora-train default), so 250–1500 all survived. **Step-1500 samples show locked
      identity** (park/portrait/beach-rear/kitchen, wardrobe promptable, felt intact) — same winning
      step as the narrator. All 6 checkpoints on Mac `~/Downloads/celeste-zimage-lora/` + `/mnt`.
      Identity was already resolving at step 1250; step-250 samples were still generic (expected).
- [x] **Wired + pinned 2026-07-02:** step-1500 checkpoint uploaded to the pod volume as
      `celeste-zimage.safetensors` (NOTE: ComfyUI lives at `/workspace/runpod-slim/ComfyUI/` on the
      gen-usne1 network volume — that's why models survive pod cycles), `model sync`'d, manual
      `identity_bearing: true`. **QKV sanity PASSED** (fixed-seed A/B, strength 0.05 vs 2.0 —
      night-and-day). Pinned `celeste-zimage.safetensors:2.0`; locked text trimmed to
      `"a young woman with pale cream felt skin, plain uncolored felt cheeks with no blush"`
      (the blush cue must stay — it re-emerges without it, her analog of the narrator's skin cue).
      *Original locked text (restore if needed):* "a felt-and-clay stop-motion puppet of a young
      woman, pale cream felt skin, plain uncolored pale cream felt cheeks matching the rest of her
      face, long straight black yarn hair hanging down just past her shoulders, large glossy black
      four-hole sewing-button eyes with visible thread holes, thin stitched black eyebrows, small
      round felt nose, bare felt face with no makeup".
- [ ] Final cosmetic verification render (spec `571b47a0` drafted, awaiting a pod).
- [ ] **Two-LoRA interior shot** — template UNBLOCKED 2026-07-02: single-slot `visual-workflow-lora`
      silently drops the 2nd LoRA (advisory only); built + registered **`visual-workflow-lora2`**
      (`workflows/z-image-turbo-lora2-api.json`, chained LoraLoaderModelOnly → `lora_0`+`lora_1`
      slots; `slot_inference` maps multi-LoRA automatically, node-id order). First two-shot spec
      `83b7e5e5` drafted (both LoRAs @2.0, spatial-separation prompt), awaiting a pod. Watch for
      identity bleed; strengths may need lowering when stacked.

### Operational gotchas (RunPod / ai-toolkit) — learned 2026-07-01, save the next run
- **Point outputs at the persistent volume.** ai-toolkit defaults to `/app/ai-toolkit/output` (container
  disk) which is **wiped when the pod cycles**. We nearly lost the checkpoints; recovered only because we'd
  `cp`'d them to `/mnt`. Next time: set `training_folder` to `/mnt/output`, or `cp … /mnt/` right after each save.
- **RunPod DNS is often broken on boot** (`Temporary failure in name resolution`) → model downloads fail with
  a misleading `httpx` "client has been closed" error. Fix: `printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf`.
- **ai-toolkit UI worker queue can wedge** (job stuck "queued", never runs). Bypass: write the config to YAML
  (pull it from the UI's own `/api/jobs` → `job_config`) and run `python run.py <yaml>` directly; set
  `logging.use_ui_logger: false`. The UI Queue row stays "queued" but the CLI run is real; samples still land
  in the output dir.
- **`scp` needs the direct-TCP SSH** (`root@<ip> -p <port>`), NOT the `ssh.runpod.io` proxy (no SFTP subsystem).
  Use `-P` (capital) for port; add `-O` if "subsystem request failed".
- **Sample images via API:** `GET /api/jobs/{id}/samples` lists paths; fetch bytes with
  `GET /api/img/<url-encoded-absolute-path>` (Bearer `AI_TOOLKIT_AUTH`).
- **Terminating a pod ≠ stop/start** — a new pod ID means a fresh container disk; only `/mnt` (network volume)
  survives, and it's region-locked + single-attach (can't be on two pods at once → relay via your Mac).

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
# Training run, end to end (scripts/lora-train encodes the §Operational gotchas):
lora-train up && lora-train dns
lora-train push ~/agent-data/visual-generation/lora/celeste/dataset
# create the job in the ai-toolkit UI (URL from `lora-train status`), then:
lora-train config celeste-zimage && lora-train train celeste-zimage
lora-train log celeste-zimage
lora-train pull celeste-zimage && lora-train down

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
