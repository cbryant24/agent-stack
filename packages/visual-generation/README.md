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

## Glossary — plain language

Short, jargon-free definitions. The most important one is the first.

- **The pipeline layers (the mental model).** ComfyUI is the **workbench**
  (camera body) you run things in; SDXL / Flux / Z-Image are **base models**
  (lens mounts) — the engines; checkpoints / LoRAs / ControlNets / IP-Adapter
  are **add-ons built for one specific mount**. "The SDXL/Flux ecosystem" = a
  base model plus all the add-ons built for it — it is NOT a UI. ComfyUI runs
  all of them. See [How a generation actually happens](#how-a-generation-actually-happens-pipeline-overview).
- **checkpoint** — one complete trained model, the whole engine (a finished
  "lens"). Name comes from training save-points (like a save-game). Big
  (~2–7 GB). Z-Image ships its parts as separate files (UNET + CLIP + VAE)
  rather than one bundled checkpoint.
- **UNET / diffusion model** — the part that does the denoising.
  **CLIP / text encoder** — the part that reads your prompt (Z-Image uses a
  4 GB Qwen encoder). **VAE** — converts between pixels and the latent the model
  works in (VAEEncode = pixels→latent, VAEDecode = latent→pixels). See
  [KSampler parameters](#ksampler-parameters).
- **LoRA** — a small trained add-on stacked on a checkpoint to teach it a
  person/object/style (a "screw-on filter" — can't work alone). Needs ~15–80
  training images.
- **denoise (0–1)** — how much of a starting image to dissolve into static
  before rebuilding it; like dissolving a photo into haze and re-developing.
  1.0 = brand-new image (text-to-image), low = small tweak. Z-Image img2img
  works at ~0.4–0.7 and breaks above ~0.85.
- **img2img** — re-roll a whole image from an existing one. **inpainting** —
  mask a region and regenerate only that area. **ControlNet** — copy structure
  (pose/depth/edges) from a reference. **IP-Adapter / InstantID / FaceID** —
  zero-shot "make it look like this person/object from one photo" (NOT available
  on Z-Image; SDXL/Flux only).
- **latent** — the compressed space the model actually works in.
  EmptySD3LatentImage = a blank latent for text-to-image; VAEEncode produces a
  latent FROM an image for img2img.
- **slot map** — the table mapping a spec's fields (seed/steps/cfg/prompt/etc.)
  to the exact node + input in a registered workflow graph. **workflow
  template** — a registered, reusable graph + its slot map. **subgraph** — a
  bundle of nodes collapsed into one box (the Z-Image template is one);
  right-click → Unpack to edit the nodes inside. See [Slot maps](#slot-maps) and
  [Subgraphs](#subgraphs).

## What to know — gaps worth closing

Orientation for a newcomer operating this agent:

- **Diffusion is iterative, not one-shot.** Changing what's in a frame
  (wardrobe, pose, layout, position) is normal practice via img2img / inpaint /
  ControlNet / LoRA — plan for iteration, not a single perfect generation.
- **Reference images map to technique by count and subject:** 1 → ControlNet
  structure; ~15+ → a LoRA; stylized character 20–40, photoreal person 70–80.
  (A dedicated refinement/reference research doc will be cross-linked here if it
  lands in the repo.)
- **Z-Image-Turbo does img2img, inpaint, ControlNet, and LoRA — but NOT
  IP-Adapter/InstantID** (one-photo zero-shot identity). That capability needs
  SDXL/Flux.
- **This agent was text-to-image only.** Refinement (img2img/inpaint + iterate-
  on-a-prior-generation via a spec `source`) has been added in code — the
  ComfyUI graphs to back it still need building/registering (see
  [workflow register](#workflow-register-exported-apijson---name-n)).
- **Pod realities:** a new pod = a new proxy URL (update `$EP`) AND a fresh
  ComfyUI that does NOT carry over a workflow you built in the browser — so
  export ([API format](#save-workflow-format-vs-export-api-format)) +
  `workflow register` to make a graph permanent. Models on a network volume can
  load slowly/stall vs local container disk. See
  [RunPod pod lifecycle & costs](#runpod-pod-lifecycle--costs).

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

## Troubleshooting — plain-language guide

A friendly guide for operators who run this agent but aren't diffusion experts.
Start here when an image doesn't come out the way you expected — it helps you
work out *which* of the five steps went sideways before you dig into the
detailed sections below. (Still stuck after this? Check the [FAQ](#faq).)

### Explain Like I'm Five

The whole pipeline is like ordering a custom drawing from a rented art studio.
There are five steps, and when something looks wrong it's almost always *one* of
them that broke:

- **Spin up a RunPod pod** = renting a computer that has a powerful graphics
  card (a GPU) bolted in. The rental meter starts the instant you turn it on —
  not when the agent connects.
- **`model sync`** = telling the agent which art supplies (the *models* — the
  trained "brains" that actually draw) that rented computer has on hand.
- **`workflow register`** = teaching the agent the layout of the recipe card, so
  it knows which blank to write each setting into.
- **`draft` / `vg-spec`** = writing the order ticket: what to draw, at what
  settings, and what size.
- **`generate`** = handing the ticket to the kitchen and waiting for the plate
  to come back.

So when a picture comes out wrong, ask: was the order ticket wrong (the
`vg-spec` settings)? Did the studio not have the right supplies (`model sync`)?
Was the recipe card misread (`workflow register`)? Or did the plate never come
back from the kitchen (`generate`)?

### When something goes wrong

**Image is oversaturated, blown-out red, or distorted.** The order ticket asked
for standard-SDXL settings (`cfg 7`, ~30 steps, `dpmpp_2m`, `karras`), but the
studio's actual supply is Z-Image-Turbo — a "turbo" model (a *distilled* model
trained to draw in far fewer steps) that wants roughly `cfg 1`, 8 steps,
`res_multistep`, `simple`. Over-driving a turbo model scorches the image. → See
[Troubleshooting: oversaturated / distorted output](#troubleshooting-oversaturated--distorted-output).

**Run ends instantly with "Generated: 0 / Skipped" and no error.** There are two
different kinds of "skip", and they mean opposite things:

- **Plan-phase** — `Skipped (no resolvable workflow template)`: the ticket's
  `workflow_ref` didn't match any registered recipe card, so *nothing was ever
  sent to the pod*. Re-check the `workflow_ref` name and that you ran
  `workflow register`. → See [`workflow_ref`](#workflow_ref).
- **Spend-phase** — a bare `Skipped:` line: the job *was* sent to the pod, but
  no finished image came back within the polling window, so the ticket was
  dropped. This usually means a hang (next entry).

**Generation seems to "hang" for ~10 minutes, then skips.** Some image
resolutions make Z-Image-Turbo wedge and never finish. In this session
`1152x896` hung indefinitely, while `1024x1024` with otherwise identical
settings rendered in seconds. The job sits in the pod's running queue, never
lands in history, the poller hits its 600-second timeout, and the ticket gets
skipped. **Fix:** use a resolution the model supports — `1024x1024` is confirmed
working. To tell a real hang from "still working", use the [First-aid
checklist](#first-aid-checklist) below: a hang shows the job stuck in `/queue`'s
`queue_running` with nothing new in `/history`.

**CLI aborts with "ComfyUI endpoint unreachable (ReadTimeout)" even though the
pod is clearly up.** A single slow history poll took longer than the client's
30-second timeout, and the client wrongly reported it as the pod being down.
This is a known rough edge — the client treats one slow poll as a dead pod, not
necessarily a real pod problem. But a slow poll is often caused by the
resolution hang described above, so before re-running, check `/queue` (see the
[First-aid checklist](#first-aid-checklist)): if a job is stuck in
`queue_running`, the issue is the hang (fix the resolution), not a transient
timeout — re-running only starts another ~10-minute hang and more GPU cost.

**Every endpoint returns 404, or curl returns nothing at all.** Usually one of
two mundane causes:

- The pod is stopped — RunPod's proxy returns 404 when nothing is listening on
  port 8188. Re-check that the pod is actually running.
- Your `$EP` shell variable isn't set in *this* terminal tab (each new tab
  starts fresh). Re-set `$EP` to the pod's current proxy URL.

**Pods keep piling up with odd "migration" names.** When RunPod reallocates a
GPU it can spin up a *new* pod with a *new* proxy URL — so any bookmarked URL or
old `$EP` breaks and must be updated. Stopped/idle pods still cost money through
their storage volume. Keep one, delete the extras. → See [RunPod pod lifecycle &
costs](#runpod-pod-lifecycle--costs).

**A refined image (`draft --from`) ignored the source style, or its settings look
wrong.** Refinement drafts now *edit* the parent: they seed the new prompt from the
parent's prompt (an edit, not a rewrite) and keep the template's recipe, so a
`draft --from` spec should carry only `denoise` in its `settings` and a prompt that
reads as an edit of the original. If you instead see invented settings (e.g.
`cfg 3.5`, `steps 25`) or a prompt that abandoned the source style, you're on a
pre-"seed-from-parent" build — pull latest. Manual stopgap: fix the spec's `settings`
in `visual-batch.md` to the Z-Image recipe (`cfg 1`, `steps 8`,
`sampler res_multistep`, `scheduler simple`) before `generate`.

### First-aid checklist

When you're not sure what the pod is doing, these safe, read-only `curl` probes
inspect its state *without* the CLI. Set `$EP` to the pod's proxy URL first
(e.g. `https://<pod-id>-8188.proxy.runpod.net`):

- **`curl $EP/system_stats`** — is the GPU actually attached, and how much VRAM
  is in use (i.e. are models loaded)?
- **`curl $EP/queue`** — is a job running or stuck? Check the `queue_running`
  length.
- **`curl $EP/history`** — did a job finish, and did it produce any images?
- **`curl -X POST $EP/interrupt`** — cancel a stuck or running job to stop
  burning GPU time.
- **`curl "$EP/view?filename=<name>&subfolder=<sf>&type=output" -o image.png`** —
  download a finished image straight from the pod. The `-o` keeps the binary out
  of your terminal; the exact `<name>` and `<sf>` (subfolder) values come from
  the `/history` output above.
- **`curl $EP/object_info`** — what models the pod actually has (this is exactly
  what `model sync` reads).

Remember the two-paths rule: images you make by clicking around in the ComfyUI
web UI are saved *on the pod's storage* (browse them via
[FileBrowser](#filebrowser-pod-file-access)), while images made by the
`generate` CLI are downloaded and saved *locally* on your Mac. → See [UI
generations vs. CLI generations](#ui-generations-vs-cli-generations).

**Cost reminder:** billing starts the moment a pod spins up and keeps running
until you stop the pod in the RunPod UI — stop it as soon as you're done.

### Deeper diagnostics

Lower-level checks for when the [First-aid checklist](#first-aid-checklist)
isn't enough. Reminder on which machine runs what: anything with `$EP`/`curl`
runs on **your Mac** (it reaches the pod over the network); `ls`/`find`/`file`
inspection runs in the **pod's web terminal**.

**Progress stuck at "8% / CLIP Text Encode 0%".** It's the cold model load, not
a hang — the 4 GB Qwen CLIP is loading. Tell loading from wedged by watching
VRAM: run `curl $EP/system_stats | jq '.devices[0].vram_free'` a few times.
Dropping = loading (wait); flat = wedged (interrupt). On a healthy pod the UNET
(~6 GB) and CLIP (~7.5 GB) load to ~15–20 GB resident; if VRAM climbs ~6 GB then
freezes, the CLIP load stalled.

**"Failed" in the job queue is often your OWN interrupt, not a real error.**
Confirm via `curl $EP/history/<prompt_id> | jq '.[].status'` — `status_str`
`"error"` with an `execution_interrupted` message = you cancelled it; an
`execution_error` message = a real failure (read
`exception_type`/`exception_message`). The UI's "Copy error message" can
silently fail; the API is the source of truth.

**Can't find the KSampler / cfg / sampler / denoise to edit them.** The Z-Image
template is a [subgraph](#subgraphs) — the KSampler/cfg/sampler/denoise/empty-
latent are hidden inside one box. To edit or rewire it (e.g. for img2img),
right-click → Unpack Subgraph to flatten it to individual nodes.

**"Value not in list / not in []" on Load Checkpoint.** You've loaded the stock
SD1.5 default workflow on a Z-Image-only pod (no full checkpoint present, just
UNET/CLIP/VAE) — wrong graph. Load the Z-Image-Turbo template instead.

**Verifying a model file is fully present on the pod.** In the pod's web
terminal: `find / -name "<file>.safetensors" -exec ls -lh {} \;` — a complete
Qwen 3-4B encoder is ~7.5 GB.

**Building an img2img graph from the Z-Image template** (for when you rebuild on
a fresh pod): unpack the subgraph → add a Load Image and a VAE Encode → add a
Load VAE set to `ae.safetensors` → wire Load Image→pixels, Load VAE→vae,
VAE Encode LATENT→KSampler `latent_image` → delete EmptySD3LatentImage → set
KSampler `denoise` to `0.5`. The img2img prompt must describe the desired
OUTPUT, not a leftover template default.

**Flaky "migration" pods.** stop/start can land a new host; repeated CLIP-load
stalls on one pod = bad host/volume — deploy a clean fresh pod rather than
nursing it, and prefer models on local disk over a network volume to avoid slow
CLIP loads. See [RunPod pod lifecycle & costs](#runpod-pod-lifecycle--costs).

**Re-registering a workflow left two templates with the same name.**
`workflow register` is now **replace-by-name**: re-registering a name overwrites it
and self-heals any existing duplicates. On older builds it inserted a *new* point
each time, so `recall`/`workflow list` could show two entries sharing one name (and
`get_template_by_name` returned an arbitrary one). If you see duplicates, re-register
the name once to collapse them.

**The "Descriptor" prompt set my descriptor to a stray letter.** The "Descriptor
(what this template serves)" prompt during `workflow register` is a **free-text
field with the default in brackets — not a yes/no confirm**. Pressing `y` writes the
literal string "y". Type a real description, or press Enter to accept the default;
re-running `register` overwrites it.

**`chain show` shows a generation as `[PENDING]` even though it rendered.** Known
issue (KI-4 in `docs/visual-generation-known-issues.md`): the generation's status is
never finalized after a successful render. It's cosmetic — lineage and source
resolution ignore status, so img2img refinement still works against a PENDING parent.

**Editing a refinement: change the `vg-spec`, not the ComfyUI graph.** The registered
img2img graph already holds the correct recipe; the order ticket is the `vg-spec` in
`visual-batch.md`. To change a refinement's prompt or settings, edit the spec — its
settings get written into the graph at generate time and override the baked-in values
— rather than rewiring the node graph.

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
