# scripts

Operational helpers for agent-stack.

## `pod` — RunPod lifecycle controller & idle-cost watchdog

`pod` manages the **visual-generation** ComfyUI pod on RunPod: an RTX PRO 6000 (Blackwell)
GPU (any datacenter — no region lock), backed by the persistent **`stably_diffused`**
RunPod Global Volume (elastic, region-independent, object-storage-backed via a FUSE layer). It
both drives the pod's lifecycle and guards against runaway idle GPU cost.

**Pod creation goes through RunPod's GraphQL API directly, not `runpodctl`.**
`runpodctl pod create --network-volume-id <global-volume-id>` fails with "Network volume not
found" — neither `runpodctl` nor the REST API it wraps support attaching a Global Volume. The
web console does it via an undocumented `volumeMounts` field on the older
`podFindAndDeployOnDemand` GraphQL mutation; `pod up` replicates that call with `curl` (see
the script's header comment for the full capture/provenance and the beta-API caveat).
`down`/`status`/`watch` are unaffected — they still use `runpodctl`, which can read/delete
pods fine regardless of how they were created.

### Why create/delete, not start/stop

RunPod pins a **stopped** pod to its original physical host. For a scarce GPU like the
PRO 6000, that host's GPUs are almost always taken by the time you'd resume — so `pod start`
reliably fails with *"not enough free GPUs on the host machine,"* and stopped pods can be
reclaimed out from under you anyway.

So this script never starts or stops. It **creates a fresh pod** each time (which RunPod is
free to schedule onto *any* host with capacity) and **deletes** it when you're done. This is
safe because the **Global Volume exists independently of the pod and survives deletion** —
all models and data live on the volume. The pod itself is disposable scaffolding; throwing it
away costs nothing but the time to recreate it.

### Verbs

```
./scripts/pod <up|down|status|watch>
```

| Verb | What it does |
|------|--------------|
| `up`     | Ensure a running pod exists. If a pod matching the name is already RUNNING **with a GPU**, reuse it; otherwise create a fresh pod and verify it came up with a GPU attached (0 GPUs = capacity failure — delete + retry, see `CREATE_RETRIES` / `CREATE_RETRY_DELAY`), then poll for a healthy runtime before declaring success — see [Health check](#health-check-crash-loop-guard) below. |
| `down`   | Delete **all** pods matching the name (running *or* exited), so stale pods don't pile up. Never touches the network volume. |
| `status` | List matching pods with `id`, `name`, `desiredStatus`, `gpuCount`, `costPerHr`. Uses `pod list --all`, so stopped/exited pods are visible too. |
| `watch`  | Idle-cost watchdog for an already-running pod — see [Watchdog](#watchdog--idle-timeout) below. |

### Configuration

Every constant is overridable via environment variable. Defaults come from the top of the
script.

| Variable | Default | Controls |
|----------|---------|----------|
| `POD_NAME`           | `visual-generation` | Pod name to target. |
| `POD_ID`             | *(unset)* | Target a specific pod id instead of matching by name. |
| `TEMPLATE_ID`        | `runpod-torch-v280` | RunPod template to deploy from. **Never set this to the `agent-stack`/`cnne9dp3rt` ComfyUI template** — it crash-loops on the Global Volume (see [Template warning](../packages/visual-generation/runpod-setup-context.md)). Set to `""` explicitly to fall back to `IMAGE` instead. |
| `IMAGE`              | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` | Container image used on create when `TEMPLATE_ID` is empty. Must avoid any baked ComfyUI-workspace-sync entrypoint, same reason as `TEMPLATE_ID`. |
| `GPU_ID`             | `NVIDIA RTX PRO 6000 Blackwell Server Edition` | GPU type to request. |
| `CLOUD_TYPE`         | `SECURE` | RunPod cloud type. |
| `DATACENTER`         | *(unset — any datacenter)* | Datacenter id. Empty means no constraint — the Global Volume is region-independent, so no region needs to match. |
| `IMAGE_NETWORK_VOLUME_ID` | *(required — no default)* | Inference/image volume to mount; set to your RunPod Global Volume id (var name predates the Global Volume migration). `up` fails fast if unset. |
| `VOLUME_MOUNT_PATH`  | `/workspace` | Where the volume mounts inside the pod. |
| `CONTAINER_DISK_GB`  | `150` | Container disk size, in GB. |
| `PORTS`              | `8188/http,22/tcp` | Ports exposed on the pod (ComfyUI + SSH). |
| `RUNPOD_API_KEY`     | *(required for `up` — no default)* | RunPod API key, used directly for the GraphQL create call. `runpodctl` on this machine authenticates via its own `~/.runpod/config.toml`, not this var, so it likely needs adding to `.env` separately. |
| `CREATE_RETRIES`     | `3` | How many times `up` retries on a capacity error. |
| `CREATE_RETRY_DELAY` | `15` | Seconds to wait between create retries. |
| `HEALTH_CHECK_TIMEOUT` | `180` | Seconds `up` polls a freshly-created pod for a healthy runtime before giving up, deleting it, and exiting nonzero. |
| `HEALTH_CHECK_INTERVAL` | `15` | Seconds between health-check polls. |
| `CHECKIN_INTERVAL`   | `1800` | Seconds between `watch` check-in prompts (30m). |
| `GRACE`              | `180` | Seconds to respond to a `watch` prompt before auto-delete (3m). |

### Known-bad-source guard

Before every create attempt, `up` refuses outright if `TEMPLATE_ID` is a known-bad template
id (currently just `cnne9dp3rt`), or — when `TEMPLATE_ID` is empty — if `IMAGE` matches the
`runpod/comfyui` repo. Both crash-loop on this Global Volume (see the
[Template warning](../packages/visual-generation/runpod-setup-context.md)); this catches a
stale `.env` value immediately instead of burning a capacity-retry cycle and then relying on
the health check below. **Coverage is limited to what's checkable at create time:** the
`TEMPLATE_ID` check only matches the literal id — a renamed/re-created template with the same
baked entrypoint isn't caught. The `IMAGE` check matches any tag of `runpod/comfyui`, since
the image string is fully known at create time, but not a differently-named image bundling
the same entrypoint.

### Health check (crash-loop guard)

After a fresh create, `up` polls the pod for up to `HEALTH_CHECK_TIMEOUT` seconds (every
`HEALTH_CHECK_INTERVAL`s) watching its `uptimeSeconds` field (confirmed present in
`pod get -o json`'s output — an earlier version of this check polled `.runtime` instead,
which turned out not to exist in this account's responses at all). This exists because
`desiredStatus == RUNNING` and `gpuCount >= 1` — the checks `create_pod()` already does —
are **not enough**: a pod whose container is crash-looping (e.g. the
runpod/comfyui-template-on-Global-Volume incident, see
[runpod-setup-context.md](../packages/visual-generation/runpod-setup-context.md)) can show
both for its entire lifetime while running zero processes. A drop in `uptimeSeconds` between
polls means the container restarted — `up` deletes the pod and exits nonzero immediately. If
`uptimeSeconds` never leaves `0` for the full timeout, same outcome (zero uptime progress).
This deliberately does **not** require anything to be listening on the pod's exposed ports
(e.g. ComfyUI on 8188) — ComfyUI is installed/started separately by `comfyui-bootstrap`
*after* `up` succeeds, so gating on a port response here would always time out. It can't
catch a restart that happens after this check already passed — see the script's own comment
on `wait_for_healthy_pod()`.

### Watchdog / idle timeout

`watch` is a **dead-man's switch** that protects an already-running pod from quietly billing
GPU time after you've walked away. It does **not** create pods — run `up` first.

The loop:

1. Every `CHECKIN_INTERVAL` seconds (default **1800** / 30m), it pops a macOS dialog asking
   whether you're still working.
2. **Confirm** ("Still working") → it keeps the pod and resumes the loop.
3. Click **"Delete pod"**, *or* fail to respond within `GRACE` seconds (default **180** / 3m
   — this is the no-response timeout) → it **deletes** the pod.

It also exits cleanly if the pod disappears or stops on its own (reclaimed/deleted
externally).

The two knobs:

- **`CHECKIN_INTERVAL`** — how often it checks in.
- **`GRACE`** — the no-response timeout before it auto-deletes.

> The dialog uses `osascript`, which needs a local GUI session. **Run `watch` on the Mac, not
> over SSH.**

### Prerequisites

- **runpodctl** — installed and authenticated (used for `down`/`status`/`watch`, and to
  verify a pod after GraphQL creates it). Verify with `runpodctl doctor`.
- **jq**
- **curl** — used for the GraphQL create call.
- **`RUNPOD_API_KEY`** set in the environment — separate from `runpodctl`'s own auth, see
  Configuration above.

```sh
brew install runpod/runpodctl/runpodctl
brew install jq
```

### Safety rules

Pod creation POSTs directly to RunPod's GraphQL API (see above); `delete`/`list`/`get` still
go through `runpodctl`. Either way, the script **never** calls `pod start` or `pod stop`, and
**never** any `network-volume` subcommand. The Global Volume therefore cannot become
collateral damage — the script has no code path that reads or modifies it.

### Examples

```sh
# Bring a GPU pod up (reuse if one is already running, else create fresh).
./scripts/pod up

# See what exists, including stopped/exited pods.
./scripts/pod status

# Tear everything down (volume is untouched).
./scripts/pod down

# Watch an already-running pod, checking in every 10m with a 2m grace window.
CHECKIN_INTERVAL=600 GRACE=120 ./scripts/pod watch
```

## `comfyui-bootstrap` — install & start ComfyUI on the pod

`comfyui-bootstrap` installs ComfyUI onto the Global Volume (around the already-populated
`models/` tree) and starts it. **Run it on the pod, over SSH — not on the Mac** (unlike
`pod`, it operates on pod-local paths, not the RunPod API):

```sh
scp -P <PORT> -i ~/.ssh/id_ed25519 scripts/comfyui-bootstrap root@<IP>:/root/comfyui-bootstrap
ssh <pod-id>@ssh.runpod.io -i ~/.ssh/id_ed25519 'bash /root/comfyui-bootstrap'
```

Idempotent: re-running it against a pod where ComfyUI is already installed just starts the
server (or no-ops if it's already running). Listens on `127.0.0.1:8188` — access it via an
SSH tunnel, matching the existing access pattern.

"Already installed" is verified (main.py present, plausible file count), not assumed from a
bare `.git` check — a 2026-09-19 crash-loop incident (old template, see `pod`'s `TEMPLATE_ID`
docs) left a partial, broken `.git` dir on the volume with no `main.py`. If the checkout looks
incomplete, the script clears everything under `COMFY_ROOT` except `models/input/output/temp/
user` and reinstalls from scratch, rather than trusting the partial state.

| Variable | Default | Controls |
|----------|---------|----------|
| `WORKSPACE`           | `/workspace` | Global Volume mount root. |
| `COMFY_ROOT`           | `$WORKSPACE/runpod-slim/ComfyUI` | ComfyUI install dir, on the volume. |
| `CONTAINER_DATA_DIR`  | `/comfy-data` | Ephemeral root (container disk) for the venv, output, input, temp, user, and log dirs. |
| `VENV_ROOT`             | `$CONTAINER_DATA_DIR/venv` | Python venv — **container disk, not the volume** (GeeseFS is poor at the small-file I/O a venv does; rebuilt per pod with `--system-site-packages` so it reuses the base image's torch/CUDA instead of re-downloading it). |
| `LISTEN_ADDR` / `PORT` | `127.0.0.1` / `8188` | ComfyUI bind address/port. |
| `COMFYUI_REPO`         | `https://github.com/comfyanonymous/ComfyUI.git` | Git remote to install from. |
| `COMFYUI_REF`           | *(unset)* | Optional tag/commit to pin; tracks the default branch HEAD otherwise. |
| `STAGED_MODELS`         | `0` | If `1`, start ComfyUI with `--models-directory` pointed at `STAGED_MODELS_DIR` instead of the volume's `models/` tree — part of the staged-model-load A/B test, see [runpod-setup-context.md](../packages/visual-generation/runpod-setup-context.md) and `stage-models` below. Refuses to start if `STAGED_MODELS_DIR` doesn't exist or is empty. |
| `STAGED_MODELS_DIR`     | `$CONTAINER_DATA_DIR/staged-models` | Where the staged copy lives (must match `stage-models`' own default/override). |
| `RESTART`               | `0` | If `1` and ComfyUI is already running, stop it first instead of the default no-op — needed to actually switch `STAGED_MODELS` on an already-running pod. |

See the header comment in the script for the full rationale (why the venv and ComfyUI's
output/input/temp/user dirs must stay off the volume). Whenever a running instance is found
(restarting or not), the script logs which models directory it was actually launched against
(read from `/proc/<pid>/cmdline`, not assumed) — so a stale `STAGED_MODELS` mismatch is
visible rather than silent.

## `stage-models` — copy models onto the container disk (A/B test tooling)

`stage-models` copies a named set of model files from the Global Volume onto the container
disk, timing every file — the "copy first" half of testing whether the volume's slow
effective cold-load rate is a FUSE/mmap access-pattern problem rather than a raw-throughput
one. See [runpod-setup-context.md](../packages/visual-generation/runpod-setup-context.md)'s
"Staged-model-load A/B test" section for the hypothesis, the decision thresholds fixed before
running it, and the full protocol. **Run it on the pod, over SSH — not on the Mac** (same
operating model as `comfyui-bootstrap`):

```sh
scp -P <PORT> -i ~/.ssh/id_ed25519 scripts/stage-models root@<IP>:/root/stage-models
ssh root@<IP> -p <PORT> -i ~/.ssh/id_ed25519 'bash /root/stage-models wan-t2v'
```

**Read-only against the volume** — it only ever reads from `$WORKSPACE` and writes under
`$STAGED_MODELS_DIR` on the container disk; nothing under `$WORKSPACE` is ever written,
renamed, or deleted. Idempotent: re-running skips any file already staged at the correct size.

```
./stage-models <zimage|wan-t2v|wan-i2v|all>
```

| Set | Contents | Approx. size |
|---|---|---|
| `zimage`  | Z-Image-Turbo: unet + qwen_3_4b text encoder + ae.safetensors VAE | ~19.1 GiB |
| `wan-t2v` | Wan 2.2 T2V: high/low noise experts + umt5_xxl encoder + wan_2.1_vae + t2v lightx2v LoRAs | ~34 GiB |
| `wan-i2v` | Wan 2.2 I2V: high/low noise experts + umt5_xxl encoder + wan_2.1_vae + i2v lightx2v LoRAs (encoder/VAE shared with `wan-t2v`) | ~34 GiB |
| `all`     | Every file above, deduped | ~83.5 GiB |

File lists are derived verbatim from `runpod-setup-context.md`'s "Currently installed"
section — if a listed file is missing on the volume, the script fails loudly naming it rather
than silently skipping it (a signal the volume's actual contents have drifted from that doc).

| Variable | Default | Controls |
|----------|---------|----------|
| `WORKSPACE`          | `/workspace` | Global Volume mount root. |
| `COMFY_ROOT`          | `$WORKSPACE/runpod-slim/ComfyUI` | Source models live under `$COMFY_ROOT/models/`. |
| `CONTAINER_DATA_DIR` | `/comfy-data` | Ephemeral root, container disk (matches `comfyui-bootstrap`'s var of the same name/default). |
| `STAGED_MODELS_DIR`  | `$CONTAINER_DATA_DIR/staged-models` | Destination for the staged copy. |

Before copying, it `stat`s every file's real size (never hardcoded) and refuses clearly, with
both numbers, if the set won't fit on the container disk's free space — and always prints the
container disk's total size regardless.
