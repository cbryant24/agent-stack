# visual-generation

A diffusion image/video generation collaborator — prompt-craft, platform tutor,
and generation/iteration over a ComfyUI backend on RunPod. Modeled on
`voiceover-direction` (cost inversion) and `music-curation` (curated memory).

**Status: Phase 2 complete (MVP) — stills + img2img/inpaint refinement shipped.**
The full turn is built and working: `draft` → `generate` → `report`, the ComfyUI
client, `model sync`, `workflow register` (slot-map propose→confirm), asset writing,
the dual Claude/GPU budgets, the three-memory-type collection, and the tutor role
(`explain` / `research`). Stills run on Z-Image-Turbo and Flux/SDXL; img2img + inpaint
(edit-mode refinement) is wired.

**Video (WAN 2.2) — setup done, agent integration is Phase 2 (not yet built).** WAN
2.2 14B text-to-video and image-to-video have been stood up and verified **manually in
ComfyUI** on the pod (models installed, graphs captured, recipes recorded). Driving WAN
through the agent CLI — the `output` field, keyframe extraction, the cost/sanity-check
additions — is the Phase 2 build. See "Video generation (WAN 2.2)" below and
`docs/handoffs/visual-generation-video-phase1-handoff.md`.

The data + retrieval foundation:

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

## Video generation (WAN 2.2)

**Status: manual ComfyUI workflow today; agent CLI integration is Phase 2 (not yet
built).** The steps below are the *operational* path for producing WAN clips in ComfyUI
on the pod, plus what was decided during setup. The agent does not yet drive WAN.

**Model:** WAN 2.2 14B (open-weights, Apache-2.0 — the reason it runs self-hosted on
RunPod; WAN 2.5/2.6 are closed APIs and were rejected). Two modes in scope: **T2V**
(text→video) and **I2V** (image→video, a seed image becomes frame 1). VACE is deferred.
WAN 2.2 14B uses a **Mixture-of-Experts split**: a high-noise expert (structure/motion)
hands off to a low-noise expert (detail) at a *boundary step* — so the graph loads two
model files and runs two sampler passes.

**Installed on the pod** (`/workspace/runpod-slim/ComfyUI/models/`): four fp8-scaled 14B
experts (t2v + i2v, high/low) in `diffusion_models/`, `umt5_xxl_fp8_e4m3fn_scaled` in
`text_encoders/`, `wan_2.1_vae` in `vae/`, and the lightx2v 4-step LoRAs (t2v + i2v) in
`loras/`. Captured graphs + full recipes: `workflows/` and
`docs/handoffs/visual-generation-video-phase1-research-signals.md`.

### Getting started (manual run in ComfyUI)

1. **Spin up the pod** (RTX PRO 6000, US-NE-1) so the `gen-usne1` network volume mounts
   at `/workspace`. Billing starts here. ComfyUI serves on port 8188.
2. **Confirm the models are present** (they persist on the volume across pods):
   `ls -lh /workspace/runpod-slim/ComfyUI/models/{diffusion_models,text_encoders,vae,loras}/`.
3. **Load the template:** ComfyUI → Browse Templates → Video → **Wan 2.2 14B Text to
   Video** (or **Image to Video**). The current ComfyUI ships these with the **lightx2v
   4-step LoRAs baked in** (a "Enable 4steps LoRA?" toggle on I2V) — so by default you're
   on the fast 4-step recipe, not the plain 20-step one.
4. **Check the loaders** auto-filled: the two diffusion-model loaders (high/low), the
   `umt5_xxl_fp8` encoder, `wan_2.1_vae`, and the LoRAs. If a "missing models" dialog
   appears for files you know are on disk, the model list is stale — press **R** to
   re-scan; only genuinely-absent files should remain.
5. **Set a cheap first run:** 832×480 (T2V) or square to match the seed (I2V), and
   **length 33** (frame count must be 4n+1: 33, 49, 81…). Leave the sampler defaults —
   they *are* the recipe to record.
