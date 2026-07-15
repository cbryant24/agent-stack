# Video Generation Implementation Guide — Wan 2.2 FLF2V in `visual-generation`

Target: extend the existing `visual-generation` agent so approved stills become the keyframe
boundaries of Wan 2.2 first-last-frame (FLF2V) clips, assembled into the 4-scene, 4–6 minute
Coraline-style short. Keyframes are produced by editing prior approved frames with
Qwen-Image-Edit 2511; clips are interpolated between consecutive approved keyframes; scenes are
chains of clips sharing boundary frames.

This plan is grounded in the current code (reviewed at `main`): `draft`/`redraft` →
`batch.md` → `generate` (plan → spend) → `ComfyUIClient` → asset + Qdrant generation record,
with `WorkflowTemplate`/`slot_inference`, `ModelRegistry`, `canon`, `lora_guard`, and
`gpu_tracker` as the supporting systems.

---

## 0. Decisions this plan encodes (from our working sessions)

1. **FLF2V, not chained single-still I2V.** Each ~5s clip is bounded by two approved keyframe
   stills; consecutive clips in a scene share the boundary frame. Chained I2V drifts (color,
   identity) past ~1 minute; FLF2V pins every clip endpoint to an approved image.
2. **Budget: ~48–72 clips, ~52–76 keyframes** for 4 scenes × 60–90s at 5s (81-frame, 16fps)
   native clips. Scene of N clips needs N+1 keyframes; scenes don't share frames.
3. **Keyframe generation migrates to Qwen-Image-Edit 2511.** The core operation — "same shot,
   same characters, new pose/action" — is an instruction edit over the prior approved frame,
   which Z-Image Turbo (pure t2i) cannot do. Identity comes from reference images (character +
   outfit sheets), optionally with a light style LoRA stacked; the Lightning 4-step LoRA keeps
   iteration fast. Z-Image Turbo stays for non-canonical ideation only — NOT scene-opening
   production frames (amended 2026-07-15: keyframe/still authority is plate-first per the
   consolidated audit §17; a scene opens on its approved framing plate, characters inserted
   by masked edits).
4. **Canon evolves from "pinned LoRA" to "pinned reference set"** (LoRA pinning stays for
   Z-Image drafts; reference-sheet pinning is added for Qwen keyframe edits).
5. **Bake-off discipline:** new models validate on a separate pod + separate network volume
   (`POD_NAME`/`NETWORK_VOLUME_ID` env overrides in `scripts/pod`) before anything touches the
   production `gen-usne1` volume.

---

## 1. What the codebase already gives you (leverage, don't rebuild)

- **Lineage is video-ready.** `VisualGeneration.parent_id`/`chain_root_id` was explicitly
  designed to "unify stills and video onto one path" (models.py:91). A clip is a generation
  whose parents are its boundary keyframes; a scene is a chain.
- **The refinement path is proven end-to-end.** `draft --from <gen_id>`/`--image` attaches a
  `VisualSource`; `generate._provision_source` uploads it and `graph_build.apply_source_filenames`
  writes it into the template's `init_image` slot. FLF2V and Qwen-edit are generalizations of
  this from one source image to several.
- **Workflow templates + slot inference are the extension point.** `workflow register` with
  propose→confirm already handles ambiguity; video support is mostly *new topology patterns* in
  `slot_inference`, not new architecture.
- **A Wan 2.2 I2V graph is already registered material** (`workflows/wan2.2-i2v-14B-lightx2v-api.json`):
  dual high/low-noise UNETs, lightx2v 4-step LoRAs, `WanImageToVideo`, `CreateVideo`(fps=16) →
  `SaveVideo`. The FLF2V graph is a sibling of this file. Note its node IDs are
  subgraph-namespaced (`"129:98"`) — string keys, so existing graph-walking code is unaffected,
  but keep tests that cover namespaced IDs.
- **Plan → spend cost gating** (`plan_generation` estimate before submit) is exactly the shape
  video needs — video runs just cost 10–30× an image run, so the estimator must become
  per-template (§4.4).

---

## 2. Gaps the implementation must close

