---
title: "visual-generation — RunPod Global Volume Migration & Recovery"
date: 2026-09-20
type: handoff
project: agent-stack
package: visual-generation
status: complete
purpose: session-narrative-for-comprehension-quizzing
tags:
  - handoff
  - visual-generation
  - runpod
  - comfyui
  - global-volume
---

# visual-generation — RunPod Global Volume migration & recovery (2026-09-20)

This document is a narrative record of one session's work, written to explain *why* each
decision was made, not just what changed. It's meant to be read by an LLM (paste it into a
chat) that will then quiz the person who did this work, to check their own understanding and
surface gaps — so it leans on reasoning and cause-and-effect rather than a terse changelog.

## 1. Why this session happened: the volume was gone

`visual-generation` drives a user-supplied RunPod ComfyUI pod for image/video generation. The
models, the ComfyUI install, and everything persistent live on a RunPod storage volume that
survives the pod itself being deleted and recreated (pods are treated as disposable — see
§2). That volume had been a **regional network volume** (`gen-usne1`, locked to the US-NE-1
datacenter). It disappeared: the RunPod account's balance hit zero while the user was away
for an extended period, and RunPod reclaims an unfunded volume after it sits empty too long.
The user has since set up balance auto-reload to prevent that specific trigger recurring, but
the *recovery process* — rebuilding a working pod against a rebuilt volume — is what this
session actually did, and it surfaced enough real bugs that it's worth understanding deeply
rather than just replaying the commands.

