# RunPod Environment — Context for Claude

Use this as ground truth when helping me with model downloads, ComfyUI configuration,
storage, or troubleshooting on this pod. Do not assume default paths — the paths below
are the real ones on this machine.

---

## Compute / hardware

- **GPU:** 1× NVIDIA **RTX PRO 6000 Blackwell Server Edition** — Blackwell architecture, **96 GB VRAM** (GDDR7).
- **System:** 251 GB RAM, 16 vCPU.
- **On-demand price:** ≈ $2.09/hr for the GPU, billed per-second while the pod is running.
- **Datacenter / region:** US-NE-1.
- **Template:** `agent-stack` — container image `runpod/comfyui:1.3.0-cuda12.8`.
- **Access:** SSH terminal enabled; ComfyUI served on HTTP port 8188.

---

## Storage — two distinct areas, keep them straight

1. **Network volume `gen-usne1`** (ID `3wqkq1t8bq`) — **200 GB** (resized up from 100 GB on
   2026-06-19), Standard tier, datacenter US-NE-1, mounted at **`/workspace`**.
   - **PERSISTENT.** Independent of the pod's lifecycle. Survives pod **stop AND terminate/delete**.
   - This is where everything I want to keep must live.
   - **Why resized:** 100 GB couldn't hold z-image + the full WAN t2v+i2v 14B set with
     working room — it kept hitting "disk quota exceeded," which corrupts files in
     confusing, indirect ways (see "Volume-full symptoms" below). Volumes only grow.
2. **Container disk** — 150 GB, the pod's root filesystem (everything *outside* `/workspace`).
   - **TEMPORARY.** Wiped on stop or terminate. Never store anything I want to keep here.

**Persistence rule of thumb:** path under `/workspace` = safe; anywhere else = ephemeral.

---

## Directory structure (ComfyUI)

ComfyUI runs from the network volume at:

```
/workspace/runpod-slim/ComfyUI
```