| # | Gap | Where |
|---|-----|-------|
| G1 | `ComfyUIClient.images_from_history` only extracts `images`; `SaveVideo` outputs land under a different history key (`videos`/`gifs` depending on ComfyUI version) | `comfyui_client.py` |
| G2 | `VisualSource` carries exactly one image (+ optional mask); FLF2V needs 2 (first/last), Qwen-edit needs 1–3 references | `models.py`, `generate._provision_source`, `graph_build` |
| G3 | `slot_inference` recognizes only t2i/img2img/inpaint topologies; needs `WanImageToVideo`, `WanFirstLastFrameToVideo`, `TextEncodeQwenImageEditPlus`, `CreateVideo`/`SaveVideo`, and dual-sampler (high/low noise) graphs | `slot_inference.py`, `draft._template_modality` |
| G4 | Per-run cost estimate is a single agent-wide learned mean; a 5s FLF2V run and a Z-Image still can't share one estimate | `gpu_tracker.py`, `generate.plan_generation` |
| G5 | No sequence concept: nothing orders clips within a scene or asserts boundary-sharing | new `sequence.py` + batch-file extension |
| G6 | No approval gate: nothing stops a clip from being generated against an unapproved (or drifted) keyframe | `generate.plan_generation` |
| G7 | Canon pins LoRAs only; no reference-sheet pinning for edit-based identity | `canon.py` |
| G8 | Assets are `.png`-oriented (`DEFAULT_ASSET_EXT`, multimodal embed of image bytes); clips are `.mp4` and Voyage multimodal can't embed video directly | `assets.py`, `store.py` |

---

## 3. Target architecture (end state)

```
scene plan (sequence.md, one per scene)
  └─ ordered clip specs, each: first_frame=<gen_id>, last_frame=<gen_id>, motion prompt
keyframes (batch.md, existing flow)
  └─ Qwen-edit specs: --from <prior approved gen> + canon reference sheets → next-beat still
generate (extended)
  ├─ keyframe spend: qwen-edit-2511 template  → PNG asset, PENDING → user approves
  └─ clip spend:     wan22-flf2v template     → MP4 asset, boundary lineage recorded
assembly
  └─ scene manifest (ordered clip paths + durations) → consumed by edit-brief
```

Three workflow templates are registered (names used throughout this plan):

| Template | Graph | Modality | Sources |
|---|---|---|---|
| `qwen-edit-2511` | Qwen-Image-Edit 2511 + Lightning 4-step LoRA (+ optional style LoRA) | `edit` | 1–3 images (base frame + reference sheets) |
| `wan22-flf2v` | Wan 2.2 14B FLF2V, dual UNET + lightx2v LoRAs, 81 frames @ 16fps | `flf2v` | 2 images (first, last) |
| `wan22-i2v` (exists) | current I2V graph | `i2v` | 1 image |

---

## 4. Implementation phases

Each phase is independently shippable and test-gated. Est. sizes assume the existing test
patterns (httpx MockTransport for the client, fixture graphs for slot inference).

### Phase 0 — Manual validation + graph export (no code)

Goal: prove the two new graphs on a throwaway pod before writing any agent code.

