# Video Generation Primer — a living knowledge base

**Purpose.** A plain-language companion to the video pipeline we built in
`visual-generation`. It explains the *concepts*, *terms*, *technologies*, and *why we
chose each one* — enough to build a real mental model, not just run commands. It is
deliberately digestible; depth without jargon-soup.

**How to use it.** Read §1 for the big picture, keep §2 (glossary) open as you read the
rest, and treat §3–§7 as the "why." When something new lands in the agent, add a term to
§2 and a paragraph wherever it fits — this doc is meant to grow with the agent *and* with
your understanding.

**Sibling docs** (the "what to build" and "the sources"): the phased build in
[`video-generation-implementation-guide.md`](video-generation-implementation-guide.md),
the reasoning/trade-offs in [`video-generation-research.md`](video-generation-research.md),
and the authoritative external links in
[`video-generation-doc-references.md`](video-generation-doc-references.md).

---

## 1. The big picture (in plain language)

We're making a **4-scene, ~5-minute stop-motion-style short film**. The hard part of AI
video isn't making *one* pretty clip — it's making *dozens* of clips where the same
character looks like the same character the whole way through. Left to its own devices, an
AI video model slowly "drifts": colors shift, faces morph, the style creeps toward glossy
realism. Over a minute of footage that drift becomes obvious and ruins continuity.

Our answer is **FLF2V — first-last-frame video**. Instead of letting the model improvise a
whole clip, we hand it **two still images** — the first frame and the last frame — and ask
it to *fill in the motion between them*. Because both ends are pinned to images we already
approved, the clip can't drift far. We then chain clips so that **each clip's last frame is
the next clip's first frame**, giving one continuous, on-model scene.

So the pipeline is really three jobs:

```
1. Make keyframes   → approved still images, one per ~5-second beat boundary
                      (each new keyframe is an EDIT of the previous approved one, so
                       identity is re-anchored at every step)
2. Sequence them    → order the keyframes into clips that share boundaries
3. Render           → the AI fills motion between each pair → .mp4 clips → a manifest
                      the editing step consumes
```

The agent (`visual-generation`) doesn't run any AI models itself. It **drives ComfyUI** (a
generation engine) running on a rented **RunPod** GPU, over HTTP. The agent's job is the
*craft and bookkeeping*: composing prompts, wiring the right images into the right places,
enforcing the character "canon," gating on approval, tracking cost, and recording lineage.

---

## 2. Glossary (the terms to internalize)

### Diffusion fundamentals
- **Diffusion model** — the kind of AI that makes images/video. It starts from random
  noise and, step by step, "denoises" it into a coherent picture guided by your prompt.
- **Latent** — diffusion doesn't work on pixels directly; it works in a compressed
  mathematical space called the *latent space*. Faster, and where the "thinking" happens.
- **VAE (Variational Auto-Encoder)** — the translator between pixels and latent. *Encode* =
  image → latent; *decode* = latent → image. Every graph ends with a VAE decode.
- **Text encoder** (a.k.a. **CLIP**, or here **UMT5** / **Qwen-2.5-VL**) — turns your text
  prompt into numbers (a "conditioning" signal) the diffusion model can follow.
- **Conditioning** — the encoded guidance fed to the sampler: usually a *positive* prompt
  (what you want) and a *negative* prompt (what to avoid).
- **Sampler** — the algorithm that runs the denoising loop (e.g. `euler`). **Scheduler**
  (e.g. `simple`) sets the noise-removal schedule across steps.
- **Steps** — how many denoise iterations. More = slower, usually cleaner. **CFG**
  (classifier-free guidance) — how hard the model obeys the prompt vs. improvising.
- **Seed** — the starting random noise. Same seed + same settings = reproducible output.
- **Denoise strength** — for *editing* an existing image: 0 = keep it exactly, 1 = ignore
  it. ~0.4–0.7 is "change some things, keep the composition."
- **Shift** — a Wan/SD3-family knob that biases the noise schedule; affects motion/detail
  balance. You'll see `ModelSamplingSD3` (Wan) and `ModelSamplingAuraFlow` (Qwen) nodes set it.

### Image vs. video generation
- **T2I (text-to-image)** — prompt → still image. (Our Z-Image Turbo drafts.)
- **I2V (image-to-video)** — one seed image becomes frame 1, model invents the rest.
- **T2V (text-to-video)** — prompt → video, no seed image.
- **FLF2V (first-last-frame-to-video)** — TWO images (first + last), model interpolates the
  motion between them. **This is our workhorse** — see §1 and §7.
