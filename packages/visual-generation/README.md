# visual-generation

A diffusion image/video generation collaborator — prompt-craft, platform tutor,
and generation/iteration over a ComfyUI backend on RunPod. Modeled on
`voiceover-direction` (cost inversion) and `music-curation` (curated memory).

**Status: Phase 2 in progress — data foundation only.** This package currently
contains the storage + retrieval layer:

- `visual_generation_memory` — one Qdrant collection, three memory types
  discriminated by a `memory_type` payload field:
  - `generation` — the core record. Embeds image/keyframe + caption via the
    runtime multimodal surface (`voyage-multimodal-3`). Carries the full settings
    recipe, model/checkpoint, LoRA stack, workflow ref, seed, dimensions,
    asset path, per-run GPU cost, `identity_bearing`, reaction, rating, status,
    and chain lineage. The binary asset is a disk file referenced by
    `asset_path`, never stored in Qdrant.
  - `technique_lesson` — a confirmed lesson learned by doing. Embeds the
    statement (`voyage-3-large`); scope ∈ prompt/settings/workflow/model.
  - `workflow_template` — a reusable parameterized ComfyUI graph + slot map +
    required models. Embeds a short descriptor.
- A local JSON **model/LoRA registry** (the voice-registry analog): concrete
  named assets looked up by name, never embedded. Entries carry an
  `identity_bearing` flag.
- A **three-collection retrieval** composition: own `visual_generation_memory`
  (primary) + `user_knowledge` (`comfyui_mechanics`/`runpod_mechanics`,
  score-boosted) + `tutorial_research`. Each leg degrades silently; usable
  cold-start.

The CLI, the ComfyUI client, the generation turn (`draft`/`generate`/`report`),
`model sync`, and asset writing land in later steps.

## How a generation actually happens (pipeline overview)

End-to-end, producing one image involves five distinct steps, each touching a
different system. It's easy to lose track of which step you're on:

1. **Spin up a RunPod pod** running the ComfyUI template (manual, in the
   RunPod web UI). This is the only step that starts GPU billing — billing
   starts here, not when the agent connects.
2. **`model sync --endpoint <url>`** — the CLI queries the pod's ComfyUI
   `/object_info` endpoint and writes/updates `~/agent-data/visual-generation/models.json`,
   the local registry of checkpoints/LoRAs/VAEs available on that pod.
3. **`workflow register <exported-api.json>`** — register a ComfyUI graph
   (exported in **API format**, not the default Save format — see below) as a
   named, reusable template with an inferred slot map.
4. **`draft` / hand-written `vg-spec`** — produce an entry in a batch file
   (`visual-batch.md`) describing what to generate: prompt, settings,
   `workflow_ref`, seed, dimensions.
5. **`generate <batch.md> --section <id> --endpoint <url>`** — resolves the
   spec's `workflow_ref` to the registered template, applies the slot map to
   fill in the template's graph with the spec's values, sends the resulting
   API graph to ComfyUI, and saves the output image locally.

A generation you create by clicking around in the ComfyUI web UI never
touches steps 2-5 — it's a completely separate path (see "UI generations vs.
CLI generations" below).

## ComfyUI workflow concepts

### Subgraphs

A ComfyUI "subgraph" is a packaged group of nodes collapsed into a single box
in the UI. Z-Image-Turbo ships as a subgraph bundling: `UNETLoader`,
`CLIPLoader`, `CLIPTextEncode`, `ModelSamplingAuraFlow`, `ConditioningZeroOut`,
`EmptySD3LatentImage`, `KSampler`, `VAELoader`, `VAEDecode`. The subgraph only
exposes a curated subset of these nodes' inputs as widgets on the collapsed
box (via a `proxyWidgets` list) — for Z-Image-Turbo that's `width`, `height`,
`text`, `unet_name`, `clip_name`, `vae_name`. Everything else (seed, steps,
cfg, sampler, scheduler, denoise — all on the inner `KSampler`) is hidden
unless you expand the subgraph (double-click it, or use its expand icon) to
see the nodes inside.

This matters because **the values `workflow register` infers a slot map from
come from the full exported graph, including the nodes hidden inside
subgraphs** — the slot map can target `30:44` (an inner KSampler) even though
that node never appears as a widget on the collapsed box.

### Z-Image-Turbo: what it is and why its settings are different

Z-Image-Turbo is a **CFG-distilled "turbo" diffusion model**. Distillation
trains the model to produce a finished image in far fewer steps and at far
lower guidance strength than a standard SDXL checkpoint. Its expected recipe
is approximately:

