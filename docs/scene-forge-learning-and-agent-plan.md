# Scene-Forge — 3D Shot-Production Skill Track & Agent

A standalone learning-and-build project, deliberately decoupled from the Coraline film's critical
path. The goal is twofold: (1) acquire the Blender-centered 3D shot-production skill set the
consolidated audit described (persistent sets, camera libraries, lighting presets, multi-pass
renders, structured shot schemas), and (2) productize it as a new agent in the `agent-stack`
monorepo — working name **`scene-forge`** — that turns a structured shot spec into a rendered
pass stack via headless Blender. The capstone reconnects to the film: a versioned 3D sports-bar
set producing a full pass stack for the toast two-shot, usable as the Blender arm of Test D.

The audit's 3D layer was the right idea attached to the wrong project phase. This document is
where that idea lives now.

---

## 1. What you're actually building

Two artifacts, developed in parallel once fundamentals are in place:

**The skill set.** Enough Blender to model and light a stylized miniature set, place cameras
with intentional lenses, and drive all of it from Python. Not a generalist 3D education — a
targeted shot-production track. Explicit non-goals for this track: character modeling,
sculpting, rigging, and animation (revisit only if a film ever needs camera moves or 3D
character proxies; the audit's "rigged proxies" stay out of scope).

**The agent.** `packages/scene-forge/` following the stack's established shape:

```
scene-forge/
  src/scene_forge/
    models.py         # SetAsset, CameraSpec, LightingPreset, ShotSpec, PassStack (Pydantic)
    blender_client.py # headless invocation: blender --background <set.blend> --python-expr / bpy-as-module
    scene_build.py    # writes ShotSpec values into the .blend scene graph (the graph_build analog)
    render.py         # plan/render split: plan resolves assets + validates spec + estimates passes/workload; render executes Blender (wall-time and device recorded, no paid-API metaphor)
    assets.py         # versioned set/camera/lighting registry (the model_registry analog)
    passes.py         # beauty / depth / normal / segmentation (cryptomatte) / mask extraction
    cli.py            # command tree: set list | camera list | light list |
                      #   shot validate <spec> | shot plan <spec> | shot render <spec> | shot inspect <run-id>
  sets/               # versioned .blend files + sidecar JSON manifests
  tests/
```

The design deliberately mirrors `visual-generation`: a **spec → template → concrete graph**
pipeline where the "template" is a `.blend` set and the "graph write" is scene-graph
parameterization via `bpy`; a plan/render split (plan resolves and validates, render executes; wall-time and device are recorded as the cost axis); versioned assets with manifests as the registry; and the same test discipline
(pure-function scene builders, golden-image or checksum tests on tiny renders). Shot specs use the **neutral shared schema** defined in the audit's shot layer (shot_id,
set_asset, framing_asset, characters, pose_guides, regions, props, lighting_intent, outputs):
Scene-Forge interprets `set_asset` as a .blend and `framing_asset` as a named Blender camera,
while the film's plate pipeline reads the same fields as plates. Shared vocabulary, independent
implementations — an integration seam, not a dependency. `shot render bar_05_toast` loads the
set version, applies camera + lighting preset, places proxies, and emits the pass stack to a
manifest-tracked output dir.

Key technical choices: Blender 4.5 LTS (pinned for the MVP; see CP6) on the M5 MacBook with Cycles/Metal;
**locked decision — use Blender's bundled Python via `blender --background --python …`** (Blender
owns the compatible Python environment and the .blend format, add-on/data-block APIs match the
installed version, and CI is reproducible; standalone `bpy` pip wheels are evaluated only after
CP5 and only against a concrete deployment need); Cryptomatte for object segmentation; EXR
multilayer output preserving source depth data alongside normalized previews.

---

## 2. Learning plan

Hour budgets assume evenings/weekends alongside work; they're effort estimates, not calendar
commitments. Each stage ends at a checkpoint (§3) — don't start the next stage until the
checkpoint passes, mirroring the audit's gate philosophy.

**Stage 0 — Environment & first light (~4h).** Install Blender, learn viewport navigation,
render one default-cube Cycles frame on Metal, then render the same frame headless from the
terminal (subprocess route — locked, see §1). Skim the manual's scene/data-blocks concepts page so
`bpy.data` vs `bpy.context` makes sense before any scripting.

**Stage 1 — Modeling fundamentals (~15h).** The classic beginner arc (a guided-course pass like
the donut tutorial or equivalent, at 1.5× speed) but graded against *your* target: box modeling,
modifiers (bevel, array, solidify, boolean), simple UV thinking, basic materials. Then apply it:
model the sports-bar **gray-box** — walls, storefront glass, counter, three high-top tables,
stools, two TV slabs, door. No materials beyond flat grays. This is deliberately the audit's
"minimal blockout," built as a learning artifact rather than a film dependency. Close the stage
with a minimal agent-shaped prototype: a JSON spec (`{"set": "sports-bar-v0", "camera": "main",
"lighting": "graybox", "output": "./renders/test"}`) rendered via a trivial script — no Pydantic,
no package — so every later scene convention is addressable by stable names rather than manual
viewport state.