- **Keyframe** — an approved still that marks a beat boundary; the anchor a clip is built on.
- **Clip** — one ~5-second generated video segment (for us, 81 frames at 16 fps).
- **fps / frame count** — Wan 2.2's native clip is **81 frames** (≈5s at 16 fps). Frame
  counts must be **4n+1** (…, 33, 49, 81) for the architecture.
- **Drift** — the gradual, unwanted change (color, identity, style) across chained clips.
  The enemy FLF2V fights.

### Model-shaping techniques
- **Checkpoint / UNET** — the big model weights file(s). "UNET" is the core denoising network.
- **LoRA (Low-Rank Adaptation)** — a small add-on file that nudges a base model toward a
  style or a specific character, without retraining the whole model. We stack a **lightx2v
  4-step LoRA** (makes Wan render in 4 steps instead of 20 — much cheaper) and can pin
  **character LoRAs** for identity.
- **MoE (Mixture-of-Experts)** — Wan 2.2 14B uses *two* expert networks: a **high-noise
  expert** (blocks out structure/motion early) hands off to a **low-noise expert** (refines
  detail late). That's why its graph loads two model files and runs two sampler passes.
- **Instruction edit** — a model that takes an image + a sentence ("same shot, she reaches
  for the door") and returns the edited image. Qwen-Image-Edit does this; plain T2I can't.
- **Reference image** — an image handed to the model as an identity/appearance guide (a
  character sheet, an outfit sheet), distinct from the image being edited.

### ComfyUI & how we drive it
- **ComfyUI** — a node-based engine for running diffusion pipelines. You wire boxes
  (nodes) together into a **graph**; running the graph produces images/video.
- **Node / `class_type`** — one box (e.g. `WanFirstLastFrameToVideo`, `KSampler`,
  `LoadImage`). Each has named **inputs**.
- **API format vs UI format** — the *UI format* is what the ComfyUI editor saves (positions,
  links as a separate list). The *API format* is the flat, machine-runnable form
  (`node_id → {class_type, inputs}`) you POST to the server. **We only use API format.**
- **Slot** — a *semantic* name (`positive`, `seed`, `first_frame`, `length`) mapped to the
  exact node input that carries it. The **slot map** is how the agent knows where to write a
  value into a stranger's graph. (See §6 — this is one of the cleverest pieces.)
- **Subgraph** — a node that contains a mini-graph inside it; when exported, its inner nodes
  get namespaced IDs like `"129:98"`. (Our committed Wan graphs are subgraph exports.)
- **The 5 endpoints we use**: `/prompt` (submit a graph), `/history/{id}` (get results),
  `/view` (download an output file), `/upload/image` (send an input image),
  `/object_info` (list installed nodes + models — also our pod-readiness test).

### Our agent's own vocabulary
- **Modality** — which *kind* of generation a workflow does, inferred from its slots:
  `text2img`, `img2img`, `inpaint`, `edit` (Qwen), `i2v`, `flf2v`.
- **VisualSource** — the record of "what images this generation starts from" (a first frame,
  an optional last frame, reference images, an inpaint mask).
- **Canon** — the per-project "source of truth" for characters/places: a locked appearance
  description, a pinned character LoRA, and reference sheets. Enforced in code so identity
  reaches every prompt regardless of the LLM's whims.
- **Approval gate** — the rule that a clip may only be built on keyframes a human has
  reacted to positively. Makes "every boundary is an approved still" real.
- **Lineage** — the parent links recorded on every generation: `parent_id` (first frame),
  `parent_last_id` (last frame, for clips), `chain_root_id` (the scene's origin).
- **Sequence / scene manifest** — the `.sequence.md` file orders a scene's clips; the
  `scene-manifest.json` is the finished handoff (clip paths, durations, boundaries) the
  editing step reads.
- **Plan → spend** — the agent computes a cost estimate and validates everything (**plan**)
  before it ever touches the GPU (**spend**). GPU money is tracked separately from the
  Claude/LLM budget.

---

## 3. The models we use (and why these, not others)

| Model | Role for us | Why we chose it | Alternatives we passed on |
|---|---|---|---|
| **Z-Image Turbo** | Fast text-to-image *drafts* / scene-opening stills | Very fast (≈8 steps), cheap ideation | (kept only for ideation — see below) |
| **Qwen-Image-Edit 2511** | **Keyframe editing** — "same shot, new pose" | It's an *instruction-edit* model with multi-image references (character + outfit) and strong identity consistency; exactly the "keep everything, change one thing" operation | **Z-Image Turbo**: can't edit an existing image at all (no image input). **FLUX.2**: great generator but oriented to fresh generation, less surgical for "keep the shot" |
| **Wan 2.2 14B** (I2V/FLF2V) | **The video model** — turns keyframe pairs into clips | Open-weights (Apache-2.0 → we can self-host on our own GPU), native FLF2V support, strong 5-second clips | **Wan 2.5/2.6**: closed APIs (can't self-host, ongoing per-call cost). **Chained single-still I2V**: drifts past ~1 min (the whole reason we use FLF2V) |

Two ideas worth locking in:

- **Why an *edit* model for keyframes instead of just generating each one fresh?** If you
  generate each keyframe from scratch, the character is slightly different every time —
  that's drift, upstream. Editing the *previous approved frame* re-anchors identity at every
  step: the new frame literally starts from the old one, so only the pose/action changes.
- **Why open-weights Wan and not a hosted API?** Self-hosting on RunPod means the model
  runs on *our* rented GPU with *our* data, at a flat hourly cost we control, and it can't
  change or disappear under us. The trade is we manage the infrastructure (pods, volumes).

---

## 4. The technology stack (and why)

| Tech | What it is | Why we use it | Alternative / why not |
|---|---|---|---|
| **ComfyUI** | Node-graph diffusion engine with an HTTP API | It's the de-facto open standard; native Wan 2.2 + Qwen support; the API lets the agent drive it programmatically | Diffusers/raw Python: more code, less community tooling; hosted APIs: closed + per-call cost |
| **RunPod** | On-demand GPU cloud (pods + network volumes) | Rent a big GPU (RTX PRO 6000, 96 GB) by the hour; a **network volume** keeps our models persistent across pods | Owning a GPU: huge up-front cost; other clouds: more setup for the same thing |
| **Network volume** | A persistent disk that survives pod deletion | Models (~tens of GB) live here once; a fresh pod just re-attaches — no re-downloading | Baking models into a container image: slow, huge, rebuild-on-change |
| **Qdrant** | A vector database (semantic search) | Stores generation records + learned "technique lessons" so the agent can *recall* what worked | A plain DB: no semantic "find similar/relevant" search |
| **Voyage embeddings** | Turns text/images into vectors for Qdrant | `voyage-multimodal-3` can embed image+caption together | (video: it *can't* embed video yet → we embed clips text-only; see §7) |
| **httpx** | Async HTTP client (Python) | How the agent talks to ComfyUI's 5 endpoints | `requests`: no async; we want concurrency |
| **Pydantic v2** | Typed data models with validation | Every record (spec, generation, template, sequence) is a validated model that round-trips to disk/DB cleanly | Hand-rolled dicts: silent shape bugs |
| **uv** | Python package/workspace manager | Fast, reproducible; manages this multi-package workspace | pip/poetry: slower, less workspace-friendly |
| **OpenTelemetry → Jaeger** | Tracing (see what ran, how long, what it cost) | Every run emits a trace; GPU seconds/cost are span attributes | print-logging: no structure, no timing |

---

## 5. How our pipeline works (flow → commands → what happens)

```
KEYFRAMES                SEQUENCE                RENDER                 HANDOFF
──────────               ────────                ──────                 ───────
draft --from <prev>      sequence plan <scene>   sequence render        scene-manifest.json
  --template               --keyframe A            <scene>.sequence.md    (ordered clips,
  qwen-edit-2511           --keyframe B ...         --endpoint <url>       durations,
  "same shot, ..."       (wires A→B, B→C ...)     (validate → gate →      boundary gen_ids)
  [canon adds refs]                                spend → manifest)          │
     │ react/approve          │                        │                     ▼
     ▼                        ▼                        ▼                 edit-brief / DaVinci
  approved keyframe      <scene>.sequence.md       .mp4 clips            (assembly — outside
  (a still, PENDING      (edit motion prompts)     + lineage recorded     this agent)
   until you react)
```

- **`draft`** composes a *spec* (prompt + settings + source images) and appends it to a
  batch file. For keyframes it uses the Qwen edit template and your prior approved frame as
  the base; **canon** auto-attaches the character's reference sheets. Free (no GPU).
- **`sequence plan`** takes your ordered approved keyframe IDs and writes a `.sequence.md`
  with clips pre-wired so consecutive clips share a boundary. Free.
- **`sequence render`** validates the sequence (order + shared boundaries), **gates** each
  clip on its keyframes being approved, then does **plan → spend**: submits each clip to
  ComfyUI, downloads the `.mp4`, records lineage, and writes the **scene manifest**. Spends GPU.

---

## 6. Key implementation ideas in our codebase

- **Workflow templates + slot inference** — The agent can't hardcode every graph. Instead,
  you register an exported ComfyUI graph and the agent *infers* its **slot map** by walking
  the wiring — e.g. it finds the positive prompt by tracing the sampler's `positive` input
  back to a text node, and finds the two frame images by tracing a `WanFirstLastFrameToVideo`
  node's `start_image`/`end_image` back to their `LoadImage` nodes. This is why adding a new
  graph rarely needs new code. (`slot_inference.py`)
- **Modality from slots** — What a template *does* is read off which slots it has
  (`first_frame` + `last_frame` → `flf2v`; `edit_image_1` → `edit`; …). (`draft._template_modality`)
- **VisualSource + multi-image provisioning** — one record holds the first frame, optional
  last frame, and ordered references; at spend time each is uploaded and written into its
  slot. A **per-session upload cache** means a frame shared by two clips uploads **once**.
- **Canon (code-enforced identity)** — locked appearance text is injected into every prompt
  that names a character; the character's LoRA is pinned into the model stack; for Qwen
  edits, the character's **reference sheets** are attached as edit images. Identity travels
  three ways (text + model + reference), on every shot, regardless of the LLM. (`canon.py`)
- **Approval gate** — before rendering a clip, the agent loads its source keyframes and
  refuses unless their reaction is positive (`--allow-unapproved` overrides). (`generate.py`)
- **Lineage** — a clip records `parent_id` (first frame) *and* `parent_last_id` (last
  frame), plus a shared `chain_root_id` for the scene — so you can always trace a clip back
  to the exact stills it came from.
- **Per-template cost + plan→spend** — a video clip costs ~10–30× a still, so the cost
  estimate is learned **per template** (video runs never get averaged with cheap image runs),
  and the whole plan (with an honest session total) is shown before any GPU spend.
- **Text-only embedding for clips** — see §7.
- **Scene manifest** — the ordered, machine-readable handoff the editing step discovers by
  project.

---

## 7. Key design decisions (the "why we did it this way")

- **FLF2V over chained single-still I2V.** Chaining (extract a clip's last frame, feed it as
  the next clip's seed) visibly drifts past ~1 minute. FLF2V pins *both* ends of every clip
  to an approved still, so drift can't accumulate. This single choice shapes the whole
  pipeline (keyframes, sequences, the approval gate).
- **Qwen-Image-Edit for keyframes, not fresh generation.** Editing the prior approved frame
  re-anchors identity at every beat; generating fresh would reintroduce drift upstream.
- **We constructed the FLF2V graph from the I2V export** (one node swap: `WanImageToVideo` →
  `WanFirstLastFrameToVideo` + an `end_image`) rather than hand-authoring it, because the
  native template runs on the *same weights*. It was then **validated by a real render on a
  pod** (a 335 KB `.mp4`), so it's proven, not assumed.
- **Clips embed text-only in Qdrant.** Our embedding model (`voyage-multimodal-3`) can embed
  images but **not video**. So a clip's searchable vector comes from its caption + motion
  prompt. (A future option: embed a middle-frame thumbnail; deliberately deferred.)
- **Pods are create/delete, never stop/start.** For our scarce GPU, a *stopped* pod usually
  can't resume (the host reclaims it). So the lifecycle is: create fresh → use → delete. The
  **network volume** (with the models) survives deletion, so nothing is lost.
- **The ComfyUI start command lives in a RunPod *template*, not the bare image.** A pod made
  from the bare image boots a GPU but never launches ComfyUI (every URL 404s). Deploying via
  the `agent-stack` template (`TEMPLATE_ID`) is what actually binds ComfyUI on port 8188.
  (Learned the hard way — see the workflows README troubleshooting.)

---

## 8. Open questions / things we'll add as we grow

- **Qwen-Image-Edit 2511 graph** — not yet committed. Its models aren't on the production
  volume and its native template is a complex subgraph (`FluxKontextImageScale`,
  `FluxKontextMultiReferenceLatentMethod`, `ModelSamplingAuraFlow`, `CFGNorm`). It needs a
  real File→Export on a pod that has the Qwen models. The agent-side plumbing is already in.
- **Style consistency** — if Wan smooths away the stop-motion look, options are a style LoRA
  on the Wan stack, holding frames, or leaning harder on the approved keyframes.
- **Post-processing** (frame interpolation to higher fps, upscaling) — deliberate non-goals
  for v1; would be added as separate templates.
- **Video-native embeddings** — adopting `voyage-multimodal-3.5` (can embed video) if
  per-clip semantic search becomes important.

*Add to this doc as the agent and your understanding grow — new terms in §2, new "why"s in
§7, and new open questions here.*