(There is also a baked copy at `/opt/comfyui-baked` on the **container disk** — that is the
image's template, NOT the active instance. Ignore it for storage purposes.)

Model directories — all under the network volume, all persistent:

```
/workspace/runpod-slim/ComfyUI/models/
├── diffusion_models/   ← Wan 2.2 video models (t2v + i2v, high/low, fp8 scaled)
├── text_encoders/      ← umt5_xxl_fp8_e4m3fn_scaled (active WAN encoder) + qwen_3_4b (z-image)
├── vae/                ← wan_2.1_vae (WAN) + ae.safetensors (z-image)
├── loras/              ← wan2.2 lightx2v 4-step LoRAs (video) + character identity LoRAs (see below)
├── unet/               ← z_image_turbo_bf16.safetensors (z-image-turbo, text-to-image)
└── checkpoints/, controlnet/, ...  (standard ComfyUI folders)
```

---

## Rule for storing ANY new model

A model file must satisfy **both** conditions:

- **(a) Persistent** — path begins with `/workspace/` (so it survives terminate).
- **(b) Visible** — path is inside `/workspace/runpod-slim/ComfyUI/models/<correct_type>/` (so ComfyUI loads it).

Failure modes to avoid:
- Under `/workspace` but *outside* the ComfyUI models tree → saved but **invisible** to ComfyUI.
- *Outside* `/workspace` → visible only until the next stop/terminate, then **gone**.

When downloading, set `COMFY=/workspace/runpod-slim/ComfyUI` and place files in the matching
`models/<type>/` subfolder.

---

## Currently installed (verified 2026-06-19)

- **z-image-turbo** (text-to-image): `models/unet/z_image_turbo_bf16.safetensors`,
  `text_encoders/qwen_3_4b.safetensors`, `vae/ae.safetensors` — confirmed working.
- **Wan 2.2** (video, t2v + i2v) — confirmed working manually in ComfyUI:
  - `diffusion_models/`: `wan2.2_t2v_high_noise_14B_fp8_scaled`, `wan2.2_t2v_low_noise_14B_fp8_scaled`,
    `wan2.2_i2v_high_noise_14B_fp8_scaled`, `wan2.2_i2v_low_noise_14B_fp8_scaled` (~14 GB each).
  - `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (the encoder the WAN templates
    use). **Note:** the `umt5_xxl_fp16` encoder was downloaded then **deleted** to free
    space — it was redundant (templates use fp8). The fp16 path is a deferred quality option.
  - `vae/wan_2.1_vae.safetensors` (the 14B VAE — not `wan2.2_vae`, which is the 5B's).
  - `loras/`: `wan2.2_t2v_lightx2v_4steps_lora_v1.1_{high,low}_noise` and
    `wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise` (the "fast mode" 4-step LoRAs the
    ComfyUI WAN templates ship with).

- **Character identity LoRAs** (`models/loras/`, added after the 2026-07 Coraline pivot +
  Turbo retrain). Per character (`narrator`, `celeste`), in the naming scheme
  `<char>-zimage[-coraline[-turbo]].safetensors`:
  - `*-zimage-coraline-turbo.safetensors` — **the pinned, in-use pair.** Trained **on
    Z-Image Turbo** (Ostris de-distill adapter), so they apply at **strength ~1.0**. Canon
    pins exactly these. See `docs/{narrator,celeste}-zimage-coraline-turbo.yaml`.
  - `*-zimage-coraline.safetensors` — the earlier **Base-trained** Coraline LoRAs
    (superseded; needed ~2.0 on Turbo, which caused prompt-override + identity bleed).
  - `*-zimage.safetensors` — the **felt-era v1** LoRAs (the documented style comeback path).
  - The bake-off **`*-turbo-2500.safetensors` alternates were unregistered** (`model rm`) once
    the finals were pinned — the files may still sit on the volume, but the drafter no longer
    sees them. Only ever pin **one** LoRA per character (canon owns identity).

Captured ComfyUI graphs (API format) + recipes: `packages/visual-generation/workflows/`.

---

## Two pods, two jobs — do not confuse them

There are **two separate RunPod pods on two separate volumes**, driven by two scripts. This
document is primarily about the **inference** pod. Never cross the wires:

| | **Inference** (this doc) | **Training** |
|---|---|---|
| Script | `scripts/pod` (`up`/`down`/`status`/`watch`) | `scripts/lora-train` |
| Job | Run ComfyUI → generate images/video | Train character LoRAs (Ostris ai-toolkit) |
| GPU | RTX PRO 6000 Blackwell 96 GB, **US-NE-1** | RTX 5090, **EU-RO-1** |
| Image | `runpod/comfyui:1.3.0-cuda12.8` | `ostris/aitoolkit:latest` (template `0fqzfjy6f3`) |
| Volume | `gen-usne1` (`3wqkq1t8bq`) at `/workspace` | `zimage-lora-factory` (`1r6sjkfwnl`) at `/mnt` |
| Port | ComfyUI 8188 | ai-toolkit UI 8675 |

Both volumes are datacenter-locked to different regions, so the two pods **can run at once**.
The pod id (and thus the `https://<pod-id>-8188.proxy.runpod.net` endpoint) is **new every
session** — read it from `pod status`, never hardcode it. **LoRA training recipe (proven):**
train **on Z-Image Turbo** (`Tongyi-MAI/Z-Image-Turbo`) with the de-distill adapter
`ostris/zimage_turbo_training_adapter_v2`, rank 8, LR 5e-5, batch 2, 3000-step cap, sampling
every 250; the Turbo-trained result runs at ~1.0 (Base-trained needed ~2.0 → override/bleed).

---

## Connecting (SSH) — two endpoints, they do different things

RunPod shows two SSH options in **Connect**, and they are NOT interchangeable:

- **Proxy — `ssh <pod-id>@ssh.runpod.io -i <key>`** — interactive terminal **only**.
  It does **not** support scp/sftp or file-piping (`cat > file` fails with
  "Your SSH client doesn't support PTY"). Fine for running commands, useless for transfers.
- **Direct TCP — `ssh root@<ip> -p <port> -i <key>` ("Supports SCP & SFTP")** — use this
  for **scp**. The IP and port are **new every time the pod is recreated** — re-read them
  from Connect after any migration.

## Getting an image (or any file) onto the pod

**Do not use ComfyUI's browser upload** — through the RunPod proxy it corrupts image files
(broken thumbnails, `PIL UnidentifiedImageError`, "Invalid image file", 500s). Instead scp
over the direct-TCP endpoint into `ComfyUI/input/`:

```bash
# from the Mac; IP/port from Connect → "SSH over exposed TCP"
scp -P <PORT> -i ~/.ssh/id_ed25519 "/path/to/image.png" \
  root@<IP>:/workspace/runpod-slim/ComfyUI/input/image.png
# verify on the pod:  file .../input/image.png  → "PNG image data"
```

Then in ComfyUI press **R** and pick it from the Load Image dropdown (not "choose file to upload").

## Migrating to a new pod (GPU availability churns)

When a pod is reclaimed and you start a new one:

- **Models, graphs, outputs persist** on `gen-usne1` and re-attach automatically — **no
  re-downloading**. (The container disk is wiped; nothing you keep lives there.)
- **The endpoints change** — the ComfyUI proxy URL (`https://<pod-id>-8188.proxy.runpod.net`)
  and the direct-TCP SSH IP/port are new per pod. Update wherever you use them.
- **Must be US-NE-1** — the volume is datacenter-locked, so a replacement pod has to be in
  US-NE-1 to mount it.
- A "migrate pod data" prompt concerns the disposable container disk only — irrelevant to
  the volume; don't wait on it for the models.

## Volume-full symptoms (so they're recognizable)

A full `/workspace` fails indirectly. If you see any of these, check/raise the quota:

- scp reaches 100% then `write/close remote: Failure`.
- a download lands as a **0-byte** file → later `ValueError: cannot mmap an empty file`
  when ComfyUI loads it. (A 0-byte file looks "present" so it won't re-download — delete it
  first, free space, then re-fetch.)
- `comfy.settings.json` corrupts → "user settings file is corrupted" spam + a frontend
  **`TypeError: Load failed`** popup. Fix: `rm` the settings file and restart ComfyUI.
- `df -h /workspace` shows the underlying cluster (hundreds of TB), **not** the per-volume
  quota — so it won't reveal a full volume. Use the RunPod console's volume meter instead.

(Note: a frontend `TypeError: Load failed` *after* a run whose log says "Prompt executed in
N seconds" is just a preview glitch — the clip is in `output/video/`.)

---

## Why this GPU and datacenter were chosen

**Starting problem:** previously on 1× A100 SXM in US-CA-2, constantly hitting
"There are no instances currently available." A100 SXM availability is Low across all
datacenters — that scarcity was the root cause, not the datacenter.

**Constraints that drove the decision:**
- Network volumes are **datacenter-locked** and attach to a single pod, so the datacenter
  the volume is built in dictates which GPUs can ever be run against it. (Pods — unlike
  Serverless — cannot use multi-datacenter volume failover.)
- Two workloads were needed: image generation (Stable Diffusion / z-image-turbo, immediate)
  and Wan 2.2 video generation (within days).
- The high-availability image GPUs (RTX 4090 24 GB, RTX PRO 4500 32 GB) were only "High"
  in EU-RO-1 (Europe) — but EU-RO-1 had only "Low" availability for any high-VRAM video card.
- Video models (Wan 2.2 14B) need far more VRAM than 24 GB; a consumer card would hit memory
  walls at higher resolution. 96 GB removes that ceiling.
- **No single datacenter offered both** strong image-GPU availability and a decent video GPU.
  US-NE-1 was the only datacenter with "Medium" (the best available anywhere) RTX PRO 6000.

**Decision:** rather than split into two volumes in two datacenters (image in EU, video in US)
and duplicate models across them, use **one GPU that handles both**. The 96 GB PRO 6000 runs
image gen trivially and handles video with headroom — a single volume, single datacenter,
single setup, no model duplication, no datacenter juggling.

**Cost tradeoff (accepted deliberately):** PRO 6000 ≈ $2.09/hr vs an RTX 4090 ≈ $0.69/hr —
about 3× to run image work on a video-class GPU, in exchange for one reliable environment
that also does video. Pods bill only while running, so the premium only applies during active
sessions. At deploy time the PRO 6000 was actually available in US-NE-1 while B200, MI300X,
and A100 PCIe all showed "Out of capacity" — confirming it was the right pick for availability.

**Cost control:** a local dead-man's-switch script (`pod-watchdog.sh`) stops the pod via
`runpodctl` if I don't confirm I'm still working, so it can't run idle at ~$2/hr.