- `cfg`: ~1 (NOT 7)
- `steps`: ~8 (NOT 20-30)
- `sampler`: `res_multistep`
- `scheduler`: `simple`

Feeding it a standard-SDXL recipe (cfg 7, 30 steps, `dpmpp_2m`/`karras`) is a
real failure mode — over-driving a distilled model's guidance massively
oversaturates and distorts the image (this is exactly what happened in the
"sports bar" generation; see Troubleshooting below).

### KSampler parameters

The `KSampler` node (whether visible on the canvas or hidden inside a
subgraph) is where the diffusion denoising loop actually runs. Its inputs:

- **`seed`** — the random seed for the initial noise. Same seed + same
  settings + same model = reproducible output. Different seed = a different
  image from the same prompt/settings.
- **`steps`** — how many denoising iterations to run. More steps generally
  means more refined detail, up to a point of diminishing returns; turbo/
  distilled models need far fewer steps than standard checkpoints.
- **`cfg`** (classifier-free guidance) — how strongly the model is pushed to
  match the prompt vs. its own unconditioned prediction. Higher = more
  literal/prompt-faithful but can oversaturate, posterize, or distort;
  lower = more "natural" but can drift from the prompt. Distilled/turbo
  models are tuned for very low cfg (≈1) because the distillation already
  bakes in strong prompt adherence.
- **`sampler`** — the numerical algorithm used to step through the denoising
  process (e.g. `dpmpp_2m`, `res_multistep`, `euler`). Different samplers
  trade off speed, smoothness, and how well they pair with a given scheduler.
  A sampler/model mismatch is a common cause of bad output even when every
  other setting looks reasonable.
- **`scheduler`** — controls how the noise level is spaced across the steps
  (e.g. `karras`, `simple`). Paired with the sampler; the two are usually
  chosen together as a matched combination recommended for a given model.
- **`denoise`** — how much of the input latent gets denoised, from 0 (no
  change) to 1 (fully regenerated). For text-to-image from an empty latent
  this is normally 1.

`vae_name` (on `VAELoader`) is not a KSampler parameter but is part of the
same pipeline: it's the model used for the final latent→pixel decode step
(`VAEDecode`) that turns the denoised latent into the actual image.

### Save (workflow) format vs. Export (API) format

ComfyUI has two very different "export" actions and only one of them is
usable by `workflow register`:

- **Save (workflow)** — the UI/editor format. Includes node positions, UI
  metadata, and subgraph definitions as ComfyUI's editor represents them.
  Good for re-opening in the ComfyUI UI; **not** what `workflow register`
  expects.
- **Export (API)** — a flat `{node_id: {class_type, inputs, _meta}}` JSON
  structure with no UI metadata, including hidden subgraph internals
  flattened into addressable node IDs (e.g. `30:44`, `30:45`). **This is the
  format `workflow register` requires.**

If you register the Save-format file, slot inference will fail or produce a
nonsensical/empty slot map because the node shapes don't match what the
inference code expects.

## visual-batch.md anatomy

`visual-batch.md` is a markdown file that's human-readable (it renders as a
normal document with a title and a prose paragraph) but also carries
machine-readable metadata in HTML comments, which markdown renderers ignore
but the `visual-generation` CLI parses as JSON:

- **`<!-- vg-batch: {...} -->`** — one per file, batch-level metadata:
  `project`, `created_at`, `source_path` (the file this batch was derived
  from, e.g. `celeste-visual-batch.md`).
- **`<!-- vg-spec: {...} -->`** — one per generation spec (one per "shot" /
  scene). Carries: `spec_id` (UUID), `negative_prompt`, `settings` (the
  steps/cfg/sampler/scheduler dict — see KSampler params above), `model`,
  `seed`, `seed_strategy`, `width`, `height`, `lora_stack`, `workflow_ref`,
  `project`, `identity_bearing`, `rationale` (free-text explanation of why
  these choices were made), `created_at`.
- The plain prose paragraph below each `vg-spec` is the actual image prompt
  text sent to the model.

### `workflow_ref`

`workflow_ref` is the link between a `vg-spec` and a **registered workflow
template** (by name, e.g. `"visual-workflow"` — the name given to
`workflow register`). At `generate` time:

- `workflow_ref` is looked up against the templates registered via
  `workflow register`.
