# Production Testing Playbook — visual-generation (`celeste-you-dangerous`)

A step-by-step harness for exercising **every** way to generate the images for this story in
production, so we can confirm the recent implementation behaves as we both expect. Run a
workflow, capture the marked output, and report back; we adjust from there.

**What we're validating** (the recent work):

- **Knowledge surfacing** — categorized Qdrant knowledge actually reaches the LLM at draft time.
- **Direct verification** — `knowledge-verify` + the `── Knowledge surfaced ──` provenance block prove it, deterministically.
- **Doc compilation** — your own `directed.md`/`script.md`/etc. compile into the prompt (`── Compiled from ──`), so you feed key points, not hand-written prompts.
- **Canon (text)** — locked identity descriptors reach every scene regardless of LLM discretion (`── Canon enforced ──`).
- **Batch anchor continuity (B)** — `batch build --from` carries a character across scenes via img2img.
- **Character LoRA (C)** — `canon set --lora` pins a trained character LoRA into every scene the subject appears in.

---

## Conventions (read once)

- **Invocation.** Examples use the `agent` wrapper from the repo root:

  ```bash
  agent() { op run --env-file=.env -- uv run "$@"; }   # one-time, in your shell
  ```

  So `agent visual-generation draft …` = `op run --env-file=.env -- uv run visual-generation draft …`.
  Anything that hits an API (Anthropic craft, Voyage embeddings, ComfyUI) needs this. Pure
  file ops (`canon set/show`, `batch list`) work under plain `uv run` too, but using `agent`
  everywhere is harmless.
- **Free vs. paid.** `draft`, `redraft`, `batch build/rebuild`, `knowledge-verify`, `digest`,
  `recall`, `canon *` are **free** (Claude tokens are pennies; no GPU). Only **`generate`**
  spends GPU and needs a live pod.
- **`<ENDPOINT>`** = your pod's ComfyUI URL on port 8188 (e.g. `https://<pod-id>-8188.proxy.runpod.net`),
  printed by `scripts/pod up`.
- **`<GEN_ID>` / `<SPEC_ID>`** = ids echoed by earlier steps (12-char prefixes are fine for `report`).
- **Project facts this playbook assumes** (already true on your machine):
  - Slug: `celeste-you-dangerous`; docs at `~/agent-projects/celeste-you-dangerous/` (`directed.md`, `script.md`, `techniques.md`, `story.md`).
  - `directed.md` scenes: **Arrival**, **The Adversity and the Advesary**, **The Win and the Loss**, **Again and Again**.
  - **Two visible leads** → **two canon subjects**: **Chris** (the narrator puppet — dreadlocks) and **Celeste** (the waitress — yarn hair past her shoulders), who share scenes 2–4. **No character LoRA yet** — Workflow 6 trains **one per lead**.
- **What to capture & report back per step:** paste the marked **`── … ──`** blocks (Knowledge
  surfaced / Compiled from / Canon enforced), plus anything under a ⚠. Those are the signal.

---

## Phase 0 — Prerequisites (shared by all workflows)

### 0.1 — Qdrant up (retrieval + memory backend)

```bash
docker compose -f infrastructure/docker-compose.yml up -d qdrant
curl -s http://localhost:6333/ | head -1        # expect a JSON banner, not a refusal
```

- **Does:** starts the vector store the draft/verify/memory legs read. If it's down, retrieval
  legs silently degrade to empty (and Qdrant-dependent tests auto-skip).
- **Verify:** `agent visual-generation knowledge-verify "z-image turbo dreadlocks" --project celeste-you-dangerous`
  should show non-zero collection sizes (next section). If everything reads `unreachable/absent`, Qdrant isn't up.

### 0.2 — Confirm project docs + canon for BOTH leads (free, instant)

This story has **two visible leads**, so canon needs **two subjects** — Chris and Celeste. Canon's
`subjects` array holds both; each `canon set` upserts one subject (keyed by `aliases[0]`) without
touching the other.

```bash
# Chris (the narrator puppet). Note "Chris"/"the man" as aliases so the lock fires whether a
# prompt names him "the narrator" OR "Chris" — your prompts use both.
agent visual-generation canon set celeste-you-dangerous \
  --alias "the narrator" --alias "narrator" --alias "@narrator" \
  --alias "Chris" --alias "the man" \
  --locked "a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back" \
  --forbid "short hair" --forbid "shoulder-length" --forbid "buzz cut"

# Celeste (the waitress). Descriptor seeded from your existing renders; outfit deliberately
# OMITTED (it changes per scene). NO --forbid (see the caveat below).
agent visual-generation canon set celeste-you-dangerous \
  --alias "Celeste" --alias "the waitress" \
  --locked "a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes"

agent visual-generation canon show celeste-you-dangerous
ls ~/agent-projects/celeste-you-dangerous/
```