6. **Queue.** First run cold-loads ~40 GB of weights (slow once, fast after). Output
   lands on the **pod** under `ComfyUI/output/video/` (manual UI runs save pod-side, not
   to your Mac — pull with scp or view in FileBrowser).

**Fast vs. quality:** the I2V graph's "Enable 4steps LoRA?" toggle flips the whole recipe
between the 4-step path (`cfg 1`, steps 4, boundary 2 — fast/cheap) and the 20-step path
(`cfg 3.5`, steps 20, boundary 10 — higher quality, no LoRA). One graph, both paths.

### Using a seed image for I2V — get it onto the pod with scp, not the browser

The I2V `Load Image` node needs the seed frame in `ComfyUI/input/`. **The browser upload
through the RunPod proxy corrupts image files** (broken thumbnails, `PIL cannot identify`,
500 errors). Do **not** use it. Instead copy the image directly with **scp over the
direct-TCP SSH endpoint** (RunPod Connect → "SSH over exposed TCP — Supports SCP"; the
`ssh.runpod.io` proxy is interactive-only and supports neither scp nor file-piping):

```bash
# from your Mac (IP/port change each time the pod is recreated — read them from Connect)
scp -P <PORT> -i ~/.ssh/id_ed25519 "/path/to/seed.png" \
  root@<IP>:/workspace/runpod-slim/ComfyUI/input/seed.png
# verify on the pod: file .../input/seed.png  → "PNG image data"
```

Then in ComfyUI press **R** and pick the file from the Load Image **dropdown** (not
"choose file to upload"). For the agent path (Phase 2), I2V will reuse the built img2img
seed mechanism (`/upload/image` + `VisualSource` lineage) so a prior still can seed a clip.

### If you have to migrate to a new pod

GPU availability churns, so you'll periodically lose a pod and start a new one. What
carries over and what changes:

- **Models, graphs, outputs persist** — they live on the `gen-usne1` network volume,
  which survives pod stop *and* terminate and re-attaches to any new US-NE-1 pod. A new
  pod does **not** require re-downloading anything. (Container disk is wiped; nothing you
  care about lives there.)
- **The endpoint changes** — both the ComfyUI proxy URL (`https://<pod-id>-8188.proxy.runpod.net`)
  and the direct-TCP SSH IP/port are new per pod. Update them wherever you use them
  (`--endpoint` for the agent later; the scp `-P`/host; any `$EP` shell var). Read the
  current values from RunPod → pod → Connect.