- If `workflow_ref` is `null`, or the named template isn't registered, the
  spec is **skipped** with `Skipped (no resolvable workflow template): <spec_id>`
  — `generate` has nothing to map the spec's settings onto and silently
  drops it from the run rather than failing the whole batch.
- A malformed value (e.g. doubly-quoted JSON like `""visual-workflow""`) also
  breaks parsing — this can even change the `spec_id` that gets reported,
  because the spec falls back to a freshly-generated id when its metadata
  fails to parse cleanly.

### Slot maps

A "slot map" is what `workflow register` infers when it registers a template:
a mapping from abstract spec fields (seed, steps, cfg, sampler, scheduler,
denoise, positive prompt, width/height, unet/checkpoint) to the specific
node IDs and input keys in the registered API graph where those values need
to be written. For the `visual-workflow` template registered in this project:

| Spec field(s)                                  | Graph location        |
|-------------------------------------------------|-----------------------|
| seed, steps, cfg, sampler, scheduler, denoise   | node `30:44` (KSampler) |
| positive prompt                                 | node `30:45.text`      |
| width, height                                   | node `30:41`           |
| unet/checkpoint                                 | node `30:46.unet_name` |

`generate` uses this map to take a `vg-spec`'s values and produce a concrete,
ready-to-run ComfyUI API graph.

## Operational commands

### `model sync --endpoint <url>`

Queries the live ComfyUI pod's `/object_info` for what checkpoints, LoRAs,
and VAEs are actually loaded/available, and writes that into the local
registry `~/agent-data/visual-generation/models.json`. Run this after
spinning up a pod and before registering workflows or drafting specs that
reference specific models — otherwise `draft` may propose models that don't
exist on the pod you're about to use.

### `workflow register <exported-api.json> [--name N]`

Registers a ComfyUI graph (must be **Export (API)** format — see above) as a
named, embedded (via Voyage AI), semantically-searchable template, with an
inferred slot map (see above). Requires a working `VOYAGE_API_KEY` — if
`.env` stores it as a 1Password reference
(`op://Personal/VOYAGE_API_KEY/credential`), prefix the command with
`op run --env-file=/Users/chrisbryant/projects/agent-stack/.env --` so the
reference is resolved to a real key before the CLI runs.

### `generate <batch.md> --section <id>|--all --endpoint <url> [--max-session-cost N]`

Resolves each targeted spec's `workflow_ref` → template → slot map, builds
the concrete API graph, sends it to the ComfyUI pod at `--endpoint`, and
saves the resulting image locally under
`~/agent-data/visual-generation/assets/<project>/<generation_id>.png`.

`--max-session-cost <N>` is a **soft/local cost ceiling**, checked before
each individual generation in the run:

- It is **not** a live RunPod balance check — it's a local running total
  based on `--gpu-rate` × elapsed time (an approximation; real billing
  starts at pod spin-up, before the agent connects).
- If the next generation would push the running total over the ceiling, the
  drain **stops early**: the result is reported with `status: partial` and
  `drained: False`, and any specs after that point are left ungenerated.
- It does **not** stop the pod, and does **not** stop GPU billing — the pod
  keeps running and accruing cost until you stop it yourself in the RunPod UI.

## UI generations vs. CLI generations

These are two completely independent paths that happen to produce images
from the same ComfyUI pod, and it's easy to conflate them:

| | Manual ComfyUI UI generation | `generate` CLI run |
|---|---|---|
| Triggered by | Clicking "Queue" in the ComfyUI web UI | `visual-generation generate ...` |
| Settings source | Whatever values are currently on the node widgets (defaults, or whatever you last edited) | The resolved `vg-spec` from `visual-batch.md`, mapped through the registered template's slot map |
| `vg-spec`/`vg-batch` involved? | No — the UI has no concept of these | Yes — every generation traces back to a specific `spec_id` |
| Where the output is saved | On the **RunPod pod's storage volume** (ComfyUI's default output directory, viewable via FileBrowser) | Downloaded and saved **locally** to `~/agent-data/visual-generation/assets/<project>/<generation_id>.png` |
| Recorded in the agent's memory? | No | Yes — as a `generation` record with full recipe, cost, lineage |

In this project's session: the **first** image (sporty-looking woman) was a
manual UI generation using whatever the Z-Image-Turbo node's prompt/defaults
were at the time — it lives only on the pod's volume. The **second** image
(the storybook sports-bar scene, oversaturated/red) was the `generate` CLI
run against `visual-batch.md`'s `vg-spec` — it was downloaded to the local
Mac path above.