1. Spin an eval pod on a **separate volume**: `POD_NAME=video-eval NETWORK_VOLUME_ID=<new-vol> scripts/pod up`.
2. Download to the eval volume:
   - Qwen: `qwen_image_edit_2511_bf16.safetensors` (or fp8 — the PRO 6000's 96GB takes bf16
     comfortably), `qwen_2.5_vl_7b_fp8_scaled.safetensors` (text encoder), `qwen_image_vae.safetensors`,
     `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (LoRA).
   - Wan FLF2V: reuse the wan2.2 14B I2V high/low-noise fp8 UNETs, `umt5_xxl` CLIP,
     `wan_2.1_vae`, lightx2v 4-step LoRAs already used by the I2V graph — the ComfyUI native
     Wan 2.2 FLF2V template runs on the same weights with a `WanFirstLastFrameToVideo` node.
3. In the ComfyUI browser UI: load the native Qwen-Edit-2511 template and the Wan 2.2 FLF2V
   template; run the three hard beats from the bake-off doc (bar two-shot with exact waitress
   outfit; jazz backs-to-camera; storefront) as keyframe-pair → clip tests.
4. Export both graphs in **API format** and commit them to `packages/visual-generation/workflows/`
   as `qwen-image-edit-2511-api.json` and `wan2.2-flf2v-14B-lightx2v-api.json`.
5. Record settings that worked (steps, cfg/shift, instruction phrasing) as technique lessons.

Exit criteria: one FLF2V clip generated from two Qwen-edited keyframes of the same shot, judged
at the director bar; both API JSONs in the repo.

### Phase 1 — Client + asset plumbing (G1, G8)

`comfyui_client.py`
- Add `videos_from_history(record)` alongside `images_from_history`: collect descriptors from
  `outputs.*.videos`, `outputs.*.gifs`, and — for ComfyUI versions that report SaveVideo under
  `images` with a video filename — any `images` entry whose filename ends in a video extension.
  Same `{filename, subfolder, type}` shape; `view()` already fetches arbitrary bytes.
- No other client changes: submit/history/view/upload are format-agnostic.

`assets.py` / `constants.py`
- Parameterize asset extension: `write_asset(..., ext=...)`; template modality decides
  `.png` vs `.mp4` at spend time. Keep `DEFAULT_ASSET_EXT` for stills.

`store.py`
- Clip records embed **text-only** (caption + motion prompt) — skip the multimodal image embed
  for `.mp4` assets. Optional later refinement: extract the clip's middle frame with ffmpeg and
  embed that; do not block Phase 1 on it.

Tests: MockTransport history fixtures for each history shape (videos/gifs/images-with-mp4);
asset write with `.mp4`; store upsert of a video generation without image bytes.

### Phase 2 — Slot inference + modality for video/edit graphs (G3)

`slot_inference.py`
- New class sets:
  `_VIDEO_LATENT_CLASSES = {"WanImageToVideo", "WanFirstLastFrameToVideoLatent", "WanFirstLastFrameToVideo"}`,
  `_EDIT_ENCODE_CLASSES = {"TextEncodeQwenImageEditPlus", "TextEncodeQwenImageEditPlusAdvance"}`,
  `_VIDEO_SAVE_CLASSES = {"SaveVideo", "CreateVideo"}`. Verify exact class names against the
  exported Phase-0 JSONs — treat the JSONs, not docs, as ground truth.
- New slots inferred:
  - `first_frame` / `last_frame`: trace the video-latent node's image inputs back to their
    `LoadImage` nodes (FLF2V has two distinct image inputs; I2V one → existing `init_image`).
  - `length` (frames) and `fps`: literals on the video-latent node and `CreateVideo`.
  - `edit_image_1..3`: the edit-encode node's image inputs traced to LoadImage nodes, in input
    order (order is meaningful — instructions say "the person from image 1").
  - Dual-sampler graphs: the wan graph has two `KSamplerAdvanced` nodes (high-noise then
    low-noise). Seed lives on the first (`add_noise: enable`). `_find_sampler` must return the
    noise-adding sampler as the seed carrier and map `steps` to the shared step primitives
    (they're `PrimitiveInt` nodes feeding both samplers via switches in the exported graph —
    slot-map those primitives, not the sampler fields). Where inference can't disambiguate,
    report ambiguity — the register propose→confirm loop resolves it once, which is the
    existing contract.
- `draft._template_modality`: return `"flf2v"` (two frame slots), `"i2v"` (one frame slot +
  video save), `"edit"` (edit-encode present) ahead of the existing three.

Tests: fixture = the two committed API JSONs; assert inferred slot maps exactly (the pattern
`tests/test_slot_inference.py` already uses for `flux_txt2img_api.json`).

### Phase 3 — Multi-image sources + keyframe drafting (G2, G7)

`models.py`
- Extend `VisualSource` additively (no new entity, keeps batch round-trip trivial):
  ```python
  class VisualSource(BaseModel):
      from_generation: str | None = None      # existing — base/init image
      image_path: str | None = None           # existing
      mask: str | None = None                 # existing
      last_from_generation: str | None = None # NEW — flf2v last frame
      last_image_path: str | None = None      # NEW
      references: list[RefImage] = []         # NEW — qwen-edit ref sheets (path or gen_id, ordered)
  ```
- `VisualGeneration`: add `parent_last_id: str | None` so a clip records both boundaries
  (`parent_id` = first frame, `parent_last_id` = last frame); add
  `clip: dict | None` in `settings` conventions (`{"length": 81, "fps": 16}` rides the existing
  model-agnostic `settings` dict — no schema change needed for those).

`generate.py`
- `_provision_source` → `_provision_sources`: upload base + last + references, return a
  provision object carrying pod filenames per semantic slot; `apply_source_filenames` writes
  each into its slot (`init_image`/`first_frame`, `last_frame`, `edit_image_N`).
- Modality validation at plan time (mirrors the existing img2img check): `flf2v` spec without
  both frames → skip with warning; `edit` spec without a base → skip.

`canon.py` (G7)
- `CanonSubject` gains `reference_sheet: list[str]` (paths or gen_ids, ordered: identity sheet
  first, outfit sheet second). When a canon subject is present in an `edit`-modality spec,
  enforcement appends the subject's sheets to `source.references` (capped at the template's
  edit-image slot count, warn on overflow) — the reference-set analog of LoRA pinning. `canon
  set/edit` CLI grows `--ref <path-or-gen-id>` (repeatable).

`draft.py` / `cli.py`
- `draft --from <gen_id> --template qwen-edit-2511 "same shot: Celeste now reaching for the door"`
  becomes the keyframe-editing gesture. Add `--last-from <gen_id>` / `--last-image <path>` for
  flf2v drafts and `--ref` (repeatable) for manual references. The drafting chain prompt for
  `edit` modality gets a small addendum: phrase instructions as image-addressed edits
  ("the person from image 2 …", "keep camera, background, lighting; change only …").

Tests: batch round-trip with the new source fields; provisioning uploads N images with
collision-proof names; canon ref-sheet pinning; modality validation warnings.

### Phase 4 — Sequences, approval gating, video cost (G4, G5, G6)

`sequence.py` (new, ~modeled on `batch_file.py`)
- `sequence.md` per scene: ordered clip specs, HTML-comment JSON metadata,
  `read_sequence(write_sequence(s)) == s` invariant:
  ```
  <!-- vg-sequence: {"project": "short-film", "scene": "bar", "fps": 16, "clip_frames": 81} -->

  ## clip 1 — narrator enters, Celeste looks up
  <!-- vg-clip: {"clip_id": "c1", "first_frame": "<gen_id A>", "last_frame": "<gen_id B>",
       "workflow_ref": "wan22-flf2v", "settings": {...}, "seed": ..., "order": 1} -->
  stop-motion felt animation, the narrator walks in from the left, Celeste looks up ...
  ```
- Structural validation: `order` contiguous; `clip[n].last_frame == clip[n+1].first_frame`
  (boundary sharing — a hard error, not a warning); every referenced gen_id exists.
- `sequence plan <scene>` CLI: given the scene's approved keyframes in order, scaffold the
  clip list with shared boundaries pre-wired, motion-prompt bodies drafted by the existing
  chains (one Claude call per clip, `technique_lessons` retrieval included).

`generate.py` — approval gate (G6)
- At plan time for `flf2v`/`i2v`/`edit` specs whose sources are `from_generation` refs: load
  the referenced generation; if `reaction` isn't positive (use the existing reaction vocabulary;
  a `--allow-unapproved` flag overrides), **skip the spec** with a clear message. This is the
  single most important guard in the whole pipeline: it's what makes FLF2V's "every boundary is
  an approved still" promise real.

`gpu_tracker.py` — per-template estimates (G4)
- `estimate_per_run_cost(prior_costs, rate)` → `estimate_per_run_cost(prior_costs, rate, *, workflow_ref)`:
  learned mean is computed **per `workflow_ref`** (query prior generation records filtered by
  template); cold-start defaults become per-modality constants
  (`DEFAULT_PER_RUN_MINUTES_VIDEO ≈ 8–12` at ~$2.09/hr ⇒ ~$0.28–0.42/clip default vs the current
  image default). The plan→spend gate then shows an honest session estimate for a 12–18 clip
  scene before the first submit.
- Poll timeout: `DEFAULT_POLL_TIMEOUT_SEC` must scale per modality (video runs are minutes,
  not seconds) — make it a template-level override in `settings`.

Tests: sequence round-trip + boundary validation errors; approval gate skip/override; per-ref
estimate isolation (image history doesn't contaminate video estimates).

### Phase 5 — Scene assembly + production run

- `sequence render <scene.sequence.md> --endpoint <url>`: plan → gate → spend the scene's clips
  in order; on completion write `scene-manifest.json` (ordered clip asset paths, durations,
  boundary gen_ids) — the artifact `edit-brief` discovers by `project_id` for the final cut.
- Production checklist per scene: approve all N+1 keyframes → `sequence plan` → review motion
  prompts → `sequence render` → react to clips (reaction/notes feed technique lessons exactly
  as stills do).
- Assembly (concat, VO alignment, music) stays outside this agent — it's edit-brief/DaVinci
  territory; the manifest is the handoff. Optional post steps (FILM interpolation to 32fps,
  SeedVR2 upscale) are deliberate non-goals for v1; add as separate templates later if wanted.

---

## 5. Keyframe production method (the craft loop this enables)

Per scene (one camera setup):
1. **Scene-opening keyframe** (amended 2026-07-15, audit §17): the scene's approved framing
   plate with characters inserted by sequential masked edits — not a fresh Z-Image draft
   (Z-Image is non-canonical ideation only). Approve it.
2. **Each subsequent keyframe**: `draft --from <last approved> --template qwen-edit-2511` with a
   same-shot instruction; canon auto-appends character/outfit sheets as references. Generate,
   react, approve. This re-anchors identity and the Coraline aesthetic at every boundary —
   drift can't accumulate because every boundary is human-approved.
3. **Clips**: `sequence plan` wires approved keyframes into boundary-shared clip specs;
   `sequence render` spends them. Motion prompts describe the action between the two frames
   (loose VO pacing — actions, not lip-sync).

Budget sanity: 4 scenes × (13–19 keyframes + 12–18 clips). At Lightning-4-step Qwen speeds,
keyframe iteration is cheap; clips dominate GPU cost, which is why the per-template estimator
and the plan-time gate land in the same phase as the renderer.

---

## 6. Risks and mitigations

- **History output shape for SaveVideo varies by ComfyUI version.** Phase 1 tests fixture all
  three observed shapes; `videos_from_history` unions them. Verify against the eval pod's live
  `/history` JSON before writing the parser.
- **Slot inference on the wan graph's switch-node indirection** (`ComfySwitchNode` feeding
  steps/cfg): if tracing through switches is brittle, fall back to register-time confirm — the
  propose→confirm loop exists precisely for graphs inference can't fully resolve. Do not build
  a general switch-resolver for v1.
- **Wan smooths away the stop-motion look.** Mitigate in motion prompts ("stop-motion felt
  animation" is already the pattern in the committed i2v graph's positive prompt), keep clips
  at 81 frames, and rely on approved keyframes re-pinning the aesthetic. If shimmer persists,
  a style-LoRA on the wan stack is a template variant, not a code change.
- **Qwen pixel drift on repeated edits.** Every keyframe is human-approved before it becomes a
  boundary; constrain instructions ("keep camera, background, lighting"). The approval gate
  (Phase 4) is the backstop.
- **VRAM/volume pressure**: Qwen bf16 (~40GB) + Wan 14B fp8 pair coexist on the 96GB PRO 6000
  but not necessarily loaded simultaneously — ComfyUI unloads between graphs; keyframe and clip
  sessions can also simply be separate `generate` invocations.
- **Cost runaway on a bad scene render**: the existing `--max-session-cost` applies unchanged;
  per-template estimates make it meaningful for video.

## 7. Test plan summary

- Unit: history video extraction (3 fixture shapes); slot inference on both committed JSONs;
  VisualSource round-trip; multi-upload provisioning; canon ref pinning; sequence round-trip +
  boundary/order validation; approval gate; per-template cost estimation.
- Integration (mocked ComfyUI): full `sequence render` of a 2-clip scene — plan, gate, spend,
  manifest — asserting lineage (`parent_id`/`parent_last_id`) and shared-boundary uploads
  (the shared frame uploads once per session, referenced twice).
- Live smoke (eval pod, manual): one keyframe edit + one FLF2V clip through the CLI end-to-end
  before the production volume ever sees the new models.

## 8. Suggested build order recap

0. Manual validation + export graphs (no code) →
1. Client/assets (small) →
2. Slot inference + modality (medium; the riskiest code) →
3. Sources + keyframe drafting + canon refs (medium) →
4. Sequences + gate + cost (medium) →
5. Render + manifest + production run (small code, large craft).
