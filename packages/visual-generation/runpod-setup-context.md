# RunPod Environment — Context for Claude

Use this as ground truth when helping me with model downloads, ComfyUI configuration,
storage, or troubleshooting on this pod. Do not assume default paths — the paths below
are the real ones on this machine.

---

## Compute / hardware

- **GPU:** 1× NVIDIA **RTX PRO 6000 Blackwell Server Edition** — Blackwell architecture, **96 GB VRAM** (GDDR7).
- **System:** 251 GB RAM, 16 vCPU.
- **On-demand price:** ≈ $2.09/hr for the GPU, billed per-second while the pod is running.
- **Datacenter / region:** any. The Global Volume (see "Storage" below) is region-independent,
  so the GPU schedules wherever capacity allows — no datacenter lock to honor.
- **Template — ⚠️ DO NOT use `agent-stack` (id `cnne9dp3rt`, image `runpod/comfyui:*`) with
  this volume.** This supersedes older guidance (this doc used to say "deploy this template,
  not the bare image" — that was correct for the old regional `gen-usne1` volume and is now
  actively wrong). **Confirmed 2026-09-19:** deploying it against the Global Volume
  crash-loops the pod — `runpod/comfyui`'s own entrypoint rsyncs a baked ComfyUI bundle onto
  `/workspace` on every boot via `rsync -a` (needs `chown` + atomic rename), both of which the
  Global Volume rejects:
  ```
  rsync: [generator] chown "/workspace/runpod-slim/ComfyUI/." failed: Operation not permitted (1)
  rsync: [receiver] mkstemp "/workspace/.../file.py.XXXXXX" failed: Operation not permitted (1)
  ```
  The entrypoint runs under `set -e`, so the first failure kills the container; RunPod
  restarts it; loop (observed: ~11 restarts at 17s intervals, `Processes: 0` the whole time,
  billing the full $2.11/hr throughout — **pod-level `desiredStatus` shows `RUNNING` the
  entire time**, so `pod status`/`pod get` alone won't reveal this). `scripts/pod` now
  defaults `TEMPLATE_ID` to RunPod's stock PyTorch template (`runpod-torch-v280`, image
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`) instead, which has no baked
  ComfyUI-sync step. ComfyUI is installed and started separately by
  `scripts/comfyui-bootstrap` (see below), which is written around the same volume limits
  (no `rsync -a`, no `mv` across the FUSE boundary — see that script's header comment).
  `scripts/pod up` also now polls for a healthy runtime after create and deletes+fails loudly
  if one never reports in, specifically to catch a repeat of this incident automatically
  rather than leave a pod crash-looping at cost — see its `HEALTH_CHECK_*` knobs.
  Template ids are account-specific (not secrets — inert without the API key); set via `.env`
  as `TEMPLATE_ID`.
- **Access:** SSH terminal enabled; ComfyUI served on HTTP port 8188.
- **Pod creation goes through RunPod's GraphQL API, not `runpodctl`.** `runpodctl` (and the
  REST API it wraps) can't attach a Global Volume — `--network-volume-id` fails with "Network
  volume not found." `scripts/pod up` instead POSTs the `podFindAndDeployOnDemand` GraphQL
  mutation directly (the same call the web console makes to attach one), authenticated via a
  `RUNPOD_API_KEY` env var passed as a `?api_key=` query param. This is undocumented beta API
  surface — see the script's header comment for the full capture provenance and caveat.
  `down`/`status`/`watch` are unaffected (still `runpodctl`).

---

## Storage — two distinct areas, keep them straight

1. **Global Volume `stably_diffused`** (ID supplied via `IMAGE_NETWORK_VOLUME_ID` — the var
   name predates this migration and still says "network volume"; it now holds a **Global
   Volume** id instead), mounted at **`/workspace`**. (Earlier notes in this doc/history
   called it `bizarre_moccasin_jaguar` — confirmed via the RunPod console's Volumes tab
   2026-09-19 that its current display name is `stably_diffused`, 90 GB / 451 objects
   stored.)
   - **PERSISTENT.** Independent of the pod's lifecycle. Survives pod **stop AND
     terminate/delete**.
   - **Region-independent.** Replaces the old regional network volume (`gen-usne1`, US-NE-1
     — gone as of 2026-09). No datacenter lock: a pod in any datacenter can mount it.
   - **Elastic.** No fixed size to provision, billed on stored data — the old volume's
     fixed-size "disk quota exceeded" failure class (see the old resize history, no longer
     relevant) doesn't apply here.
   - **Backed by object storage via a FUSE layer** (`fuse.geesefs`), not local NVMe: ~181
     MB/s cold sequential read (a ~40GB model load ≈ 4 min). RunPod documents this as **poor
     for frequent writes** — reads are fine. Practical implication: keep ComfyUI's
     output/input/temp/user dirs AND the Python venv off this volume — see
     `scripts/comfyui-bootstrap`, which routes all of that to the container disk instead.
   - **Files report owner `nobody:nogroup`, and it has no real permission bits.** Beyond the
     cosmetic warning tools like `pip` print, this is load-bearing: an explicit `chown()` or
     `chmod()` call against a file already on this volume **fails with `Operation not
     permitted`** — confirmed 2026-09-19 (see the Template warning above for the incident
     this caused). It also doesn't support atomic rename (mkstemp-then-rename), which `git`
     and `rsync -a` both depend on for their own writes. Practical rule: never run `rsync
     -a`, `cp -p`/`cp -a`, `mv` (its cross-device fallback preserves mode, same problem), or
     any explicit `chown`/`chmod` against a path under `/workspace` — plain `cp -r` (no -p)
     or a fresh `git clone` INTO a path here is fine; modifying-in-place with
     metadata-preserving tools is not. `scripts/comfyui-bootstrap` is written around this.
   - This is where everything I want to keep must live.
2. **Container disk** — 150 GB, the pod's root filesystem (everything *outside* `/workspace`).
   - **TEMPORARY.** Wiped on stop or terminate. Never store anything I want to keep here.

**Persistence rule of thumb:** path under `/workspace` = safe; anywhere else = ephemeral.

---

## Directory structure (ComfyUI)

ComfyUI runs from the Global Volume at:

```
/workspace/runpod-slim/ComfyUI
```

(The old `runpod/comfyui` image also carried a baked copy at `/opt/comfyui-baked` on the
container disk — irrelevant now that the default template/image is the plain PyTorch one
with no baked ComfyUI at all; see the Template warning above.)

Model directories — all under the Global Volume, all persistent:

```
/workspace/runpod-slim/ComfyUI/models/
├── diffusion_models/   ← Wan 2.2 video models (t2v + i2v, high/low, fp8 scaled)
├── text_encoders/      ← umt5_xxl_fp8_e4m3fn_scaled (active WAN encoder) + qwen_3_4b (z-image)
├── vae/                ← wan_2.1_vae (WAN) + ae.safetensors (z-image)
├── loras/              ← wan2.2 lightx2v 4-step LoRAs (video) — character identity LoRAs
│                          are NOT currently present, see "Currently installed" below
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

## Currently installed (verified 2026-09-19, on the rebuilt Global Volume)

~85 GB under `/workspace/runpod-slim/ComfyUI/models/`:

- **z-image-turbo** (text-to-image): `unet/z_image_turbo_bf16.safetensors` (12G).
- **Wan 2.2** (video, t2v + i2v):
  - `diffusion_models/`: `wan2.2_{t2v,i2v}_{high,low}_noise_14B_fp8_scaled` (4 files, 54G).
  - `text_encoders/`: `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (the encoder the WAN templates
    use) + `qwen_3_4b.safetensors` (z-image) — 14G total.
  - `vae/`: `wan_2.1_vae.safetensors` (the 14B VAE — not `wan2.2_vae`, which is the 5B's) +
    `ae.safetensors` (z-image) — 562M total.
  - `loras/`: `wan2.2_t2v_lightx2v_4steps_lora_v1.1_{high,low}_noise` and
    `wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise` (the "fast mode" 4-step LoRAs the
    ComfyUI WAN templates ship with) — 4 files, 4.6G total.

**⚠️ TODO / MISSING — character identity LoRAs are NOT on this volume.** The `narrator` and
`celeste` identity LoRAs did not carry over from the old `gen-usne1` volume to the rebuilt
Global Volume. **Do not assume they exist; do not fabricate paths for them.** They previously
lived at `models/loras/<char>-zimage[-coraline[-turbo]].safetensors`, in this naming scheme
(kept here as reference for when they're restored — none of this is currently present):
  - `*-zimage-coraline-turbo.safetensors` — the pinned, in-use pair. Trained **on Z-Image
    Turbo** (Ostris de-distill adapter), so they apply at **strength ~1.0**. Canon pinned
    exactly these. See `docs/{narrator,celeste}-zimage-coraline-turbo.yaml`.
  - `*-zimage-coraline.safetensors` — the earlier **Base-trained** Coraline LoRAs
    (superseded; needed ~2.0 on Turbo, which caused prompt-override + identity bleed).
  - `*-zimage.safetensors` — the **felt-era v1** LoRAs (the documented style comeback path).
  - Only ever pin **one** LoRA per character (canon owns identity).

Re-train (`scripts/lora-train` — status of its own volume is unverified, see "Two pods, two
jobs" below) or re-transfer these before any generation that depends on character identity.

**ComfyUI itself is not installed on the volume** — only `models/` exists. Install + start it
with `scripts/comfyui-bootstrap` (run on the pod over SSH; see `scripts/README.md`).

Captured ComfyUI graphs (API format) + recipes: `packages/visual-generation/workflows/`.

---

## Two pods, two jobs — do not confuse them

There are **two separate RunPod pods on two separate volumes**, driven by two scripts. This
document is primarily about the **inference** pod. Never cross the wires:

| | **Inference** (this doc) | **Training** |
|---|---|---|
| Script | `scripts/pod` (`up`/`down`/`status`/`watch`) | `scripts/lora-train` |
| Job | Run ComfyUI → generate images/video | Train character LoRAs (Ostris ai-toolkit) |
| GPU | RTX PRO 6000 Blackwell 96 GB, **any datacenter** | RTX 5090, **EU-RO-1** *(unverified, see below)* |
| Image | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` via template `runpod-torch-v280` (default `TEMPLATE_ID`) — **never** `runpod/comfyui`/`cnne9dp3rt`, see Template warning above | `ostris/aitoolkit:latest` (template `<template-id>`) |
| Volume | Global Volume `stably_diffused` at `/workspace` (id via `IMAGE_NETWORK_VOLUME_ID`) | `zimage-lora-factory` at `/mnt` (id via `LORAS_NETWORK_VOLUME_ID`) — **status unverified** |
| Port | ComfyUI 8188 | ai-toolkit UI 8675 |

**Training pod/volume status (as of 2026-09-19): unverified, possibly gone.**
`runpodctl network-volume list` returned zero volumes on this account — so `zimage-lora-factory`
(and the third volume reserved via `QWEN_NETWORK_VOLUME_ID` for the planned Qwen-Image-Edit
migration) may no longer exist, the same way `gen-usne1` didn't. Confirm before running
`scripts/lora-train up`; `scripts/lora-train` itself hasn't been changed as part of the Global
Volume migration. The inference pod is no longer datacenter-locked (Global Volume); whether the
training pod still is depends on whether `zimage-lora-factory` survives as a regional network
volume — unverified.
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

**SSH/tunnel drops during long waits are expected, not a sign of a broken setup.** A `Direct
TCP` SSH session (and any tunnel through it, e.g. `ssh -N -L 8188:127.0.0.1:8188 ...` for
browser access) commonly gets silently killed by an idle-connection timeout on a NAT/firewall/
proxy somewhere on the path — most noticeable during a long cold model load (see "Cold vs.
warm model-load times" below), where the terminal itself sees no traffic for minutes at a
time even though you're actively watching the browser. Mitigate with client-side keepalives in
`~/.ssh/config`:

```
Host *
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Applies to new connections only (reconnect after adding it). Note the ComfyUI **server
process itself is unaffected** by a dropped SSH/tunnel session — `comfyui-bootstrap` starts it
with `nohup ... & disown`, so it keeps running (and finishes any in-flight generation)
independent of your terminal. A `TypeError: Load failed` / "Reconnecting" popup in the browser
right after a drop is just the browser losing its live connection, not a failed generation —
reload the page once reconnected and check the Job Queue / server log for ground truth.

## Getting an image (or any file) onto the pod

**Do not use ComfyUI's browser upload** — through the RunPod proxy it corrupts image files
(broken thumbnails, `PIL UnidentifiedImageError`, "Invalid image file", 500s). Instead scp
over the direct-TCP endpoint into ComfyUI's input dir — **on the container disk**, not the
volume: `scripts/comfyui-bootstrap` starts ComfyUI with `--input-directory` pointed at
`/comfy-data/input` (kept off the Global Volume along with output/temp/user — see "Storage"
above), so that's the path to scp into, not `ComfyUI/input/` on `/workspace`:

```bash
# from the Mac; IP/port from Connect → "SSH over exposed TCP"
scp -P <PORT> -i ~/.ssh/id_ed25519 "/path/to/image.png" \
  root@<IP>:/comfy-data/input/image.png
# verify on the pod:  file /comfy-data/input/image.png  → "PNG image data"
```

Then in ComfyUI press **R** and pick it from the Load Image dropdown (not "choose file to upload").

## Migrating to a new pod (GPU availability churns)

When a pod is reclaimed and you start a new one:

- **Models and ComfyUI's code persist** on the Global Volume and re-attach automatically —
  **no re-downloading, no reinstalling.** (The container disk is wiped, so the venv and any
  outputs left there are gone — re-run `scripts/comfyui-bootstrap`, which rebuilds the venv
  fast and detects the existing ComfyUI checkout.)
- **The endpoints change** — the ComfyUI proxy URL (`https://<pod-id>-8188.proxy.runpod.net`)
  and the direct-TCP SSH IP/port are new per pod. Update wherever you use them.
- **Any datacenter works now** — the Global Volume is region-independent, so a replacement
  pod can schedule in whichever datacenter has GPU capacity; no region to match.
- A "migrate pod data" prompt concerns the disposable container disk only — irrelevant to
  the volume; don't wait on it for the models.

## Write-performance note (replaces the old "volume-full" section)

The old `gen-usne1` network volume had a fixed size and would hit "disk quota exceeded" when
full — a failure mode that corrupted files in confusing, indirect ways (0-byte downloads,
`comfy.settings.json` corruption). **That whole failure class doesn't apply to the Global
Volume:** it's elastic, billed on stored data, with nothing to provision or run out of.

What DOES apply: the Global Volume is backed by object storage via a FUSE layer
(`fuse.geesefs`), documented by RunPod as **poor for frequent writes** (~181 MB/s cold
sequential read is the only measured number available — write throughput/latency wasn't
characterized). The mitigation is `scripts/comfyui-bootstrap`, which keeps `output/`,
`input/`, `temp/`, `user/` (so `comfy.settings.json` specifically can't hit this volume at
all anymore), and the Python venv on the container disk instead — the volume should only ever
be written to for install/model-download steps, not per-generation output.

No FUSE-specific corruption symptoms have actually been observed on this volume yet — if
something surfaces (partial writes, stale reads, etc.), document it here rather than assuming
it behaves like the old quota-exceeded failures.

(Unrelated to the volume, still true: a frontend `TypeError: Load failed` popup *after* a run
whose log says "Prompt executed in N seconds" is just a preview glitch, not a failed
generation — the clip is in `output/video/`.)

## Cold vs. warm model-load times (measured 2026-09-20)

Loading model weights off the Global Volume into VRAM — not the diffusion sampling itself —
is the dominant cost on a freshly-created pod. Once a model's weights are resident in VRAM,
re-running against the *same* model is dramatically faster; this GPU's 97GB VRAM comfortably
holds several models at once, so they stay warm across generations until something evicts
them.

Measured end-to-end (`Prompt executed in Xs` from the ComfyUI log) on a fresh
`runpod-torch-v280` pod: first generation against a model vs. the very next generation against
the same model (different seed each time, to force a real recompute rather than a
node-level cache hit):

| Model | Cold (first gen) | Warm (next gen) |
|---|---|---|
| Z-Image-Turbo (image, ~19.5GB combined weights) | 477s (~8 min) | 2.03s |
| Wan 2.2 T2V 14B lightx2v (video, ~34GB combined weights) | 2339s (~39 min) | 8.55s |

**Don't mistake a cold load for a hang.** `0/N` progress and 0% GPU utilization for several
minutes right after clicking Run is expected on a fresh pod, not stuck — the GPU sits idle
while weights stream in from the volume. To confirm it's genuinely working rather than dead,
run `nvidia-smi dmon -s u -d 1` on the pod: a healthy run shows long stretches of 0% (loading)
with a brief `sm` spike to ~100% for a second or two (the actual sampling), not a permanent
flatline once a job has actually been queued.

One anomaly observed, not yet explained: Wan's two ~13.6GB diffusion models loaded
back-to-back showed a 3.4x slowdown on the second one (395s vs. 1351s) despite identical file
size. Candidates, unconfirmed: storage-backend throughput variance, or an interaction between
the dynamic-VRAM ("comfy-aimdo") loading system and having multiple large models staged at
once. Revisit if it recurs.

**Cost implication:** `scripts/pod up` always creates a fresh pod rather than resuming a
stopped one (see "Why create/delete, not start/stop" in `scripts/README.md`), so every new pod
pays the full cold-load cost again the first time each model is used on it — currently ~8 min
for Z-Image, ~39 min for Wan, per pod, at ~$2.09/hr. Factor this in before spinning up a pod
for a quick one-off test.

## Staged-model-load A/B test (hypothesis: FUSE mmap pattern, not raw throughput, is the cost)

The cold-load numbers above are suspiciously slow given the volume's own measured
throughput: a plain sequential read off it hits ~181 MB/s, but the actual cold loads above
only achieved ~15-41 MB/s effective. Suspected cause: `safetensors` loading is mmap-based, so
a cold load becomes many page-fault-driven small reads over the volume's FUSE layer
(`fuse.geesefs`) — close to worst case for object storage, even though the volume delivers
bytes fast under a plain sequential read. `scripts/stage-models` + `comfyui-bootstrap`'s
`STAGED_MODELS` knob exist to test this: copy the models to the container disk first (a
sequential read, matching the fast measured rate), then have ComfyUI load from there instead
of the volume, and see whether that turns ~39 minutes into roughly copy-time-plus-seconds.
Confidence in the hypothesis is moderate and was explicitly unmeasured until this test exists
to measure it.

**Mechanism, confirmed from ComfyUI's own source (`cli_args.py` / `folder_paths.py`), not
assumed:** `--models-directory <dir>` fully replaces the base models directory every default
per-type search path is built from — no default path coexists alongside it. Passing it means
the volume's `models/` tree is never registered as a search path at all, so there's no way
for ComfyUI to silently fall back to it.

**Decide the bar before running, not after — the 2339s Wan baseline above came from a
different pod on a different day, and storage variance is already evidently high (the 3.4x
anomaly noted above, between two identically-sized files in that same run). A single run is
only decisive if the effect is large; the hypothesis predicts roughly a 10x improvement, which
clears that noise easily — but fix the threshold now, not after seeing the number:**

- **Total (copy time + first-gen time) under ~10 min → adopt staging** as the default path.
- **10–25 min → inconclusive; rerun once** before deciding either way.
- **Over ~25 min → reject** the hypothesis, at least for this volume/pod combination.

**Baseline `fast_disk=` value — cite the existing one, don't re-measure it.** ComfyUI's own
load-time log line (`Model storage policy: fast_disk=False paths=[...]`) only prints during
an actual model load; a plain install (protocol step 1 below) never triggers one. The only way
to capture a fresh baseline would be to run a full volume-backed generation first — don't do
that here: it costs ~39 minutes on its own, and it would warm the page cache for the exact
files `stage-models` is about to copy, inflating the "cold" copy-timing measurement that
follows. Use the value already confirmed against the volume on 2026-09-20 — **`fast_disk=False`**
(see the table above) — as the baseline instead.

**Protocol:**

1. Fresh pod, run `comfyui-bootstrap` normally (`STAGED_MODELS` unset) to install ComfyUI.
   **Do not run a generation against this volume-backed install** — see the baseline note
   above for why.
2. `./stage-models wan-t2v` — record the printed per-file and total copy time/throughput.
3. `RESTART=1 STAGED_MODELS=1 bash comfyui-bootstrap` — `RESTART=1` is required here, because
   step 1 already left ComfyUI running against the volume, and the startup script's own
   idempotency guard would otherwise silently leave that instance running instead of
   switching to the staged path (it logs which models dir a running instance is actually
   using, specifically so this kind of mismatch is visible rather than assumed). Confirm via
   **both** of the following that it's genuinely reading from the staged copy, not the
   volume:
   - ComfyUI's own load-time log line should now show a `$CONTAINER_DATA_DIR/staged-models/...`
     path instead of `$WORKSPACE/runpod-slim/ComfyUI/models/...` — also record its
     `fast_disk=` value here for comparison against the `False` baseline; a change in that
     value is itself a real finding, not noise, since ComfyUI appears to pick a different
     loading strategy based on it.
   - Independent kernel-level cross-check, since a log line is still just a string ComfyUI
     chose to print: **run this DURING the load, while the GPU sits at 0% utilization — not
     after generation completes**, since whether ComfyUI keeps the `safetensors` mmap open
     after transferring weights to VRAM is unconfirmed, and a post-generation check could
     show nothing and look like a failure when it isn't one.
     ```
     grep -i safetensors /proc/$(pgrep -f main.py)/maps | awk '{print $NF}' | sort -u
     ```
4. Run the pinned Wan lightx2v T2V workflow (`workflows/wan2.2-t2v-14B-lightx2v-api.json`),
   record `Prompt executed in Xs`.
5. Compare `(stage-models copy time) + (step 4's first-gen time)` against the 2339s baseline
   and the decision thresholds above.
6. Record whether the 3.4x anomaly (two identically-sized Wan diffusion files loading at 395s
   vs. 1351s in the original measurement) reproduces under local loading. If it disappears,
   that's real evidence the anomaly was a FUSE effect specifically, not something inherent to
   ComfyUI's dynamic-VRAM loading system.

**Caveat, so the result isn't misread later:** `/proc/sys/vm/drop_caches` is read-only inside
the container (no permission to actually drop page cache), so the staged files will be served
partly warm from page cache immediately after `stage-models` copies them. This is **not a
confound** — real usage stages then loads immediately after, so whatever page-cache benefit
exists is representative of actual use, not an artifact of the test.

---

## Why this GPU and datacenter were chosen

**Historical — this reasoning predates the Global Volume migration (2026-09).** The
datacenter-lock constraint the argument below rests on (a network volume pins a pod to one
region) no longer applies to the inference pod: the Global Volume is region-independent.
Kept as historical record because the VRAM/GPU-selection reasoning is unaffected by the
volume-type change — the 96 GB PRO 6000 was chosen because it single-handedly covers both
image and video VRAM needs, not only to avoid a datacenter split.

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