The replacement is a RunPod **Global Volume**: region-independent (any datacenter can attach
it, unlike the old volume which pinned the pod to one region), elastic (billed on stored
data, nothing to provision or run out of — the old volume's "disk quota exceeded" failure
class doesn't exist for this one), and backed by object storage through a FUSE layer
(`fuse.geesefs`). That FUSE detail matters a lot later in this document — it's the reason
several fixes were needed, because a FUSE-backed object store doesn't behave like a normal
disk for certain operations.

## 2. Why pods are create/delete, not start/stop — this shaped the whole recovery

RunPod pins a *stopped* pod to its original physical host. For a GPU as scarce as the one
this project uses (RTX PRO 6000 Blackwell), that host's GPUs are almost always already taken
by the time you'd resume, so `pod start` reliably fails, and a stopped pod can be reclaimed
out from under you anyway. `scripts/pod` therefore never stops/starts — it always **creates a
fresh pod** (schedulable onto any host with capacity) and **deletes** it when done. This is
only safe because everything that matters lives on the volume, independent of the pod's
lifecycle. Understanding this is what makes the rest of the recovery make sense: rebuilding
"the pod" was never the hard part (that's one command); rebuilding what runs *on* a fresh pod
each time is what took the session.

## 3. The crash-loop incident — root cause and the three-layer fix

The first attempt to bring a pod up used the old default: a RunPod *template* called
`agent-stack`/`cnne9dp3rt`, built on the `runpod/comfyui` image, which has ComfyUI **baked
into the image** and starts it automatically on boot. That was the correct choice for the old
regional volume. Against the new Global Volume, it crash-looped — repeated restarts at full
GPU cost, ~$2/hr, with zero processes actually running.

**Root cause, found by reading the image's actual entrypoint source (not guessed):** the
image's startup script runs `rsync -a --delete` to sync its baked-in ComfyUI files onto
`/workspace` on every boot. `rsync -a` (archive mode) needs to set file ownership (`chown`).
The Global Volume's FUSE layer has no real permission model — every file reports owner
`nobody:nogroup` no matter what's requested, and an explicit `chown`/`chmod` call against it
fails with `EPERM` (Operation not permitted). The entrypoint script has `set -e`, so the first
failed `chown` kills the whole script — which means the container never finishes booting,
RunPod restarts it, and the same thing happens again, forever, at full cost.

The fix was three layers, each catching a different failure mode:

1. **Prevention** — changed the default `TEMPLATE_ID` to `runpod-torch-v280` (a plain PyTorch
   template/image with no baked ComfyUI, no rsync-on-boot entrypoint at all). ComfyUI is now
   installed separately, on purpose, by a new script (`scripts/comfyui-bootstrap`) run
   manually over SSH after the pod is up — so nothing tries to write ownership metadata to
   the volume during pod boot.
2. **A hard guard** — `scripts/pod` now refuses outright, before even attempting to create a
   pod, if `TEMPLATE_ID` resolves to the known-bad id, or (when no template is set) if
   `IMAGE` matches the `runpod/comfyui` repo. This exists specifically so a *stale* `.env`
   value (exactly what caused the first real attempt today to fail — the safer script default
   didn't apply because `.env` still explicitly set the old template) fails loudly and
   immediately, instead of silently crash-looping again. Caveat, stated rather than
   overclaimed: this only catches the literal known-bad template id — a renamed or
   re-created template with the same underlying image wouldn't be caught, since RunPod
   doesn't expose a confirmed way to resolve a template id to its image without an extra,
   unverified API call.
3. **Bootstrap hardening** — `scripts/comfyui-bootstrap` (the new install script) avoids the
   same class of operation entirely: it clones ComfyUI to a scratch directory on the
   *container disk* (never the volume — git also needs atomic rename, which the volume
   doesn't support either), then copies files onto the volume with plain `cp -r` — no `-p`,
   no `-a`, nothing that tries to preserve ownership/permissions and would trip the same
   `EPERM`.

## 4. The health-check saga — why `.runtime` was wrong and `uptimeSeconds` was right

Even with the template fixed, `create_pod()`'s own check (pod status is `RUNNING`, GPU count
≥ 1) isn't enough to detect a crash-loop — during the incident, the pod reported exactly that
for its *entire* lifetime while the container inside kept restarting. So a second check was
added: after creating a pod, poll it for some signal that it's genuinely healthy, not just
nominally running, and delete it automatically rather than leave a broken pod billing
unattended.

The first version polled a field called `.runtime`, based on this repo's own prior
documented behavior. That field turned out **not to exist at all** in this account's actual
`pod get` responses (confirmed by reading a live JSON response, not assumed) — meaning that
check could never pass, and it deleted a pod that was actually fine. The real, confirmed field
is `uptimeSeconds`, found the same way (reading an actual live response). The check now polls
that instead: a drop in `uptimeSeconds` between polls means the container restarted (a
crash-loop, caught immediately without waiting out the full timeout); a value that goes
nonzero and doesn't drop means healthy.

One deliberate design point worth understanding: this check does **not** wait for ComfyUI
itself to be reachable on port 8188. That's intentional — with the new architecture, nothing
serves 8188 until the separate `comfyui-bootstrap` step runs manually afterward, so gating pod
creation on "is ComfyUI responding" would make every fresh pod fail this check by design. The
health check's job is narrower: confirm the *container* isn't crash-looping, not confirm the
*application* is up yet.

## 5. The partial-install bug — why checking for `.git` wasn't enough

`comfyui-bootstrap` is meant to be idempotent — safe to re-run, skipping install if ComfyUI is
already there. The first version checked for that by testing whether a `.git` directory
existed at the install path. That was fooled by debris left behind by the original
crash-loop: the old template's `rsync` had gotten partway through syncing `.git/objects/*`
onto the volume before dying (repeatedly), so a `.git` directory existed, but no working
files (`main.py`, etc.) did. The script reported "already installed, skipping" and then
immediately failed its own post-install verification.

The fix replaced the bare `.git` check with a real completeness check (does `main.py` exist,
is the file count plausible) — the same check already used to verify a *fresh* install
succeeded — and added a cleanup step: if the existing install looks incomplete, clear
everything under the ComfyUI directory except `models/`/`input/`/`output/`/`temp/`/`user/`
(never touch the populated model tree) before reinstalling from scratch, rather than trying to
"resume" an untrusted partial state.

## 6. Cold-vs-warm model load times — not a bug, a real cost characteristic

Once ComfyUI was actually installed and running, the first generation attempt appeared to
hang — 0% GPU utilization, no progress, for several minutes. It wasn't stuck: model weights
live on the Global Volume and have to stream in over the FUSE layer into VRAM before any
compute can happen, and that's slow the *first* time a given model is used on a fresh pod.
Once loaded, the weights stay resident in VRAM (this GPU has 97GB, comfortably holding
several large models at once) and subsequent generations against the same model are fast.

Measured directly, first generation vs. the very next one (different seed each time, to force
a genuine recompute rather than a hit against ComfyUI's own node-level result cache):

| Model | Cold (first generation) | Warm (next generation) |
|---|---|---|
| Z-Image-Turbo (image, ~19.5GB combined weights) | 477s (~8 min) | 2.03s |
| Wan 2.2 T2V 14B lightx2v (video, ~34GB combined weights) | 2339s (~39 min) | 8.55s |

One anomaly, observed but not explained: Wan's two ~13.6GB diffusion model files, loaded
back-to-back in the same job, took very different times (395s vs. 1351s — a 3.4x slowdown on
the second one) despite being the same size. Possible causes weren't confirmed — storage
throughput variance and a dynamic-VRAM-loading interaction are both plausible, neither is
proven.

The practical implication: because pods are always created fresh (never stopped/resumed, see
§2), this cold-load cost is paid again on *every new pod*, the first time each model is used
on it — several minutes for stills, the better part of an hour for video. That's a real
planning factor, not a one-time inconvenience from today.

## 7. SSH/tunnel drops — a separate, unrelated annoyance worth understanding

While waiting through the long cold loads, SSH sessions (and the browser tunnel riding on
top of one, `ssh -L 8188:127.0.0.1:8188 ...`) kept dropping with `Connection reset by peer` /
`Broken pipe`. This is unrelated to the Global Volume or ComfyUI — it's a NAT/firewall/proxy
somewhere on the network path silently killing a connection that goes quiet for too long,
which happens easily here because the terminal itself sees no traffic while you're just
watching a slow load in the browser. Fixed with client-side SSH keepalives
(`ServerAliveInterval 30` / `ServerAliveCountMax 3` in `~/.ssh/config`), which make the
connection send small pings so it never looks idle. Important related fact: the ComfyUI
server process itself is started with `nohup ... & disown`, so it's completely unaffected by
a dropped SSH session — a "Prompt execution failed" / "Reconnecting" popup in the browser
right after a drop is the browser losing its own connection, not a failed generation; the job
kept running server-side and usually completes fine.

## 8. End-to-end validation

Both models were confirmed working correctly against the rebuilt Global Volume: Z-Image-Turbo
produced a correct still image from its template prompt, and Wan 2.2 T2V produced a correct
~2-second video clip (a fox walking through snow, matching the prompt) using the project's own
documented lightx2v 4-step recipe (loaded from the repo's pinned workflow file, verified by
checking the LoRA loader nodes' filenames against what the recipe's own README documents). The
pipeline is fully operational again as of this session.
