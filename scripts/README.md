# scripts

Operational helpers for agent-stack.

## `pod` — RunPod lifecycle controller & idle-cost watchdog

`pod` manages the **visual-generation** ComfyUI pod on RunPod: an RTX PRO 6000 (Blackwell)
GPU in the **US-NE-1** datacenter, backed by the persistent **gen-usne1** network volume. It
both drives the pod's lifecycle and guards against runaway idle GPU cost.

### Why create/delete, not start/stop

RunPod pins a **stopped** pod to its original physical host. For a scarce GPU like the
PRO 6000, that host's GPUs are almost always taken by the time you'd resume — so `pod start`
reliably fails with *"not enough free GPUs on the host machine,"* and stopped pods can be
reclaimed out from under you anyway.

So this script never starts or stops. It **creates a fresh pod** each time (which RunPod is
free to schedule onto *any* host with capacity) and **deletes** it when you're done. This is
safe because the **gen-usne1 network volume exists independently of the pod and survives
deletion** — all models and data live on the volume. The pod itself is disposable
scaffolding; throwing it away costs nothing but the time to recreate it.

### Verbs

```
./scripts/pod <up|down|status|watch>
```

| Verb | What it does |
|------|--------------|
| `up`     | Ensure a running pod exists. If a pod matching the name is already RUNNING **with a GPU**, reuse it; otherwise create a fresh pod and verify it came up with a GPU attached. A pod that comes up with 0 GPUs is treated as a capacity failure — it's deleted and creation retries (see `CREATE_RETRIES` / `CREATE_RETRY_DELAY`). |
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
| `IMAGE`              | `runpod/comfyui:1.3.0-cuda12.8` | Container image used on create. |
| `GPU_ID`             | `NVIDIA RTX PRO 6000 Blackwell Server Edition` | GPU type to request. |
| `CLOUD_TYPE`         | `SECURE` | RunPod cloud type. |
| `DATACENTER`         | `US-NE-1` | Datacenter id (must match the network volume's region). |
| `NETWORK_VOLUME_ID`  | `3wqkq1t8bq` | Network volume to mount (the gen-usne1 volume). |
| `VOLUME_MOUNT_PATH`  | `/workspace` | Where the volume mounts inside the pod. |
| `CONTAINER_DISK_GB`  | `150` | Container disk size, in GB. |
| `PORTS`              | `8188/http,22/tcp` | Ports exposed on the pod (ComfyUI + SSH). |
| `CREATE_RETRIES`     | `3` | How many times `up` retries on a capacity error. |
| `CREATE_RETRY_DELAY` | `15` | Seconds to wait between create retries. |
| `CHECKIN_INTERVAL`   | `1800` | Seconds between `watch` check-in prompts (30m). |
| `GRACE`              | `180` | Seconds to respond to a `watch` prompt before auto-delete (3m). |

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

- **runpodctl** — installed and authenticated. Verify with `runpodctl doctor`.
- **jq**

```sh
brew install runpod/runpodctl/runpodctl
brew install jq
```

### Safety rules

The script only ever calls `runpodctl pod create` / `delete` / `list` / `get`. It **never**
calls `pod start` or `pod stop`, and **never** any `network-volume` subcommand. The gen-usne1
volume therefore cannot become collateral damage — the script has no code path that reads or
modifies it.

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
