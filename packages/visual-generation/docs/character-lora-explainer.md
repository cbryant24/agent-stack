# Character LoRA — plain-English explainer

> **PROVENANCE (2026-07-15, audit §1):** the training dataset for these LoRAs =
> agent-generated synthetic frames (the gen-ids in the dataset filenames are the agent's own
> prior generation records). Any image shown or referenced in this doc is a training INPUT
> unless a generation id proves it is an output. A LoRA trained on this material encodes a
> character class, not a locked puppet identity (audit §7).

Written 2026-07-01 to demystify the terms, models, and settings from the narrator-LoRA session.
Companion to [`character-lora-plan.md`](character-lora-plan.md) (the phased plan) and
[`character-lora-narrator-audit.md`](character-lora-narrator-audit.md) (the dataset audit).

---

## 1. What are we actually accomplishing?

Your film has recurring characters (the **narrator**, **Celeste**). Every time you generate a shot,
you have to re-describe them in the prompt ("felt-and-clay puppet, caramel-brown skin, dreadlocks to
mid-back…"), and they still **drift** — the face/build changes shot to shot.

A **character LoRA** fixes this. It's a small add-on file we *train* on ~12 pictures of the narrator.
Once trained, we load it on top of the image model and just write **`chrsnrtr`** in the prompt — the
model then reliably renders *him*, consistently, without the long description. 

**What it fixes:** his identity (face, skin, hair, build) is locked at the model level.
**What it does NOT fix:** where he stands, what he's doing, camera angle — that's still your prompt's job.

Think of it as: the base model is a versatile actor; the LoRA is teaching that actor to *become one
specific character* on command.

---

## 2. The models (what generates the image)

| Term | What it is |
|---|---|
| **Z-Image** | The base AI image model we use (a 6-billion-parameter model from Alibaba/Tongyi). "Non-distilled" = full quality, slower. **We train the LoRA on this.** |
| **Z-Image-Turbo** | A "distilled" (sped-up) version of Z-Image that makes an image in ~8 fast steps instead of ~30. **We use this for actual production generation** — a LoRA trained on Base still works on Turbo. |
| **De-Turbo / L2P / Turbo+Adapter** | Other Z-Image training-target flavors in the ai-toolkit menu. We didn't use them; plain **Z-Image (Base)** was the cleanest choice. |
| **Distilled** | A model compressed to run in fewer steps (faster) at some cost to flexibility. Turbo is distilled; Base is not. Training works better on non-distilled. |
| **Text encoder (Qwen-3-4B)** | Turns your written prompt into numbers the image model understands. |
| **VAE** | Translates between real images and the compressed "latent" form the model actually works in. |
| **Diffusion / DiT** | The model type. It generates an image by starting from noise and repeatedly "denoising" toward the prompt. DiT = "Diffusion Transformer," Z-Image's architecture. |
| **ComfyUI** | The app that *runs generation* on a GPU (our production/"inference" side). It builds image pipelines as connected "nodes." |
| **ai-toolkit (Ostris)** | The app that *trains LoRAs* (what we're using on the RunPod pod right now). |

**The flow:** train LoRA on **Z-Image (Base)** with ai-toolkit → use the LoRA on **Z-Image-Turbo** in
ComfyUI for fast shots → pin it to the narrator's "canon" so it auto-applies.

---

## 3. LoRA training terms & the settings we chose

Each row: what it means, what we set, and why.

| Setting | Plain meaning | Ours | Why |
|---|---|---|---|
| **LoRA** | "Low-Rank Adaptation" — small learned add-on weights that adapt a big model to a new concept without retraining the whole thing. Output is a small `.safetensors` file. | — | The whole point. |
| **Linear Rank** | The LoRA's *capacity* — how much it can learn. Higher = more detail but bigger, slower, and overfits more easily. | **8** | Plenty for one character's identity; low rank resists overfitting. |
| **Alpha** (`linear_alpha`) | A scaling knob for how strongly the LoRA's learning is applied. Commonly set equal to rank. | **8** | 1:1 with rank = standard, stable. |
| **Learning Rate (LR)** | How big each learning adjustment is. Too high → unstable; too low → slow/weak. | **5e-5** (0.00005) | A careful, "tight" rate — locks identity cleanly without frying it. |
| **Steps** | Number of training iterations (each processes one batch). | **3000 cap** | Upper bound. With only 12 images this is *a lot*, so we pick an **early** checkpoint (see Overfitting). |
| **Batch Size** | Images processed per step. Bigger = smoother/faster but more GPU memory. | **2** | The 5090's 32 GB can handle it. |
| **Epoch** | One full pass through the dataset. (12 imgs ×2 with flip = 24, ÷ batch 2 = 12 steps/epoch.) | — | 3000 steps ≈ 250 epochs — why overfitting is the main risk. |
| **Optimizer (AdamW8bit)** | The algorithm that decides how to adjust weights each step. "8bit" = a memory-saving version. | AdamW8bit | Standard, VRAM-friendly. |
| **Gradient Accumulation** | Fake a bigger batch by summing several steps before updating. | **1** (off) | Not needed; batch 2 is enough. |
| **Gradient Checkpointing** | Trades a little speed for much less VRAM (recomputes instead of storing). | **On** | Keeps memory in budget. |
| **Quantize (float8)** | Store the big *base* model in 8-bit precision during training to fit VRAM. The LoRA itself still trains at higher precision. | **float8** | Lets a 6B model + batch 2 fit; negligible quality cost. |
| **Flow Match / Timestep type / Noise scheduler** | The math recipe Z-Image uses to go noise → image. "Timestep type: weighted" tweaks which noise levels it practices on. | model defaults | Selecting the Z-Image architecture sets these correctly — leave them. |
| **EMA** | "Exponential Moving Average" — averages weights over time for smoother results. | **Off** | Simpler for a first run. |

### Dataset / captioning terms

| Term | Meaning | Ours |
|---|---|---|
| **Trigger word** | The rare token that "names" the character. Put it in a prompt to summon the LoRA. | **`chrsnrtr`** |
| **Caption** | Text describing each training image (a `.txt` next to each `.png`). Best practice: describe the things that **vary** (pose, angle, wardrobe, setting) and let the trigger absorb the **constant** identity. | 1 per image |
| **Caption Dropout** | Randomly ignore the caption a small % of the time so the model doesn't over-rely on exact words. | **0.05** (5%) |
| **Flip X (augmentation)** | Mirror images left-right to effectively double the dataset and reduce overfitting. | **On** (12 → 24) |
| **Resolution / Aspect Bucketing** | Train at several sizes (512/768/1024); "bucketing" groups images by shape so non-square crops train without being squished. | 512/768/1024 |
| **Cropping** | We trimmed the couch shots to *narrator-only* so the LoRA doesn't accidentally learn Celeste sitting next to him ("identity bleed"). | 5 frames cropped |
| **Overfitting** | When the model *memorizes* the training images — including their backgrounds/poses — instead of learning the general character. Symptom: he only looks right on a couch/storefront. **The #1 risk with a tiny dataset.** We fight it with: low rank, flip aug, caption variety, and **stopping early**. | — |

### Watching the run (sampling & checkpoints)

| Term | Meaning | Ours |
|---|---|---|
| **Sample prompts** | Test prompts the trainer renders periodically so we can *see* the LoRA improving. We deliberately used **new settings** (park/beach/kitchen) in **front + rear** views to detect overfitting live. | 4 prompts |
| **Sample every** | How often to render those test images. | every **250** steps |
| **Guidance Scale** | How strongly generation obeys the prompt (higher = more literal). | **4** (right for Base) |
| **Seed** | The fixed random starting point. Keeping it fixed means the same prompt makes a comparable image at every checkpoint, so drift is obvious. | **42**, fixed |
| **Checkpoint** | A saved snapshot of the LoRA at a given step (`narrator-zimage_000000250.safetensors`, etc.). | saved every 250 |
| **Save every / Max saves to keep** | How often to save, and how many to retain. We keep many so we can pick the **best early** one before overfit. | save 250 / keep **12** |
| **Baseline / First sample** | A test render at step 0 (before any training) = the "before" picture. `chrsnrtr` means nothing yet, so it looks generic. | On |

---

## 4. Infrastructure terms (the GPU pod)

| Term | Meaning |
|---|---|
| **RunPod** | A service that rents cloud GPUs by the hour. A **pod** is one rented machine (a container). |
| **GPU / RTX 5090** | The graphics card that does the heavy math. Ours is a 5090. |
| **VRAM** | The GPU's own memory (32 GB here). The model + training data must fit in it — hence quantization, gradient checkpointing, and "Low VRAM" mode. |
| **Blackwell / CUDA** | Blackwell = the 5090's chip generation; CUDA = NVIDIA's compute toolkit (v12.8/13 here). Newer chips need newer CUDA/PyTorch — we verified PyTorch sees the card. |
| **Container disk vs Network volume** | Container disk (150 GB) is **temporary** — it vanishes when the pod is destroyed. The Network volume (`zimage-lora-factory`, region-locked) is **persistent** and survives. ⚠️ Our output is currently on the *container* disk, so we must **download the trained LoRA before terminating the pod**. |
| **Hugging Face (HF) / HF cache** | Hugging Face is where models download from. The "cache" is the local downloaded copy (`~/.cache/huggingface`). |
| **DNS** | Translates names like `huggingface.co` into network addresses. Ours was broken on the pod ("Temporary failure in name resolution"), which blocked the model download until we pointed it at public DNS (1.1.1.1). |
| **`HF_HUB_OFFLINE`** | An env flag telling tools to load models only from the local cache (no internet) — a workaround we kept ready. |
| **ai-toolkit worker / queue** | ai-toolkit's UI hands jobs to a background "worker." Ours got stuck, so we ran training **directly from the command line** (`python run.py`) to bypass it. That's why the UI's Queue still shows "queued 0/3000" — ignore it; the real run is the CLI process. |

---

## 5. How it plugs into agent-stack (the integration side)

| Term | Meaning |
|---|---|
| **Template / `visual-workflow-lora`** | A ComfyUI workflow we built (Phase 1) that has a **LoRA loader** wired in, so the agent can apply a character LoRA. The existing templates didn't have one. |
| **`lora_0` / `lora_0_strength` slots** | The named "plugs" the agent writes into: which LoRA to load and how strongly (0 = off, 1 = full). We added the strength plug so canon's tuned value actually takes effect. |
| **Canon** | The project's locked character descriptions (in `celeste-you-dangerous.json`). "Pinning" the LoRA to *the narrator* means it auto-applies whenever he's in a shot — and we can then **trim his long text description** from prompts. |
| **Silent-QKV gotcha** | A Z-Image quirk where a LoRA can *appear* to load but actually do nothing (because of how Z-Image packs its attention weights). We'll verify it's really working with a **strength 0 vs 1** test — if the image doesn't change, we swap in a special loader node. |
| **Identity-bearing flag** | A marker in the model registry that tells canon "this LoRA carries a character's identity," which the auto-pin relies on. |

---

## 6. The plan in one picture

```
Phase 0  Decide: train on Z-Image Base  ✅
Phase 1  Build a ComfyUI template with a LoRA slot (visual-workflow-lora)  ✅
Phase 2  Curate + crop + caption 12 narrator images  ✅
Phase 3  Train the LoRA on the GPU pod        ◧ (running now)
Phase 4  Load the .safetensors into ComfyUI, verify it actually works (strength 0-vs-1)
Phase 5  Pin it to the narrator's canon, trim his prompt text, test a shot
Phase 6  Repeat for Celeste
```

**Bottom line:** we're teaching the image model to know the narrator by a single word (`chrsnrtr`), so
every future shot is consistent and your prompts get short. The training run happening now is the one
step that needs a rented GPU; everything else is prep and wiring.