- **Datacenter is fixed** — the volume is locked to US-NE-1, so a replacement pod must be
  US-NE-1 to mount it (that's why the RTX PRO 6000 there was chosen).
- **Nothing to re-install or re-configure** beyond pointing at the new endpoint. If a
  "migrate pod data" prompt appears, it concerns the disposable container disk, not your
  volume — you don't need to wait on it for the models.

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
- **`report --context` vs `--notes`** — when you react to a generation with
  `report <gen_id>`, `--context` (reasoning-oriented: *why* you reacted) is embedded with
  the generation record and **reaches the drafting Claude on later related drafts** as a
  retrieved prior-generation signal; `--notes` (action-oriented: *what to change next
  time*) is stored but **currently NOT read by `draft`**. So put any steering feedback you
  want to actually influence future drafts in **`--context`**, not `--notes`.

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
- **Refinement (img2img/inpaint) is built, wired, and proven end-to-end.** `draft --from <gen_id>` /
  `--image <path>` (+ `--mask`) attaches a `VisualSource`; at `generate` the source is
  uploaded (`/upload/image`) and written into the template's init-image (and mask) slot, with
  `parent_id`/`chain_root_id` lineage. The **`visual-workflow-inpaint` graph is registered and
  has been run through the CLI end-to-end** (editing a single TV screen inside a stop-motion bar
  plate), so registering a graph is no longer an open prerequisite for inpaint. Authoring
  *new* graphs (e.g. an img2img+LoRA template) remains a user task (see
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

**Known limitations** (learned generating the `celeste-you-dangerous` batch):

- **Text and logos render unreliably.** 8-step turbo diffusion renders text
  inconsistently — short common words *sometimes* land legibly ("wrong" rendered
  clean) but not reliably ("right" garbled to pseudo-text in the very same pass);
  complex stylized marks (team logos, wordmarks, branded graphics) garble
  *reliably*. Rule of thumb: treat legibility-critical text and any logo/wordmark
  as an edit-stage composite on a clean plate (see
  [Edit-stage compositing vs. in-diffusion generation](#edit-stage-compositing-vs-in-diffusion-generation)),
  not something to generate. → Troubleshooting:
  [garbled text/logos](#when-something-goes-wrong).
- **Small per-character face details drop out in multi-character prompts.**
  Coraline-style button eyes rendered reliably on a *solo* render but dropped on
  the second/detail-heavier character in a two-character prompt, and on *both*
  characters in a face-forward two-shot — even with parallel phrasing and an
  explicit "button eyes clearly visible" instruction. Treat button eyes (and
  similarly small details like alternating nail colors) as unreliable in
  multi-character face-forward shots; mitigations are a targeted eye inpaint after
  the base render, or keeping such details to solo/close compositions. →
  Troubleshooting: [missing button-eyes](#when-something-goes-wrong).
- **text2img has no region isolation.** Changing any part of a text2img prompt
  regenerates the whole frame; a fixed seed keeps the result *similar* but does
  not lock any region. To change one region while protecting another (e.g. fix a
  skin tone while keeping the existing TV screens), use **inpaint** (mask the
  region; everything outside is copied pixel-exact) or a **low-denoise img2img**
  (light global touch) — see the inpaint/denoise entries under
  [When something goes wrong](#when-something-goes-wrong). Adding *large new*
  elements (thought bubbles, text overlays) can't be done by a light-touch edit;
  it needs a re-roll or edit-stage compositing.

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

### Edit-stage compositing vs. in-diffusion generation

Logos, wordmarks, branded graphics, legibility-critical text, and graphic
overlays (e.g. thought bubbles) are **composited in the editor (DaVinci) on a
clean generated plate, not generated** — because the model renders text and
marks unreliably (see the Z-Image
[Known limitations](#z-image-turbo-what-it-is-and-why-its-settings-are-different)).

**Benefits:** crisp, correct, legible output; preserves an otherwise-good plate
(no re-roll); faster and cheaper iteration; a clean separation for IP-sensitive
assets. **Tradeoffs:** extra editing labor; the plate must intentionally leave
room for the overlay (clear headroom, blank-ish screens); IP responsibility
shifts to composite time.

### Character continuity: validate before propagating

Prove a character's locked descriptor block on a **single** render before
reusing it across other beats. For two-character beats, validate the **two-shot
itself** (distinct puppets, no identity bleed — which held) before relying on it,
rather than assuming a descriptor that works solo will compose cleanly.

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

**A `spec_id` is not a generation id.** The `spec_id` identifies the *order ticket* (one
`vg-spec` in a batch) — it is **not** the id of the image that gets produced. At `generate`
time a fresh **`gen_id`** is minted for each rendered image; that `gen_id` is also the asset
filename (`assets/<project>/<gen_id>.png`) and the Qdrant point id of the stored
`generation` record. So when you want to inspect or act on a *generation* —
`report`, `recall`, `chain show` — use the `gen_id` surfaced by `review-pending` / `recall`,
**not** the batch's `spec_id`. (The two only coincide in error paths: a spec whose metadata
fails to parse falls back to a freshly-generated `spec_id`, which is why a malformed
`workflow_ref` can change the `spec_id` that gets reported — see [`workflow_ref`](#workflow_ref).)

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

### `lesson list [--include-unconfirmed] [--scope S] [--valence V]`

Lists technique lessons one per line as `entry_id  [valence/scope] statement`. The
management inverse of `recall` (which hides ids on purpose): here the `entry_id` is the
whole point, so you can target one for removal. Confirmed-only by default;
`--include-unconfirmed` also shows unconfirmed lessons. `--scope`/`--valence` filter the
list.

### `lesson rm <entry_id> [--yes]`

Deletes the technique lesson with `entry_id`. Refuses an id that resolves to a `generation`
or `workflow_template` (errors clearly), and errors if no point has that id. Prompts for
confirmation unless `--yes` is passed. Use `lesson list` to find the id.

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

**An inpaint of a screen/prop came out as flat *framed art* instead of a lit display.**
Two causes, usually together: the prompt used "flat colors / graphic style / poster"
language, and the **mask covered the prop's frame/bezel**, so the surrounding frame got
repainted into a picture frame. **Fix the recipe, not the code:** (1) mask the
**glass/region only**, inset *inside* the surrounding frame, so the object's own frame is
preserved; (2) prompt it as a **lit display from a broadcast/camera angle** and explicitly
negate "poster / framed art / flat / picture frame / matte border"; (3) use **denoise ~0.8**.
(Learned editing a TV screen to show a basketball game in the stop-motion bar plate.)

**What denoise to use for inpaint — it's *higher* than whole-image img2img.** A masked
inpaint only regenerates the masked region, so a low denoise leaves the original content
ghosting through. Use **0.8–0.9** to fully replace masked content. The CLI's ">0.85 loses
coherence" warning is about *whole-image* coherence and is **benign for masked inpaint** —
the rest of the frame isn't denoised. Whole-image img2img stays at **0.4–0.7** (≈0.65 is the
calibrated "redo every surface, keep the room's geometry" dial for turning a photo into a set).

**Rendered text or logos come out garbled** (words on screens/clothing render as pseudo-text
or smeared marks). 8-step turbo diffusion renders text *unreliably* and complex marks (logos,
wordmarks, branded graphics) *reliably* garbled — see the Z-Image
[Known limitations](#z-image-turbo-what-it-is-and-why-its-settings-are-different). **Fix /
future:** composite these at the edit stage on a clean plate (see
[Edit-stage compositing](#edit-stage-compositing-vs-in-diffusion-generation)); if you must
attempt text in-diffusion, expect only short common words to *sometimes* land.

**Button eyes (or other small face details) missing in multi-character renders** — button eyes
render as ordinary eyes on one or both characters in a face-forward two-shot. Small
per-character attributes drop in multi-character prompts (see the Z-Image
[Known limitations](#z-image-turbo-what-it-is-and-why-its-settings-are-different)). **Fix /
future:** validate on solo/close shots, and consider a targeted eye inpaint after the base
render — parallel phrasing and an explicit "clearly visible" instruction alone are insufficient.

**`draft` dies with `FileNotFoundError: …/batches/batch.batch.md`.** The batch directory
doesn't exist and `write_batch` doesn't create it (KI-6). One-time fix:
`mkdir -p ~/agent-data/visual-generation/batches`. The "Error communicating with Voyage" line
printed just above is unrelated and non-fatal (next entry). The redundant `batch.batch.md`
name is the default-project quirk (KI-7) — point `generate` at the path on the `Appended to:`
line, **not** the generic `<batch.md>` placeholder in the `Next:` hint.

**`draft` prints "Error communicating with Voyage" and/or picks no template.** `draft` does
template auto-retrieval via the Voyage embeddings API; a transient failure **degrades
gracefully to no template**. For txt2img that just means unconstrained settings, but for
**inpaint it means the `init_image`/`mask` slots are never wired — the mask silently won't
apply.** Watch the `Template:` line in the draft output: if it reads
`(none — settings are unconstrained)`, re-run (usually transient) or pass
`--template visual-workflow-inpaint` explicitly to bypass retrieval.

**A semantic command reports an *invalid* Voyage key (distinct from the transient failure
above).** If `workflow list` — or any embed/semantic command — errors as if the key is
invalid, the likely cause is that it was run *without* `op run`, so the `op://` reference in
`.env` was never resolved: an **absent** key looks identical to a **rejected** one. **Fix:** run
under `op run --env-file=.env -- …` (the same prefix called out in the next entry). **Future:**
any command that embeds or does semantic retrieval (`draft`, `generate`, `recall`,
`workflow list`) must run under `op run`; exact-match DB reads (e.g. template lookup by name) do
not.

**You can drop `--package visual-generation` from the `uv run` command.** The
`visual-generation` console script is installed in the shared workspace venv, so
`uv run visual-generation …` resolves it; `--package` only matters for disambiguation or
package-specific sync. The `op run --env-file=".env" --` prefix is still required for any
credentialed command (embeds/store writes) — see the Voyage/Anthropic key entry below.

**`docker ps` hangs and the local Qdrant stack won't come up.** *Symptom:* `docker ps`
(or `docker compose … up`) hangs with no output and never returns. *Cause:* the Docker
Desktop daemon has wedged — the CLI is waiting on a backend that's no longer answering.
*Fix:* force-kill the whole Docker process tree, then relaunch:
`osascript -e 'quit app "Docker"'` to ask it to quit, then
`pkill -9 -f '[Dd]ocker'` (or `pkill -9 com.docker`) to kill the stragglers, then
`open -a Docker` to start fresh. **Never delete the Docker VM data / "reset to factory
defaults"** — the `visual_generation_memory` Qdrant volume lives inside that VM, so
wiping it destroys your generations/lessons/templates. If `docker ps` still hangs after a
relaunch, kick the network helper: `sudo launchctl kickstart -k system/com.docker.vmnetd`.
*Recurrence:* this is an intermittent Docker Desktop fault, not something the repo causes;
the quit + `pkill -9` + relaunch sequence is the routine recovery, and as long as you
never wipe the VM the Qdrant data survives every cycle.

**Qdrant container fails to start with `bind: can't assign requested address`.**
*Symptom:* `docker compose -f infrastructure/docker-compose.yml up` errors on the Qdrant
port mapping with `bind: can't assign requested address`. *Cause:* the compose file pinned
the host side of `6333` to a specific IP that *this* machine doesn't currently own — e.g. a
Tailscale IP copied from another host, or one that changed. The kernel can only bind an
address the host actually holds. *Fix:* bind to an address this host owns. Either use this
machine's own Tailscale IP (`tailscale ip -4` — this M1 = `100.79.253.62`) or, preferably,
bind **all interfaces** with a plain `"6333:6333"` mapping, which serves both `localhost`
*and* the Tailscale address at once. A pinned non-loopback IP loses `localhost`, so the
local tests/CLI that hit `localhost:6333` can no longer reach Qdrant. *Recurrence:* a
pinned IP breaks again whenever the Tailscale IP rotates or the volume moves to another
host; `"6333:6333"` is the durable choice that survives both. (Don't hand-edit
`infrastructure/docker-compose.yml` as part of an unrelated change — this entry just
records what the binding should be.)

### Setup-phase gotchas (volume, uploads, downloads) — learned 2026-06-19

These all surfaced standing up WAN 2.2 on the pod. Most trace back to **the network
volume hitting its quota**, which fails in confusing, indirect ways.

- **"Disk quota exceeded" is the root cause of a whole cluster of errors.** A full
  `/workspace` volume shows up as: scp transferring to 100% then `write/close remote:
  Failure`; a model file downloading as **0 bytes** (→ later `ValueError: cannot mmap an
  empty file` when ComfyUI loads it); `comfy.settings.json` getting **corrupted** (→
  "user settings file is corrupted" + a frontend **`TypeError: Load failed`** popup);
  and image uploads failing. **Fix:** free space (delete a redundant model — e.g. an
  unused `umt5_xxl_fp16` if the templates use `fp8`) and/or **resize the network volume**
  (RunPod → Storage → `gen-usne1` → increase; volumes only grow). The 100 GB default is
  too small for z-image + full WAN t2v+i2v 14B; 200 GB gives working room.
- **`TypeError: Load failed` after a *successful* run is a frontend glitch, not a
  generation failure.** Check the log: if it ends with `Prompt executed in N seconds` and
  the sampler bars hit 100%, the clip was produced and saved under `output/video/` — the
  popup is just the browser failing to fetch the preview through the proxy.
- **Browser image upload corrupts files; use scp over direct-TCP.** See
  [Video generation → seed image](#using-a-seed-image-for-i2v--get-it-onto-the-pod-with-scp-not-the-browser).
  Symptoms: broken thumbnails in Media Assets, `PIL UnidentifiedImageError`, "Invalid
  image file". `ssh.runpod.io` is interactive-PTY only (no scp/sftp, no `cat >` piping —
  "doesn't support PTY"); use the "SSH over exposed TCP (Supports SCP)" endpoint instead.
- **A partial download leaves a 0-byte file that ComfyUI thinks "exists."** It won't
  re-offer the download. Delete the empty file (`find .../loras -name '*name*' -size 0
  -delete`) then re-trigger the download (free space first). Verify safetensors integrity
  cheaply by reading the header — see below.
- **Verify a safetensors file is intact without loading it:** read the 8-byte header
  length + JSON header; if it parses, the file isn't truncated. (One-off Python:
  `struct.unpack('<Q', f.read(8))` then `json.loads(f.read(n))`.)
- **The "missing models" dialog over-reports right after a pod is recreated** — it scans
  before the volume finishes mounting/indexing. Press **R** to re-scan; only genuinely
  absent files should remain (after a fresh pod, that was just the i2v LoRAs).
- **fp16 vs fp8 encoder:** the WAN templates default to `umt5_xxl_fp8_e4m3fn_scaled`. The
  fp16 encoder is a marginal quality lever and pure dead weight if unused — delete it to
  reclaim ~11 GB. The real quality levers are fp16 *diffusion experts* + the 20-step
  (no-LoRA) path, both gated on volume size (see the v2-refinements doc).

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

**Credentialed commands fail with "Provided API key is invalid" (Voyage/Anthropic).**
The repo's `.env` stores secrets as 1Password references (`op://…`), not literal keys —
python-dotenv loads the placeholder string and hands *that* to the API, which rejects it.
Run anything that writes to the store or embeds — `workflow register`, `fact ingest-docs`,
`lesson add`, `draft`, `generate` — through the 1Password CLI:
`op run --env-file=".env" -- uv run --package visual-generation visual-generation …`.
`load_dotenv` defaults to `override=False`, so the op-injected value wins over the
placeholder. Needs an authenticated 1Password session (biometric in iTerm2, or an
`OP_SERVICE_ACCOUNT_TOKEN` for non-interactive shells like Claude Code).

**Re-running `lesson add` (or a seeding block) duplicated my lessons.** `lesson add` is
**not** dedup-by-content — each run writes a fresh point, so the same statement run twice
leaves two copies that both surface in `recall` and waste retrieval slots. Add each lesson
once. To clean existing dupes, run `lesson list` to see every lesson with its `entry_id`,
then `lesson rm <entry_id>` to remove all-but-one per identical statement.

**`fact ingest-docs` parsed fewer sections than expected (or none for a page).** The ingest
reads a folder **non-recursively, `*.md` only**, and turns every **H2-or-deeper** heading
into one entry — prose above the first heading, and any heading-less page, is dropped.
ComfyUI/RunPod docs ship `.mdx` in nested folders, so stage them first: flatten to one
folder of `.md`, strip MDX `import`/JSX component lines (leave fenced code intact), re-add
each page's frontmatter `title:` as a top-level `## ` so intros and short pages still
produce an entry, and add a frontmatter `url:` line so the ingest records the live doc URL
as `source_ref`. Run under `op run`, `--dry-run` first to see the candidate count.

**Fixing a template's descriptor without disturbing its slot map.** A weak descriptor (e.g.
the template name itself) ranks badly in `recall`/`draft` because the descriptor is the
embedded text. Don't `workflow register` again just to fix it — that re-infers the slot map
from the graph and can drop manual slot corrections. Update in place instead: load the
template (`get_template_by_name`), set `.descriptor`, and `upsert_template` — it re-embeds
the new descriptor, preserves graph + slot_map + entry_id, and collapses same-name dupes.

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
