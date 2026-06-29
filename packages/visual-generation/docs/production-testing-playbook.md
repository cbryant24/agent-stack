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
  - Canon set for the narrator (puppet descriptor + `forbid` list); **no character LoRA yet** (Workflow 6 adds one).
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

### 0.2 — Confirm project docs + canon are present (free, instant)

```bash
agent visual-generation canon show celeste-you-dangerous
ls ~/agent-projects/celeste-you-dangerous/
```
- **Does:** confirms the doc-compilation source and the deterministic canon both exist.
- **Expected:** `canon show` prints the narrator subject — `aliases`, `locked` (the puppet
  descriptor), `forbid`. **No `lora:` line yet** (that arrives in Workflow 6).
- **Report back:** the `canon show` output.

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

**Path for:** the strongest continuity — a trained character LoRA pinned into **every** scene the
narrator appears in, via canon. Identity travels at the model level, not just the text.

> **Prerequisites (one-time, GPU/curation — do these before the CLI steps):**
> 1. **Curate** ~15–30 stills of the approved narrator puppet (varied pose/angle/light, consistent
>    identity) into `~/agent-projects/celeste-you-dangerous/refs/narrator-lora/`. Your best
>    `report`ed generations + anchor renders are good sources.
> 2. **Train** a Z-Image Turbo LoRA per the ingested tutorial (the one Workflow 1 surfaced) on the
>    pod → a `.safetensors` placed in the pod's `models/loras/`.
> 3. **Register** it: `agent visual-generation model sync --endpoint <ENDPOINT>` then
>    `model list` to confirm the LoRA appears.
>    - To flag it `identity_bearing` (routes outputs to the secured path) there is **no CLI flag
>      yet** — edit `~/agent-data/visual-generation/models.json` and set `"identity_bearing": true`
>      on that asset. **This is optional for continuity:** the pin applies the LoRA regardless;
>      the flag only governs secured-path routing.

### Step 6.1 — Pin the LoRA into canon (free)

```bash
agent visual-generation canon set celeste-you-dangerous \
  --alias "the narrator" --alias "narrator" --alias "@narrator" \
  --locked "a felt-and-clay stop-motion puppet of a young Black man, deep caramel-brown felt skin, long black yarn dreadlocks falling to mid-back" \
  --forbid "short hair" --forbid "shoulder-length" --forbid "buzz cut" \
  --lora celeste-narrator.safetensors:0.8
```
- **Does:** re-upserts the narrator subject (keyed by first alias) **with** a character LoRA.
  Re-passing the aliases/locked/forbid keeps them; `--lora NAME[:STRENGTH]` adds the model-level identity.
- **Expected:** the echo now includes a `lora: celeste-narrator.safetensors@0.8` line.
- **Verify it stuck:** `agent visual-generation canon show celeste-you-dangerous` → the subject
  shows the `lora:` line.
- **Options to alter:**
  - `:STRENGTH` — omit it for `1.0`; lower (`:0.6`) for a lighter identity influence.
  - The `NAME` must match a registry asset name exactly (from `model list`).
- **⚠ Note:** `--lora` on `canon set` **replaces** the subject — always re-pass `--alias`/`--locked`/`--forbid`
  or you'll drop them. (Copy the values from `canon show` first.)

### Step 6.2 — Draft and confirm the pin (free)

```bash
agent visual-generation draft --project celeste-you-dangerous --scene "Arrival" \
  --points "wide establishing shot" --points "dusk"
```
- **Expected — look for:**
  - `LoRAs:    celeste-narrator.safetensors@0.8` on the spec.
  - `── Canon enforced ──` now also lists **`pinned canon LoRA 'celeste-narrator.safetensors'@0.8`**.
  - `Model: … [identity-bearing]` **if** you flagged the LoRA identity_bearing in the registry.
  - **⚠ if you see** `N LoRA(s) won't apply: this template has no LoRA loader slots` — the
    resolved template can't load a LoRA. Force a LoRA-capable template with `--template <name>`
    (check `workflow list`), or register one. This advisory is the feature working — it's
    surfacing a silent drop, not hiding it.
- **Try this to verify behavior:**
  1. Draft a scene that **doesn't** name the narrator → the LoRA should **not** be pinned (the
     pin is scoped to subject presence, same as the text). Confirms it's not blindly appended.
  2. Temporarily hand-pick the same LoRA in a prompt and confirm the pin **dedupes** (one entry,
     your strength kept) rather than doubling.
- **Report back:** the `LoRAs:` line + the `pinned canon LoRA …` note (and any ⚠ won't-apply line).

### Step 6.3 — Build a LoRA-pinned batch + generate (free build, PAID generate)

```bash
agent visual-generation batch build celeste-you-dangerous -o /tmp/celeste-lora.batch.md
agent visual-generation batch list /tmp/celeste-lora.batch.md
agent visual-generation generate /tmp/celeste-lora.batch.md --all --endpoint <ENDPOINT> --gpu-rate 2.09
```
- **Does:** every scene naming the narrator gets the LoRA pinned, so the face holds across all
  four scenes — the durable counterpart to Workflow 5's img2img anchor.
- **Verify:** open `/tmp/celeste-lora.batch.md` and confirm the LoRA is in each narrator scene's
  `lora_stack`. After generate, eyeball that the narrator is consistent scene-to-scene.
- **Report back:** whether the LoRA appears in each scene's spec, and a note on cross-scene consistency.

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