- **Does:** locks both leads' identities deterministically. `canon show` should now list **two
  subjects** — each with `aliases`, `locked`, (`forbid` for Chris). **No `lora:` line yet** (Workflow 6 adds one per lead).
- **⚠ Forbid bleeds across subjects — keep forbid lists minimal with two leads.** `--forbid` strips
  the phrase from the **whole prompt**, not just its own subject's text. So in a two-shot:
  - Chris forbids `shoulder-length` → that's why Celeste's hair is phrased **"past her shoulders"**
    (not the token "shoulder-length"), so it isn't clipped.
  - **Do NOT give Celeste `--forbid "dreadlocks"`** — it would strip *Chris's* "long black yarn
    dreadlocks" in any scene they share. Her positive descriptor ("hair past her shoulders") does
    the differentiating instead.
  - Rule of thumb: prefer distinguishing leads by their **positive `locked` text**; use `forbid`
    only for a token that can't collide with the other lead's locked descriptor.
- **Report back:** the `canon show` output (both subjects).

### 0.3 — (PAID workflows only) Pod up + model registry sync

```bash
scripts/pod up                                  # prints the ComfyUI endpoint; note it as <ENDPOINT>
agent visual-generation model sync --endpoint <ENDPOINT>
agent visual-generation model list
```

- **Does:** `pod up` creates a fresh RunPod ComfyUI pod (create/delete lifecycle — never start/stop).
  `model sync` reads the pod's `/object_info` and writes the local registry (`~/agent-data/visual-generation/models.json`),
  preserving any manual `identity_bearing` flags. `model list` shows what's registered.
- **Expected:** sync plan line `+N new, ~M refreshed, …`; `model list` shows checkpoints/LoRAs/VAEs.
- **Options:** `model sync --yes` skips the write confirmation.
- **⚠ Cost discipline:** the pod bills continuously while up (~$2/hr). `scripts/pod down` deletes it
  when done; the volume survives. `generate` reminds you when a batch is drained.
- **Skip this** for any free-only workflow (1, and the draft/compile halves of 2–8).

---

## Workflow 1 — Prove the knowledge surfaces (free, read-only) ⭐

**Path for:** confirming ingested research is actually reachable *before* you spend any GPU.
This is the centerpiece of the "stop ignoring my knowledge" work.

### Step 1.1 — Verify a visual query

```bash
agent visual-generation knowledge-verify \
  "z-image turbo dreadlocks rooftop puppet" --project celeste-you-dangerous
```

- **Does:** runs the *same* retrieval the draft uses, then prints collection sizes, per-leg
  provenance, and gap flags. No LLM craft, no GPU.
- **Expected — look for:**
  - `── Collection sizes ──` with non-zero counts for `tutorial_research`, `technique_research_outputs`, `visual_generation_memory`.
  - `── Knowledge surfaced (deterministic) ──` with legs like `[reference] Tutorial research (tutorial_research): N hit(s), top 0.xx` and `[strong] Technique reports (technique_research_outputs): N hit(s), …` (other legs: `[locked] Project canon`, `[strong] Prior generations / Technique lessons / Platform facts`, `[reference] Workflow templates`).
  - **`✓ No gaps flagged — relevant knowledge is reachable for this query.`**
- **Options to alter:**
  - `--limit 15` — more hits per leg (default 8); good for seeing how deep a collection goes.
  - `--project` is a label only here (context), so try it with/without.
- **Try this to verify behavior:**
  1. A **non-visual** query to contrast: `knowledge-verify "suno music mastering chain"` — the
     technique-report leg should surface little/nothing visual (proves the `{generation, both}`
     topic-tag filter is actually filtering, not matching everything).
  2. A query you *know* you ingested z-image LoRA-training for: `knowledge-verify "how to train a LoRA for z-image turbo"` — expect the tutorial leg to surface it (this is the knowledge that makes Workflow 6 a research-→-execute task).
- **Report back:** the full output of 1.1, plus the contrast query in (1).

### Step 1.2 — (optional) Categorization audit

```bash
agent visual-generation digest celeste-you-dangerous
```

- **Does:** bounded "where did I leave off" view — recent generations + reactions, confirmed
  lessons, pending. Read-only. Empty early on; fills as you `report`.
- **Report back:** whatever it shows (sets a baseline for the memory-loop check in Workflow 9).

---

## Workflow 2 — Single hand-guided draft → generate → report (the core loop)

**Path for:** the simplest end-to-end — one image, you steer it with a one-line intent.
Exercises: provenance surfacing + canon enforcement on a single text2img.

### Step 2.1 — Draft (free)

```bash
agent visual-generation draft \
  "the narrator on a rooftop at dusk, wide cinematic shot, neon glow" \
  --project celeste-you-dangerous
```

- **Does:** retrieves knowledge, has Claude compose a full prompt + settings + model/LoRA picks,
  enforces canon deterministically, and appends the spec to the project's batch file. **No GPU.**