### Viewing pod-side images after stopping the pod

Images saved to the pod's volume (manual UI generations) are only reachable
while the pod (or its volume, mounted to a running pod) is accessible —
either by restarting the ComfyUI pod, or via FileBrowser if it's running.
Locally-saved CLI generations remain on your Mac regardless of pod state.

## Troubleshooting: oversaturated / distorted output

**Symptom:** a `generate` run completes successfully (no errors), but the
output image is badly oversaturated, blown-out red/black, and doesn't
resemble the prompt.

**Cause:** the spec's `settings` (in `vg-spec`) were written for a standard
SDXL recipe (`cfg: 7.0`, `steps: 30`, `sampler: dpmpp_2m`,
`scheduler: karras`) — reasonable defaults when `model: null` and no specific
checkpoint is known — but the slot map applied them to **Z-Image-Turbo**, a
CFG-distilled model expecting `cfg ≈ 1`, `steps ≈ 8`, `sampler: res_multistep`,
`scheduler: simple`. Driving a distilled model at cfg 7 massively over-applies
guidance, which is what produces the oversaturated/distorted result.

**Fix options:**

1. Edit the `vg-spec`'s `settings` to match Z-Image-Turbo's recipe (`cfg: 1`,
   `steps: 8`, `sampler: "res_multistep"`, `scheduler: "simple"`) and
   re-run `generate`.
2. Or, if you want to keep the SDXL-oriented recipe as written, swap to a
   non-turbo SDXL checkpoint (the spec's own `rationale` suggests candidates
   like "Dreamshaper XL" or "Counterfeit XL") — run `model sync` again after
   loading that checkpoint on the pod so it's in the registry.

## RunPod pod lifecycle & costs

- **Billing starts at pod spin-up**, in the RunPod web UI — not when any CLI
  command runs. `model sync`, `workflow register`, and `generate` all assume
  a pod is already up and reachable at `--endpoint`.
- **Stopping a pod can release its GPU reservation.** Restarting may then
  show "Your Pod's GPUs are no longer available" — this is GPU reallocation
  by RunPod's scheduler, not a credits/billing problem. Options when this
  happens: "Automatically migrate your Pod data" (gets you a *new* pod ID and
  new proxy URLs — anything bookmarked to the old pod's URL breaks, and
  migration takes time before billing/GPU access resumes on the new pod),
  start on CPU (no GPU generation possible), or wait for GPU availability to
  return to the original pod.
- **Observed real cost** for this session's work (Step 11, RunPod ComfyUI
  template, A100 SXM): ~$3.67 total, dominated by two A100 SXM GPU charges
  (~$0.553 and ~$3.049) plus a 100GB storage volume charge — against a $20
  GPU compute credit balance. RunPod's Audit logs, Cost centers/Invoices,
  Account balance, and Billing explorer (Cloud GPU/CPU/Storage breakdown) are
  the places to check actual spend; the CLI's `--max-session-cost` figure is
  a local estimate only and won't match these exactly.

## FileBrowser (pod file access)

FileBrowser (typically on port 8080 of the pod) is a **separate login from
your RunPod account** — it is not the same credentials.

- **Default credentials for RunPod's official ComfyUI template:**
  `admin` / `adminadmin12` (the `$FB_USERNAME`/`$FB_PASSWORD` env vars are
  often empty on the pod, so the documented default is what works, not
  `admin`/`admin`).
- **To change the password:** either use FileBrowser's own Settings UI after
  logging in, or from the pod's web terminal:
  `filebrowser users update admin --password <newpassword>`
- **Where to look for generated images in FileBrowser:** manual UI
  generations land in ComfyUI's output directory on the pod's volume — browse
  to ComfyUI's `output/` folder (not the `assets`/model folders) to find them.

## FAQ

Common questions and knowledge gaps about this agent. Add entries as they come up — capture anything that surprised you about its capabilities, flags, costs, or where its outputs land.

<!-- Template for a new entry:
### Q: <the question, as you'd actually ask it>
<the answer, with the exact command/flag/path where relevant>
-->

**Where do this agent's files go?**

`-o` outputs are director-owned working files — put them in your per-project folder (`~/agent-projects/<project-slug>/`). Machine-managed outputs (sources, audio, stills, qdrant) go under `~/agent-data/`, and run reports auto-write to `~/obsidian/agent-reports/`. Canonical, single-source-of-truth detail: [File organization](../../README.md#where-should-project-files-live) in the repo root README.