**Stage 2 — Cameras, lighting, look (~12h).** Camera objects — learn focal length, sensor size,
camera distance, aperture, and focus distance as **one framing system**, reproducing a target
reference rather than assuming a short lens (the miniature impression comes from the combination
of scale, distance, DOF, focus distance, lighting scale, and surface irregularity; short focal
lengths alone add wide-angle distortion). Framing against reference stills. Three-point and practical-source lighting; emissive materials for the
Edison bulbs and TV screens; warm/amber grading toward the bar's mood board. Light the gray-box
to a recognizable "moody sports bar at night" beauty render. This stage is where the Coraline
*miniature* feel gets studied deliberately: scale cues, DOF, slight imperfection.

**Stage 3 — Render passes & compositor (~8h).** View layers and passes: Z/depth (and Mist as
the normalized alternative), normals, Cryptomatte for per-object masks; multilayer EXR; the
compositor as a pass-extraction tool. Produce the full pass stack for one camera of the gray-box
and inspect every layer. Treat segmentation as five distinct mask families from the start:
object masks (counter, tables, TVs), character-region masks (proxy objects in dedicated
collections with stable IDs), holdout/occlusion masks, floor-contact regions, and a
background-protection mask (the Gate 2A input). Understand what a downstream ControlNet/edit model actually wants
(normalized depth PNGs, binary region masks) and write the export accordingly.

**Stage 4 — bpy scripting & headless production (~15h).** The pivot from artist to pipeline:
drive everything from Python. Scripts that load a .blend, set the active camera by name, apply a
lighting preset (collection visibility or node-group swap), place placeholder character proxies
at named empties, configure passes, and render headless to a structured output dir. Parameterize
via JSON in / manifest out. By the end, no GUI is needed to produce a pass stack.

**Stage 5 — The agent (~20h).** Wrap Stage 4 in the stack's conventions: Pydantic models,
versioned asset registry with manifests, plan/render commands with an optional estimate report, tests (scene-builder unit
tests against a fixtures .blend; a tiny 64×64 golden-render smoke test), README in the house
docstring style. Register nothing with the film project yet — `scene-forge` stands alone.

**Capstone (~15h).** §4.

Total ≈ 90–95h (CP6 adds a small reproducibility pass at the end of Stage 5). If that reads heavy, it is — that's the point of decoupling it from the film,
which needs none of it to ship.

---

## 3. Checkpoints & benchmarks (proposed — for your sign-off)

Each is pass/fail and produces an artifact worth keeping.

- **CP0 — Reproducible headless render.** A provided fixture scene renders at 512×512 from one
  documented command, headless, and reruns successfully from a clean shell. The run writes a
  manifest recording Blender version, device, engine, samples, and elapsed time — performance is
  recorded as a baseline, not gated. Artifact: command + frame + manifest.
- **CP1 — Gray-box bar.** Layout agreement with the approved master plate from the film's main
  framing (counter right, high-tops receding, storefront, two TV positions) — plus mechanical
  requirements that matter once bpy drives the file: named objects for walls/counter/storefront/
  TVs/tables/stools/door (no `Cube.017`), real or internally consistent units, applied transforms
  and sensible origins, a documented collection naming convention, and camera framing matched to
  selected plate landmarks. The scene must satisfy a machine-readable contract — required
  semantic anchors and collections exist by exact name (`CAM_MAIN`, `ANCHOR_NARRATOR`,
  `ANCHOR_CELESTE`, `CONTACT_NARRATOR`, `CONTACT_CELESTE`, `OCCLUDER_BAR`, `MASK_BACKGROUND`,
  `COLL_SET`, `COLL_PROXIES`, `COLL_LIGHT_AMBER`) — and CP1 fails if any are missing. Artifact:
  `sets/sports-bar-v0.blend`.
- **CP2 — Lit beauty render.** One render a stranger would caption "miniature sports bar at
  night." Gates: practicals visibly motivate the illumination, readable foreground/background
  separation, controlled exposure, intentional camera + DOF, at least three simple purpose-built
  materials, and the image reads correctly at thumbnail size. Gray-box materials may remain
  where beauty isn't needed yet. Artifact: beauty PNG + the .blend at `v0.2`.