- **Expected — look for:**
  - `Status: complete`, a `Cost: $0.00xx (Claude — GPU is spent at generate)`, a `Spec:` id.
  - `Prompt:` containing the **locked puppet descriptor** even though you didn't type it.
  - `── Knowledge surfaced (deterministic) ──` block.
  - `── Canon enforced (deterministic) ──` with `injected canon for 'the narrator'` (and a
    `removed forbidden phrasing …` line if the model reached for "short hair" etc.).
  - `Appended to: …/celeste-you-dangerous.batch.md` and a `Next: … generate …` hint.
- **Options to alter:**
  - `--template <name>` — force a specific workflow template (default: top retrieved).
  - `--model opus` / `--model sonnet` — which Claude crafts the spec (alias resolves via the provider seam).
  - `--provider anthropic` — the LLM provider (default from config; `openai` is a stub and will raise — that's expected).
  - `-o <path>` — write to a different batch file (keeps your main batch clean while testing).
- **Try this to verify behavior:**
  - Draft once **without** mentioning the narrator (`"an empty neon rooftop, rain, no people"`)
    → the `── Canon enforced ──` block should be **absent** (no subject named = no injection).
    This proves canon is scoped, not blindly appended.
  - Draft mentioning `@narrator` instead of "the narrator" → expect `expanded '@narrator' → canonical descriptor`.
- **Report back:** the Knowledge-surfaced + Canon-enforced blocks, and the final `Prompt:`.

### Step 2.2 — Generate (PAID — needs Phase 0.3)

```bash
agent visual-generation generate \
  ~/agent-data/visual-generation/batches/celeste-you-dangerous.batch.md \
  --section <SPEC_ID> --endpoint <ENDPOINT>
```

- **Does:** resolves the spec's template, uploads any source, renders on the pod, records the
  generation (pending reaction). The `<SPEC_ID>` is from 2.1's `Spec:` line.
- **Expected — look for:**
  - `── GPU cost gate (soft-inform …) ──` with a per-run estimate; a confirm prompt
    (`Spend ~$… ?`) — answer `y`.
  - `── Generation <id> (spec …) ──` with `Asset: <path>`; `[identity-bearing → secured path]`
    appended **only** if the spec used an identity-bearing model/LoRA.
  - `Review, then: visual-generation report <gen_id> …` and a `Report:` path.
- **Options to alter:**
  - `--all` instead of `--section` — render every spec in the batch (used in Workflow 4).
  - `--gpu-rate 2.09` — set the $/hr used for cost tracking (default 0.69; set it to your real pod rate for honest numbers).
  - `--max-session-cost 1.50` — hard ceiling; the run stops before breaching it.
  - `--yes` — skip the confirm gate (don't, while testing — you want to see the estimate).
- **Report back:** the cost-gate block + the `Asset:` line (and whether `[identity-bearing]` showed).

### Step 2.3 — Report (free — closes the memory loop)

```bash
agent visual-generation report <GEN_ID> --reaction liked --rating 4 \
  --notes "dreadlocks read well; push the neon cooler next time" \
  --context "rooftop establishing shot for Arrival"
```

- **Does:** records your reaction (flips pending→complete) into `visual_generation_memory`, so it
  surfaces in future drafts/`recall`/`digest`.
- **Reaction vocabulary:** `loved`, `liked`, `liked_with_changes`, `disliked` (rendered faithfully
  but not to taste — weighs against the *settings*), `render_failed` (intent didn't render —
  direction stays open). `--rating 1–5` is meaningful only for the three positive ones.
- **Try this to verify behavior:** after reporting, run `agent visual-generation recall "narrator rooftop"`
  → the generation should come back as a `[PRIOR GENERATION]`-style hit. That proves the retention loop.
- **Report back:** the `Recorded: …` line, and whether `recall` finds it.

---

## Workflow 3 — Doc-compiled scene draft (no hand-written prompt)

**Path for:** the intended day-to-day — feed key points + a scene name; the agent compiles your
own `directed.md` into the prompt. Exercises: **Part 1.5 doc compilation** + provenance + canon.

### Step 3.1 — Draft from a scene (free)

```bash
agent visual-generation draft \
  --project celeste-you-dangerous \
  --scene "Arrival" \
  --points "wide establishing shot" --points "dusk" --points "neon city below"
```

- **Does:** discovers the project's docs, narrows to the **Arrival** section of `directed.md`,
  compiles that + retrieved knowledge + your points into a prompt Claude composes. No `INTENT`
  string needed.
- **Expected — look for:**
  - `── Compiled from (your project docs) ────` listing `directed.md` (Arrival) and likely
    `brief.md`/`techniques.md` if present — **this is the proof your script fed the prompt.**
  - `── Knowledge surfaced ──` and `── Canon enforced ──` as in Workflow 2.
  - A `Prompt:` that reflects the Arrival beat (not your literal points verbatim).
- **Options to alter:**
  - Drop `--scene` → the **whole** `directed.md` becomes context (broader, less focused).
  - `--points` is repeatable; for a refinement (next workflows) points describe the *change*.
  - `--scene "The Win and the Loss"` etc. — any of the four real headings.
- **Try this to verify behavior:**
  - Run with a **wrong** scene name (`--scene "Nonexistent"`) → expect the compile to fall back
    (whole-doc or a visible "missing input"), never a crash. Confirms degrade-on-absence.
  - Compare the `Prompt:` from `--scene "Arrival"` vs `--scene "Again and Again"` — they should
    differ in beat/tone, proving the scene selection actually changes the compiled context.
- **Report back:** the `── Compiled from ──` block for two different scenes, side by side.

### Step 3.2 / 3.3 — Generate + report

Same as 2.2 / 2.3 (use this spec's id).

---

## Workflow 4 — Whole-story batch build → generate all four scenes

**Path for:** one command compiles a spec for **every** scene of `directed.md`. Exercises: batch
compilation across the real four-scene structure.

### Step 4.1 — Build the batch (free)

```bash
agent visual-generation batch build celeste-you-dangerous -o /tmp/celeste-test.batch.md
```

- **Does:** loops the compile over each `##` scene in `directed.md` (Arrival → Again and Again),
  canon-enforcing each, writing one spec per scene. **Refuses to overwrite** an existing batch
  (use `batch rebuild` to replace). `-o` to a temp path keeps your real `visual-batch.md` untouched while testing.
- **Expected:** an info line per scene as it compiles; a final write to the `-o` path.
- **Inspect:**

  ```bash
  agent visual-generation batch list /tmp/celeste-test.batch.md
  ```

  → **4 specs**, each `[<template>]` with the scene title. Confirm all four scenes are present.
- **Options to alter:**
  - `--model` / `--provider` — same craft controls as `draft`.
  - `batch rebuild celeste-you-dangerous -o <path>` — overwrite/regenerate from scratch.
  - `--from` / `--image` / `--denoise` / `--template` — the **anchor** options (Workflow 5).
- **Try this to verify behavior:** open `/tmp/celeste-test.batch.md` and confirm each spec's
  prompt carries the **locked puppet descriptor** (canon enforced per scene, not just once).
- **Report back:** `batch list` output (all four spec ids + titles).

### Step 4.2 — Generate the whole batch (PAID)

```bash
agent visual-generation generate /tmp/celeste-test.batch.md --all --endpoint <ENDPOINT> --gpu-rate 2.09
```

- **Does:** renders every spec. The gate estimates the **session** cost across all four.
- **Expected:** four `── Generation … ──` blocks; a `── Batch drained ──` reminder to stop the pod.
- **⚠** After this, `scripts/pod down` if you're done — idle pods keep billing.
- **Report back:** the cost-gate estimate vs. the final `Session cost:`, and the four asset paths.

---

## Workflow 5 — Anchor-frame img2img continuity (feature B)

**Path for:** carry the narrator's look across all scenes by anchoring every scene to **one
approved frame** as an img2img refinement. The no-training interim continuity fix.

### Step 5.1 — Get an anchor frame

Pick the best narrator still you've already rendered (e.g. from Workflow 2/4) and note its
`<GEN_ID>`. Or render a dedicated one. (Alternatively, anchor to a file on disk with `--image`.)

### Step 5.2 — Build an anchored batch (free)

```bash
agent visual-generation batch build celeste-you-dangerous \
  --from <GEN_ID> --denoise 0.55 -o /tmp/celeste-anchored.batch.md
```

- **Does:** every scene is composed as an **img2img** refinement off that one frame, so the
  narrator carries across scenes instead of being re-rolled. Auto-targets the
  `visual-workflow-img2img` template when anchored.
- **Expected — look for:**
  - An `Anchoring every scene to '<GEN_ID>' via img2img …` info line.
  - `batch list` shows each spec with the **img2img** template (not the txt2img one).
- **Options to alter:**
  - `--denoise` — **the key knob.** Lower (~0.4) = hold the anchor tighter (more identity, less
    scene change); higher (~0.7) = re-stage the scene more (more variety, less carry). Try
    `0.45` and `0.65` and compare.
  - `--image <path>` instead of `--from` — anchor to an external reference (mutually exclusive with `--from`).
  - `--template <name>` — override the auto img2img template.
- **Try this to verify behavior:**
  - Build the same batch at `--denoise 0.4` and `--denoise 0.7`; generate one scene from each;
    compare how much the narrator's identity holds vs. how much the scene restages. This
    characterizes the honest trade-off (img2img imports composition, so it's strongest when the
    narrator is a recurring framed element — not a perfect face lock).
  - `batch list` both files and confirm the template is the img2img one in both.
- **Report back:** the anchoring info line, `batch list`, and (after generate) a note on how
  identity held at each denoise.

### Step 5.3 — Generate (PAID)

`generate --all` as in 4.2.

---

## Workflow 6 — Character-LoRA continuity (feature C — the durable fix)

**Path for:** the strongest continuity — a **trained character LoRA** pinned into **every** scene a
lead appears in, via canon. Identity travels at the model level, not just the text. This is the only
path that fully locks a face across all four scenes.

This workflow includes the training itself as first-class steps, grounded in your ingested tutorial
**"How to Train a Character LoRA for Z-Image Turbo"** (Seb G., `k0UWypeLcJ4`) — the one Workflow 1
surfaces. Steps 6.1–6.3 produce a LoRA; 6.4–6.6 pin and use it.

> **You have TWO leads, so you run this workflow TWICE — once per lead.** Each gets its **own
> dataset, own trigger word, own `.safetensors`, and own canon pin** on its own subject. The steps
> below are written once with `<CHARACTER>` / `<TRIGGER>` placeholders; substitute each lead's row:
>
> | Lead | Subject alias | `<CHARACTER>` (folder/LoRA/job name) | `<TRIGGER>` | Dataset source |
> |---|---|---|---|---|
> | Chris (narrator) | `the narrator` | `celeste-narrator` | `celestenarr8` | mine existing narrator renders + fan-out |
> | Celeste (waitress) | `Celeste` | `celeste-waitress` | `celestechar8` | **bootstrap from ONE good render** (she had no lock until now — see 6.1) |
>
> **Two different pods.** Training runs on a **separate, manually-deployed Ostris AI-Toolkit pod**
> (a cheap 4090 is plenty) — **not** `scripts/pod` (that script is only for the inference ComfyUI
> pod). Deploy the training pod from the RunPod console; delete it when training finishes. You can
> train both LoRAs in one pod session (two jobs back-to-back) to save spin-ups.

### Step 6.1 — Curate the dataset (free, ~30 min per lead)

- **Goal:** 20–30 images of `<CHARACTER>`, all **1024×1024**, varied — different angles, expressions,
  poses, framing (close-ups + mid + a couple full-body). Main features must stay consistent (Chris:
  caramel felt skin, black yarn **dreadlocks to mid-back**; Celeste: felt skin, black yarn hair
  **just past her shoulders**, stitched button eyes). Captioning is **trigger-word-only**, so variety
  in the *images* is what teaches identity.
- **How — Chris:** you already have ~47 rendered project stills. Pick the strongest on-model narrator
  frames; fill gaps in angle/pose by fanning one strong render out (the tutorial's Qwen multi-angle
  approach, or `draft --from <gen_id>` at higher denoise to restage).
- **How — Celeste (different — read this):** because she had **no canon lock** until now, her 47-image
  back-catalog has likely **drifted** (inconsistent identity). Do **not** scoop 20–30 mixed renders —
  that trains a blurry average. Instead **bootstrap from ONE**: pick your single best Celeste render
  (now that her canon is set), then fan *that one image* out to 20–30 via Nano Banana Pro / GPT Image
  side-by-side or the Qwen multi-angle workflow — all derived from the one seed, so they stay on-model.
  (This is the step we agreed to revisit together — we'll pick the seed before you fan it out.)
- **Land them in:** `~/agent-projects/celeste-you-dangerous/refs/<CHARACTER>/` (one folder per lead).
- **Report back:** per lead — how many frames, the angle/pose spread, and (Celeste) which seed render
  you fanned out. Dataset consistency is the #1 driver of LoRA quality.

### Step 6.2 — Train on Ostris AI-Toolkit (RunPod — PAID, cheap 4090)

Deploy and train per the tutorial. This is a UI flow, not a CLI command:

1. **Deploy** a RunPod pod with your storage volume, GPU **4090** (5090/H200 if you want speed),
   template = **Ostris** (search "Ostris AI-Toolkit"). Deploy On Demand; wait for the ready log.
2. **Open** the AI-Toolkit UI (Connect → the web port). Default password if prompted: `password`.
3. **Datasets → New Dataset** → name it `<CHARACTER>` → drag-drop that lead's Step-6.1 frames.
4. **Captions:** set **just the trigger word** `<TRIGGER>` on **every** image — no descriptive
   paragraphs. (The tutorial tested paragraph vs. keyword captions and found keyword-only works
   best for Z-Image specifically.) **Use a distinct trigger per lead** (`celestenarr8` vs
   `celestechar8`) so the two LoRAs never cross-fire.
5. **Job:** name the LoRA `<CHARACTER>`; **Trigger Words** = `<TRIGGER>`.
6. **Model:** search "Zimage" → select **"Z-Image Turbo with the training adapter"** (important —
   this is what makes fine-tuning the distilled Turbo model work; the raw Turbo weights are
   "generation only"). Untick low-VRAM on a 4090+.
7. **Training params** (tutorial's recipe): **steps 6000** (min 3000 — don't go lower; 6000
   over-trains for robustness), **learning rate `1e-5`** (or `2e-5`), resolution **1024**, caption
   dropout **0**, sample every 250 steps, **guidance scale 2**, **sample steps 16**, Cache Text
   Embeddings optional.
8. **Create Job → Play.** Watch the 250-step sample grid: `<CHARACTER>` should start resolving around
   **1250–1500 steps** and tighten from there.
9. **Download** the resulting `.safetensors` when the job completes. **Repeat steps 3–8 for the
   second lead** (new dataset, new trigger, new job) — you can queue it in the same pod session.
   **Delete the training pod** once both finish (your volume/LoRA downloads survive).
- **Options to alter (for the validation round):** dataset size (20 vs 30), steps (3000 vs 6000),
  LR (1e-5 vs 2e-5), and rank/dim if exposed — these are exactly the knobs we'll tune if the first
  LoRA is weak or over-baked.
- **Report back:** the final step count, LR, and a couple of the late-step sample images so we can
  judge identity lock before spending inference GPU.

### Step 6.3 — Place + register the LoRA (PAID sync against the inference pod)

```bash
# Put BOTH .safetensors where the INFERENCE ComfyUI pod can see them:
#   ComfyUI/models/loras/celeste-narrator.safetensors
#   ComfyUI/models/loras/celeste-waitress.safetensors   (names must match what you'll pin)
agent visual-generation model sync --endpoint <ENDPOINT>
agent visual-generation model list
```

- **Does:** copy the trained files into the inference pod's `models/loras/` (via the pod's volume /
  upload), then `model sync` reads `/object_info` and registers them; `model list` should now show
  `[lora       ] celeste-narrator.safetensors` **and** `[lora       ] celeste-waitress.safetensors`.
- **Optional — flag identity_bearing:** there's **no CLI flag yet** — edit
  `~/agent-data/visual-generation/models.json` and set `"identity_bearing": true` on that asset.
  **Optional for continuity** (the pin applies the LoRA regardless); it only routes outputs to the
  secured path and adds the `[identity-bearing]` markers.
- **Report back:** the `model list` line for the LoRA (and whether you flagged it).

### Step 6.4 — Pin each LoRA into its canon subject, trigger word and all (free)

One pin **per lead** — the `locked`/`forbid` differ, and each bakes **its own trigger** as the first
token of `--locked`:

```bash
# Chris (narrator) — trigger celestenarr8 prepended; keeps his forbid list.
agent visual-generation canon set celeste-you-dangerous \
  --alias "the narrator" --alias "narrator" --alias "@narrator" \
  --alias "Chris" --alias "the man" \
  --locked "celestenarr8, a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back" \
  --forbid "short hair" --forbid "shoulder-length" --forbid "buzz cut" \
  --lora celeste-narrator.safetensors:0.8

# Celeste (waitress) — trigger celestechar8 prepended; NO --forbid (forbid-bleed caveat, §0.2).
agent visual-generation canon set celeste-you-dangerous \
  --alias "Celeste" --alias "the waitress" \
  --locked "celestechar8, a felt-and-clay stop-motion puppet of a young woman, smooth matte felt skin, long black yarn hair falling just past her shoulders, bare felt face with no makeup, glossy black stitched sewing-button eyes" \
  --lora celeste-waitress.safetensors:0.8
```

- **Does:** re-upserts each subject **with** its character LoRA. **The trigger word is the first
  token of `--locked`** — the integration detail that makes it work: a LoRA only activates when its
  trigger is in the prompt, so baking the trigger into the locked descriptor means canon injects
  *both* the trigger (fires that lead's LoRA) *and* pins it — text and model identity travel together,
  per subject, so each lead fires only its own LoRA.
- **Expected:** each echo includes its `lora:` line; `canon show` lists **two subjects**, each with a
  trigger-prefixed `locked` and a `lora:` line.
- **Options to alter:**
  - `:STRENGTH` per lead — `0.8` start; lower (`:0.6`) if a LoRA over-powers the scene, higher if the
    identity is weak. (The main dial in the validation round — tune each lead independently.)
  - `NAME` must match the registry asset name exactly (from `model list`).
- **⚠ Two notes:** (1) `canon set` **replaces** the subject — re-pass *all* of its
  `--alias`/`--locked`/`--forbid` each time or you'll drop them (copy from `canon show` first).
  (2) Keep the **forbid-bleed** rule from §0.2 — that's why Celeste carries no `--forbid`.

### Step 6.5 — Draft and confirm the pins (free) — including the two-shot test

The single-lead case proves each pin fires; the **two-shot** (a scene with both Chris and Celeste —
scenes 2–4) is the real multi-subject test: both subjects must fire **independently**.

```bash
# Solo lead (Arrival is Chris only):
agent visual-generation draft --project celeste-you-dangerous --scene "Arrival" \
  --points "wide establishing shot" --points "dusk"

# Two-shot (both leads — the multi-subject test):
agent visual-generation draft --project celeste-you-dangerous \
  --scene "The Adversity and the Advesary" --points "Chris and Celeste at the bar, mid two-shot"
```

- **Expected — solo (Arrival):**
  - `Prompt:` begins with `celestenarr8`; `LoRAs:  celeste-narrator.safetensors@0.8`.
  - `── Canon enforced ──` lists `injected canon for 'the narrator'` **and** `pinned canon LoRA 'celeste-narrator.safetensors'@0.8`.
- **Expected — two-shot:** **both** subjects fire — the prompt carries **both** triggers
  (`celestenarr8` *and* `celestechar8`), `LoRAs:` lists **both** `.safetensors@0.8`, and
  `── Canon enforced ──` shows two `injected canon …` + two `pinned canon LoRA …` notes.
  - `Model: … [identity-bearing]` if you flagged either LoRA.
  - **⚠ Template slot count matters on two-shots.** A two-LoRA scene needs a template with **two**
    loader slots (`lora_0`, `lora_1`). The draft-time `N LoRA(s) won't apply …` advisory only fires
    when the template has **zero** loader slots — it does **not** currently catch the "1 slot, 2
    LoRAs" case, so the second LoRA could **silently drop** at generate. So: before generating a
    two-shot, confirm your chosen template actually exposes two loader slots (`workflow list`), and
    eyeball the generate output for both identities. (Flagged as a known gap — tell me if you hit it
    and we'll add an insufficient-slots warning.)
- **Try this to verify behavior:**
  1. A scene naming **neither** lead → **no** triggers, **no** LoRAs pinned (scoped to presence).
  2. Confirm the two-shot didn't **cross-fire** — Chris's text doesn't get Celeste's LoRA and vice
     versa; each subject pins only its own.
- **Report back:** the two-shot `Prompt:` head (both triggers?), `LoRAs:` line (both?), the two
  `pinned canon LoRA …` notes, and any ⚠ won't-apply line.

### Step 6.6 — Build a LoRA-pinned batch + generate (free build, PAID generate)

```bash
agent visual-generation batch build celeste-you-dangerous -o /tmp/celeste-lora.batch.md
agent visual-generation batch list /tmp/celeste-lora.batch.md
agent visual-generation generate /tmp/celeste-lora.batch.md --all --endpoint <ENDPOINT> --gpu-rate 2.09
```

- **Does:** each scene gets the trigger(s) + LoRA(s) for whichever lead(s) it names — Arrival just
  Chris; scenes 2–4 both — so each face holds across all four scenes. The durable counterpart to
  Workflow 5's img2img anchor.
- **Verify:** open `/tmp/celeste-lora.batch.md` — Arrival's spec carries `celestenarr8` + the
  narrator LoRA; the two-shot scenes carry **both** triggers + **both** LoRAs. After generate,
  eyeball cross-scene consistency for **each** lead — this is the payoff shot of the whole feature.
- **Report back:** per scene, which triggers+LoRAs landed, any ⚠ won't-apply (two-slot template?),
  and how consistent each lead looks scene-to-scene (vs. Workflow 5's img2img anchor, if you ran it).

---

## Workflow 7 — Single-image refinement (img2img / inpaint)

**Path for:** fixing or re-lighting one existing image rather than generating fresh. Exercises the
`--from`/`--image`/`--mask` refinement path on a single `draft`.

### Step 7.1 — img2img refine (free draft)

```bash
agent visual-generation draft "warmer key light, hold the composition" \
  --from <GEN_ID> --denoise 0.45 --project celeste-you-dangerous
```

- **Does:** the spec becomes a refinement — your text is the *change*, the prior generation's
  frame is the source (uploaded at `generate`), and lineage is recorded.
- **Expected — look for:**
  - `Refining: generation <GEN_ID>  [img2img]` and `Denoise: 0.45`.
  - Inherited recipe/model/dims from the parent.
- **Options to alter:**
  - `--image <path>` — refine an external image instead of a prior generation (mutually exclusive with `--from`).
  - `--mask <png>` — **inpaint**: white = area to change; the mode switches to `[inpaint]`. Requires a source.
  - `--denoise` — how far from the source (lower = closer; ~0.4–0.7 coherent).
- **Try this to verify behavior:** add `--mask` and confirm the echo flips to `[inpaint]  mask <path>`;
  omit the source with `--mask` set and confirm the clear `--mask requires a source` usage error.
- **Step 7.2 generate:** same as 2.2 (the source uploads automatically).
- **Report back:** the `Refining:` / `Denoise:` lines and the mode.

---

## Workflow 8 — Redraft (prose-only revise, continuity-safe)

**Path for:** "same image, reworded" — revise a generation's *prompt* while inheriting seed,
recipe, model, LoRAs, dimensions, and template so nothing drifts.

### Step 8.1 — Redraft (free)

```bash
agent visual-generation redraft <GEN_ID> "make the sky stormier, keep everything else"
```

- **Does:** produces a **text2img** spec (not an img2img edit of the pixels) that changes only the
  prose; records descent via `revised_from`.
- **Expected — look for:** `Revised from: <GEN_ID>`, `Template: … (recipe inherited from parent)`,
  the **same `Seed:`** as the parent, and `── Canon enforced ──` re-applied (continuity can't drift from canon).
- **Options to alter:** `--model` / `--provider` (craft controls), `-o` (batch file), `--project`.
- **Try this to verify behavior:** redraft and confirm the `Seed:` matches the parent's exactly —
  that's the continuity guarantee. Then `chain show <ROOT_GEN_ID>` (Workflow 9) to see the lineage.
- **Report back:** the `Revised from:` + `Seed:` lines.

---

## Workflow 9 — Memory & retention loop (proves nothing's lost between sessions)

**Path for:** confirming `report` actually builds durable memory you can recall — the answer to
"I'll lose my Claude-chat context."

```bash
agent visual-generation review-pending                       # renders awaiting a reaction
agent visual-generation report <GEN_ID> --reaction loved --rating 5 --context "hero shot for Arrival"
agent visual-generation digest celeste-you-dangerous         # recent gens + reactions + lessons
agent visual-generation recall "narrator rooftop dusk"       # semantic recall across memory
agent visual-generation chain show <ROOT_GEN_ID>             # lineage tree (draft→redraft→refine)
```

- **Does, in order:** list un-reacted renders → record a reaction → see the bounded session
  primer → semantically recall prior work → inspect a generation's lineage.
- **Expected:** `digest` lists the just-reported generation under "Recent generations"; `recall`
  returns it; `chain show` renders the tree rooted at the original.
- **Options to alter:** `digest --limit 15`, `recall --limit 10`.
- **Try this to verify behavior:** report a generation, then **start a fresh terminal** and run
  `digest` — it should still show it (proves cross-session persistence, the whole point).
- **Report back:** `digest` before vs. after a `report`, and whether `recall` finds the new one.

---

## Appendix A — Command quick reference

| Command | Free? | Purpose | Key options |
|---|---|---|---|
| `knowledge-verify "<q>" --project P` | ✅ | prove knowledge surfaces + gap flags | `--limit` |
| `draft "<intent>" --project P` | ✅ | craft one spec (text2img or `--from`/`--image` refine) | `--points` `--scene` `--template` `--model` `--provider` `--from` `--image` `--mask` `--denoise` `-o` |
| `batch build P` | ✅ | one spec per `directed.md` scene | `--from` `--image` `--denoise` `--template` `--model` `-o` |
| `batch rebuild P` | ✅ | overwrite an existing batch | (same as build) |
| `batch list <file>` / `batch rm <file> <id>` | ✅ | inspect / prune specs | `--yes` (rm) |
| `redraft <gen> "<change>"` | ✅ | prose-only revise (inherits recipe/seed) | `--model` `--provider` `-o` |
| `canon set P --alias … --locked … [--forbid …] [--lora N[:S]]` | ✅ | lock identity (text + character LoRA) | replaces the subject — re-pass all fields |
| `canon show/rm P` | ✅ | view / remove canon | — |
| `generate <file> --endpoint <url>` | 💸 | render on the pod | `--section` `--all` `--gpu-rate` `--max-session-cost` `--yes` |
| `report <gen> --reaction X` | ✅ | record reaction → memory | `--rating` `--notes` `--context` |
| `digest P` / `recall "<q>"` / `review-pending` / `chain show <id>` | ✅ | memory + lineage reads | `--limit` |
| `model sync --endpoint <url>` / `model list` | (sync hits pod) | registry from `/object_info` | `--yes` |
| `workflow list "<q>"` / `workflow register <graph>` | ✅ | template registry | `--limit`, `--name`, `--descriptor`, `--yes` |

Reactions: `loved` · `liked` · `liked_with_changes` · `disliked` · `render_failed` (rating 1–5 meaningful for the first three).

## Appendix B — Marked blocks = the signal to paste back

When you report back, these `── … ──` blocks are what tell us the implementation works:

- **`── Knowledge surfaced (deterministic) ──`** — retrieval reached the LLM (per-leg, with scores). Empty = a surfacing hole.
- **`── Compiled from (your project docs) ──`** — your `directed.md`/etc. fed the prompt. Absent on a `--project` draft = doc discovery missed.
- **`── Canon enforced (deterministic) ──`** — locked text injected / forbidden phrasing stripped / **`pinned canon LoRA …`** (feature C).
- **`✓ No gaps flagged`** vs **`⚠ Gaps (…)`** — the knowledge-verify verdict.
- **`⚠ … LoRA(s) won't apply …`** — an honest surfaced silent-drop; means the template lacks a loader slot.
- **`[identity-bearing → secured path]`** at generate — an identity model/LoRA routed to the secured path.

---

*Report results per workflow and we'll confirm each behaves as expected, then adjust anything that
doesn't before the next round.*