- **CP3 — Full pass stack.** One command-line render emitting beauty + depth (source HDR EXR
  **and** normalized preview PNG — never discard the source data) + normals + ≥3
  Cryptomatte-derived object masks (counter, tables, TVs) + at least one grounding output (a
  shadow-catcher pass, direct/indirect shadow contribution, character-contact shadow mask, or
  AO pass — Scene-Forge's value is reduced without a usable grounding pass, and the film's
  escalation trigger is specifically shadow grounding) with a JSON manifest. Gates: masks
  pixel-aligned with beauty; normalized depth range documented; foreground/background ordering
  visually verified; object IDs map to manifest entries; and **one fixed downstream conditioning
  test** (depth-ControlNet or edit-model) is run with its output saved alongside the checkpoint.
- **CP4 — Parameterized headless shot.** A single JSON spec switches camera (two named cameras),
  lighting preset (amber-night vs day), and proxy placement, headless, no .blend hand-edits
  between runs. Gate: **deterministic scene resolution and reproducible render configuration** — two consecutive runs produce exactly equal resolved specs, manifests,
  object/camera transforms, and asset hashes; **images are compared perceptually or with pixel
  tolerance, never byte-equality** (GPU output varies across drivers, Blender versions, devices,
  and denoisers — reserve exactness for deterministic CPU fixture renders).
- **CP5 — Agent MVP.** `uv run scene-forge shot render <spec>` executes CP4 through the package
  with tests green at three levels: **unit** (schema validation, asset resolution, transform
  application, pass configuration, output paths), **scene-state** (inspect the resulting .blend/
  scene for camera identity, transforms, collection visibility, render settings, object IDs),
  and **render smoke** (pinned Blender version, small fixture scene, perceptual-hash or
  thresholded comparison, diagnostic diff image on failure) — plus **failure-path tests**:
  missing Blender executable, missing set/camera asset, missing required anchor, unsupported
  Blender version, invalid output path, Cryptomatte unavailable, render timeout, partial output,
  nonzero subprocess exit, and corrupt .blend must each produce an actionable error, not a
  traceback. Artifact: the package at reviewable quality (I'll review it like the
  visual-generation audit).
- **CP6 — Clean-environment reproducibility.** From a fresh clone/worktree: documented Blender
  path discovery, no machine-specific absolute paths, example assets installed or referenced
  correctly, one fixture spec renders successfully, the manifest records Blender + package
  versions, and failure messages are actionable when Blender or an asset is missing. **Support
  policy: the MVP supports Blender 4.5 LTS only** — other versions are added explicitly later,
  keeping golden tests, pass APIs, and CI stable. This is the difference between a script on
  your laptop and a reusable agent.

## 4. Capstone — the Test D arm, produced by the agent

**Deliverable:** `sports-bar-v1` as a versioned set asset, and the film's toast two-shot framing
rendered as a complete pass stack **through the agent CLI in one command**, with two character
proxies at blocking positions and narrator/celeste region masks in the manifest.

**Pass criteria (agreed before starting, per the audit's experiment discipline):**
1. Layout matches the approved master plate closely enough that an edit model conditioned on the
   capstone's depth map preserves the plate's geometry (run Test D once with this arm — that's
   the integration proof, and the only point where the capstone touches the film).
2. The same command re-run reproduces the stack deterministically.
3. The camera specification is versioned (`bar_counter_two_shot_01`) with explicit lens and
   sensor metadata, and can be duplicated into a second named camera preserving that metadata (a
   camera asset is one framing; new framings are new named cameras, not retargeted ones).
4. Region masks drop into the visual-generation sequential-masked-edit flow without manual
   cleanup — narrator and Celeste proxies carry stable object IDs and non-overlapping manifest
   labels.
5. Wall-time budget ≤ 5 min per stack on the M5, reported as two figures — render time and
   end-to-end command time — with machine/device, resolution, samples, denoiser, included
   passes, and warm-vs-cold Blender startup recorded in the manifest.

**Explicitly deferred beyond the capstone:** rigging/animation, the living-room and jazz-club
sets (repeat of a solved problem — build only if the film's Test D arm is actually adopted),
and any integration that makes the film *depend* on scene-forge. The dependency direction stays:
the film may *consume* scene-forge outputs; it must never *wait* on them.

## 5. Working agreement

- The film's plate-first path proceeds regardless of this track's pace; a §9 audit trigger is
  the only event that promotes scene-forge onto the film's critical path.
- Checkpoints are reviewed as they land (screenshots/renders in chat are enough); we adjust the
  plan at any checkpoint rather than mid-stage.
- If, by CP2, the craft isn't enjoyable enough to justify ~90h, the honorable exit is: keep the
  gray-box + CP3 pass stack (already a usable Test D arm), skip Stages 4–5, and fold the
  learnings into a technique lesson.
