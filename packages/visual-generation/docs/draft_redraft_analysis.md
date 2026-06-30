# Draft and Redraft Analysis — and the Hair-Length Fix

A code-grounded breakdown of how `visual-generation`'s `draft`, `redraft`, and
`generate` turn your text into an image — written to answer a specific recurring
failure: the narrator's **hair keeps rendering too short** on the new
`celeste-you-dangerous` bar-exterior rear shot.

Every claim below is traceable to source. Key files:

- `src/visual_generation/cli.py` — the Click commands and the terminal output (incl. the `── Your own technique lessons (relevant) ──` block).
- `src/visual_generation/draft.py` — `draft()` / `redraft()` orchestration.
- `src/visual_generation/chains.py` — the Claude authoring call.
- `src/visual_generation/retrieval.py` — context retrieval (Qdrant only).
- `src/visual_generation/generate.py` + `graph_build.py` — render-time slot substitution.
- `docs/z-image-turbo-craft.md` — the human craft doc (the LOCKED narrator descriptor, ~line 237).

---

## 1. TL;DR — why the hair is wrong

Two causes are stacking, and **neither is a bug in a doc**:

1. **You never actually ran the canonical phrase.** The proven, locked descriptor is
   `long black yarn dreadlocks falling to the middle of his back`. Across *every CLI run*
   in the log, the wording sent was **shorter** — "just past his shoulders", "a little
   past his shoulders", "just below his shoulders", "reach his shoulder blades". The
   draft prompt is **near pass-through** (§3), so the generator rendered roughly the
   short length you asked for. The chat *recognized* the canonical phrase but the
   commands kept shipping shorter wording.

2. **The shot itself is a rendering wall.** A **rear view of black dreads over a black
   sweater at night** is near-zero luminance contrast. Even with perfect wording,
   Z-Image Turbo at 8 steps has no edge to grow hair against the dark sweater/background,
   so it collapses to a short cap. Clauses like *"short neck / head sits low on his
   shoulders"* make it worse by packing the head–shoulder zone. This is why the other
   (non-rear, higher-contrast) beats rendered long hair fine.

**On your specific question — "is a pipeline doc preventing this, or is it that this
scene isn't in the project docs?":** No. **The CLI reads zero markdown docs.** Neither
`z-image-turbo-craft.md` nor `visual-batch.md` is ever loaded by `draft`/`redraft`/
`generate` — they are *human* references. The scene being absent from `visual-batch.md`
has **no direct mechanical effect**. It has one *indirect* effect (§6/§9): a brand-new
scene isn't similar to your existing good-hair generations in Qdrant, so those proven
prompts don't get auto-retrieved — meaning you must supply the canonical wording
literally yourself.

The fix is in §10.

---

## 2. The pipeline at a glance

```
  your text ──► draft ──► (batch .md file) ──► generate ──► image ──► report
              (Claude,                         (GPU,                  (feedback
               FREE)                            PAID)                  into Qdrant)
```

- **`draft` / `redraft`** call **Claude** to author a *spec* (prompt + settings + model +
  seed + rationale) and append it to a `*.batch.md` file. **No GPU. Free** (a few cents of
  Claude tokens). Infinitely iterable.
- **`generate`** reads one spec from the batch file and renders it on your ComfyUI pod.
  **This is the only step that spends GPU.**
- **`report`** records your reaction; that feedback re-enters Qdrant and can influence
  later drafts.

---

## 3. How your text becomes the output prompt

### Two different models — don't confuse them

| Role | What it is | Where set |
|---|---|---|
| **Authoring model** | The **Claude** model that *writes* the image prompt | `--model opus` → `claude-opus-4-8`; default Sonnet. Used at `chains.py:244`. |
| **Image model** | The **diffusion** checkpoint that renders pixels | `z_image_turbo_bf16.safetensors`, chosen by Claude into the spec, applied at `generate`. |

So `--model opus` only buys you **better prompt-writing**. It does **not** change the
diffusion render. The line in your output —
`Model: z_image_turbo_bf16.safetensors` — is the *image* model, not the Claude model.

### The output prompt is near pass-through

The chat's instinct was right. `draft` does rewrite your intent into structured prose,
but it stays very close to your literal words. `redraft` is even tighter — its system
suffix `_REVISE_MODE_SYSTEM` (`chains.py:82-91`) orders Claude to copy unchanged language
**verbatim**:

> REVISE MODE — … Preserve every locked descriptor block and all unchanged
> composition/style/lighting language **VERBATIM — copy it through word-for-word; do not
> paraphrase, reorder, or "improve" it.**

**Consequence:** whatever hair phrasing you type is essentially what reaches the
generator. This is the single most important lever you have. It also means
**meta-instructions to Claude leak into the image** — e.g. writing *"do not use the words
falling/below"* risks those words landing in the rendered prompt as content. Write only
the literal scene; never instructions-about-the-scene.

The base instruction set is `_SYSTEM_PROMPT` (`chains.py:30-71`): it tells Claude it is a
"diffusion prompt-crafter and platform tutor", to honor the template's slots, to pick
models by name from the registry, and to emit **strict JSON** (`prompt`,
`negative_prompt`, `settings`, `model`, `seed_strategy`, `seed`, `width`, `height`,
`lora_stack`, `rationale`). The JSON is parsed in `_parse_spec_response`
(`chains.py:310-358`); the `prompt` field becomes the `Prompt:` you see and the body of
the batch file.

---

## 4. What each option does

From your command
`--template visual-workflow --model opus --project celeste-you-dangerous -o …bar-exterior-draft.batch.md`:

| Option | Effect on prompt / settings / rationale |
|---|---|
| `--template visual-workflow` | Resolves that **named** registered template (`draft.py` `_resolve_template`). The template's **slot map** defines which settings keys Claude may set and where the prompt/seed/dims are written at render. With no `--template`, the top *retrieved* template is used — which can wrongly pick an inpaint graph for text2img prose (known issue KI-8). Pinning the name avoids that. **No effect on hair wording.** |
| `--model opus` | The **Claude authoring** model (§3). Better prose adherence/cleanup. **Does not touch the diffusion render.** |
| `--project celeste-you-dangerous` | Tags the spec and sets the asset output directory (`assets/celeste-you-dangerous/…`). Also the default batch filename stem. **No effect on the prompt.** |
| `-o <path>` | The batch `.md` file appended to (`append_spec`). Pure plumbing. |
| `--from <gen_id>` / `--image <path>` | Switches `draft` into **img2img/inpaint EDIT** mode (`_EDIT_MODE_SYSTEM`): preserves the source, changes only what you ask, recipe fixed by template. |
| `--mask <png>` | Inpaint mask (white = change). Requires `--from`/`--image`. |
| `--denoise <f>` | Refinement strength (default 0.5; ~0.4–0.7 coherent). Persisted onto the spec, overriding crafted settings. |

---

## 5. Where the Settings and Rationale come from

- **Settings** (`{cfg, steps, sampler, scheduler, denoise}`) are authored by **Claude in
  its JSON**, then filtered so only keys the template has slots for survive
  (`_parse_spec_response`). For your Z-Image template they consistently land on the locked
  recipe (cfg 1.0, 8 steps, res_multistep, simple) because that's the confirmed lesson
  Claude is fed (§6) — not a hardcoded default.
- **Rationale** is just a Claude-authored field in the same JSON. It is **explanation,
  not configuration** — it can occasionally cite a number that doesn't match the applied
  settings (tracked as known issue KI-3). Don't treat the rationale as authoritative for
  what actually rendered; the `Settings:` line and the batch file are authoritative.

---

## 6. "Your own technique lessons (relevant)" — sourced and **used**

**Question:** *if they're displayed, does that mean they're being used?*
**Answer: Yes — displayed == used.** They are the same objects, from one retrieval:

- `draft.py:114` runs **one** `retrieve_context(intent, …)` producing `ctx`.
- That **same `ctx`** is passed to `craft_spec(intent, ctx, …)` at `draft.py:125` → into
  the Claude user message, formatted by `build_context_prompt` as
  `[TECHNIQUE LESSON: valence/scope, score=…]` blocks (`retrieval.py:232-237`).
- That **same `ctx`** is also what's printed:
  `tutor_notes = [le.statement for _, le in ctx.technique_lessons]` (`draft.py:157`).

So the four bullets you see on screen are exactly the four lessons Claude saw. The base
prompt explicitly tells Claude to honor them:

> `[TECHNIQUE LESSON: positive/...]` entries are confirmed preferences — honor them.

**Important nuances:**

- They inform Claude's **reasoning/settings**, they are **not** copied verbatim into the
  prose prompt. (They shape *how* it crafts, not literal output text.)
- **The four lessons you keep seeing are all recipe/inpaint mechanics** (1152×896 stall,
  the Z-Image recipe, glass-only screen masking). **None of them govern hair or the
  character.** So although the system is working, it has *nothing stored* to steer hair —
  which is why it never self-corrected the length.

### Where lessons come from, and how they're stored

- Stored in Qdrant collection **`visual_generation_memory`**, `memory_type=technique_lesson`,
  `confirmed=true`; retrieved by **Voyage** vector similarity to your intent
  (`store.search_lessons`, top-5), and only **confirmed** lessons surface.
- They are created **only** by `visual-generation lesson add …`. They are **not**
  auto-derived from `report` reactions. (`report --rating/--context/--notes` are stored on
  the *generation record*, not converted into lessons.)

### The numbered "Technique 1 / Technique 14" are NOT these lessons

The chat cited "Technique 1: literal beats relational", "Technique 14", etc. Those live
**only** in `docs/z-image-turbo-craft.md` as prose. **No code path reads that markdown**
— `retrieval.py` queries Qdrant collections exclusively. Those numbered techniques only
reached your earlier Claude chats because the doc was *pasted into the chat*. The `draft`
command has never seen them. (Same for the LOCKED narrator descriptor at craft-doc
line 237.)

---

## 7. The generate stage — verbatim, no re-thinking

`generate` does **not** re-author anything. It:

1. Reads the spec from the batch file by `--section <spec_id>`.
2. Resolves the spec's workflow template and **substitutes each spec value into the
   ComfyUI graph** via `write_slot(graph, slot_map, slot, value)` (`graph_build.py`) —
   prompt, negative, seed, width/height, settings, model, LoRAs each written to the exact
   node the slot map names. Values with no slot are collected as advisory `unmapped`,
   never forced.
3. Resolves the seed: `seed_strategy == "random"` → fresh int at render time; otherwise
   the stored int (`generate.py` `_resolve_seed`).
4. Submits the graph to your `--endpoint` ComfyUI pod, downloads the asset, prints the
   GPU cost gate (soft-inform, never blocks).

**There is no Claude call in `generate`.** The `Prompt:`/`Settings:` you saw at draft
time are exactly what render. Nothing between draft and pixels edits your wording.

---

## 8. redraft vs draft

| | `draft` | `redraft <gen_id> "<change>"` |
|---|---|---|
| Starts from | your intent | the **parent's full prompt** |
| Rewriting | structured, near-literal | **verbatim** preserve + targeted change only |
| Seed | Claude chooses (often random) | **re-pins the parent's seed as FIXED** (`_enforce_revise`, `chains.py:291-307`) |
| Recipe/model/dims/LoRAs | authored | **inherited from parent**, locked |
| Reads `report --notes` / `--context`? | **no** (`--notes` not read by draft) | **yes** — folded into the change context (`chains.py:148-152`) |
| Render type | text2img | text2img (fresh render, `source=None`), not a pixel edit |

**Why this bit you:** redraft **re-pins the short-hair seed**. With a near-identical
prompt and the same seed, Z-Image at 8 steps reproduces almost the same composition — so
a small hair-word change barely moves the image, *especially* against the contrast wall.
A redraft was the wrong tool for "make the hair substantially longer here".

---

## 9. Why the hair specifically failed (the full diagnosis)

1. **Pass-through + shorter wording.** Every run requested shoulder-ish length; the model
   delivered shoulder-ish length. The canonical `to the middle of his back` was never
   actually shipped (§1).
2. **Black-on-black rear-view contrast wall.** No luminance edge for hair to grow against;
   the model defaults to a short cap. Inpaint also stalled here — there's no hair edge to
   continue and nothing to separate dreads from sweater (your own chat logged this).
3. **Competing anatomy clauses.** "short neck / head low on shoulders" compress the zone
   where long hair would fall.
4. **redraft fixed-seed inertia** (§8) locked the short-hair composition in place.
5. **No stored hair lesson + dissimilar new scene.** The only Qdrant lessons are recipe
   mechanics, and a brand-new bar-exterior scene isn't similar enough to your good-hair
   beats for those prompts to be retrieved as `[PRIOR GENERATION]` — so nothing in the
   pipeline pulled the canonical wording in for you.

---

## 10. Best strategy + the fix (canonical mid-back)

Ordered cheapest → most reliable.

### Step 1 — Use the canonical descriptor verbatim (the phrase never actually run)

```
long black yarn dreadlocks falling to the middle of his back
```

Use the material noun **"yarn dreadlocks"** and the **literal endpoint "to the middle of
his back."** Drop or minimize the length-suppressing clauses ("short neck", "head sits
low on his shoulders"). Write only the literal scene — no instructions-to-Claude in the
intent (they pass through into the image).

### Step 2 — Break the black-on-black contrast (the real blocker for this rear shot)

Pick at least one:

- **Light the hair:** `…long black yarn dreadlocks falling to the middle of his back, the
  dreadlocks catching the warm orange glow from the doorway` — gives the model an edge.
- **3/4 rear angle** instead of dead-behind, so some dreads fall forward over a shoulder
  into a lighter area.
- **Lighter sweater value**, if wardrobe allows, so the dark dreads read against it.

### Step 3 — Prefer a FRESH `draft` (new seed) over `redraft` here

redraft re-pins the short-hair seed and resists the change (§8). Run a fresh draft so the
composition is free to place long hair. Example, assembling Steps 1–2 onto your proven
storefront base (the `de5b3c7e` / `c8f5c109` wording that landed everything but the hair):

```bash
op run --env-file=.env -- uv run visual-generation draft "storybook stop-motion short-film production still, Coraline-inspired handmade felt and clay puppet aesthetic, visible woven fabric texture and stitched seams, night exterior of a small city sports bar. Seen from behind at a slight three-quarter angle: a young African American man as a handmade felt puppet, stocky build, warm caramel-brown felt skin, long black yarn dreadlocks falling to the middle of his back, the dreadlocks catching the warm orange glow from the doorway. He stands on the sidewalk facing the open central doorway and looking inside. He wears a long black sweater with distressed edges at the bottom, loose black jeans, red-and-white Air Jordan 1 high-top sneakers. The storefront has the open central doorway with a large window on each side; the interior glows dim and moody in warm orange with soft light-purple accents. A large flat-screen television is mounted low and centered over each window, one on each side of the doorway: the left shows the Los Angeles Lakers logo in purple and gold; the right shows a New York Knicks basketball game in blue and orange. Dark night exterior, lit mainly by the two glowing screens and the warm light from the doorway. Film grain, cinematic frame composition, rich saturated color, short-film production still." --template visual-workflow --model opus --project celeste-you-dangerous -o ~/agent-data/visual-generation/batches/bar-exterior-draft.batch.md
```

Then `generate` that spec and `report` it.

### Step 4 — If still short, masked hair inpaint with room to grow

`draft --from <gen_id> --mask <hair.png> "long black yarn dreadlocks falling to the
middle of his back" --denoise 0.8`, where the **mask extends down the back** past where
the hair currently ends — give the model empty canvas to fill, not just the existing-hair
pixels. Combine with the Step 2 contrast aid; pure black-on-black can still resist.

### Step 5 — Make it stick for next time (optional but recommended)

Store the canonical descriptor so it auto-surfaces on future related drafts:

```bash
op run --env-file=.env -- uv run visual-generation lesson add "Narrator hair canonical: long black yarn dreadlocks falling to the middle of his back. State as a literal body-landmark endpoint ('to the middle of his back'), use the material noun 'yarn dreadlocks', and never relational drape words (falling just below/past the shoulders, shoulder blades)." --scope prompt --valence positive
```

This stores it in Qdrant (`visual_generation_memory`) so it's retrieved and shown to
Claude on related drafts (§6). Because lessons inform reasoning rather than appearing
verbatim, still **type the literal phrase into the intent** too.

### Strategy summary — how to describe anything for this pipeline

- **Literal beats relational.** Fixed body-landmark endpoints ("to the middle of his
  back"), not drape/motion words ("falling below", "reaches").
- **Reuse proven wording verbatim**, especially on a new scene — the pipeline won't fetch
  it for you when nothing similar exists yet.
- **Positive, single, clean mentions** beat heavy negatives and repetition (this is what
  finally landed the sleeves — see the log).
- **No meta-instructions in the intent** — they leak into the image.
- **Give failing details edge/contrast or canvas**, or move them to a masked inpaint;
  some misses are rendering walls, not wording problems.

---

## Appendix A — Original problem statement

> I need a visual indepth analysis on the visual-generation draft and redraft … each time
> the character's hair length is completely wrong. … I want to know the best strategy for
> what description to use with the input. … How is `Your own technique lessons (relevant)`
> sourced and if they are displayed does that mean those techniques are being used. … How
> is this all used in the generate stage. … One thing to note is I am generating a new
> image for the project that was not in the `visual-batch.md`; the narrator's hair length
> was never a problem in any of the other images.

(See §6 and §9 — the "not in visual-batch.md" detail has no direct mechanical effect, only
the indirect retrieval effect described in §9.5.)

## Appendix B — Chat excerpts and run logs

### Chat: diagnosis recognized but length still wrong

> Both inpaint passes stalled — confirming black dreads on a black sweater in a dim rear
> shot is a near-zero-contrast wall the masked path can't cross, on top of inpaint not
> inventing length where there's no hair edge to continue. … The LOCKED narrator
> descriptor in the craft doc is: *a young African American man with deep caramel-brown
> felt skin, long black yarn dreadlocks falling to the middle of his back* … I've been
> asking for hair shorter than the canonical character this whole time — "just below the
> shoulders," "shoulder blades" … The length that actually renders is "to the middle of
> his back," with the material noun "yarn dreadlocks." … New approach: minimal and
> canonical. Use the locked block verbatim … Fresh draft, new seed, template pinned, Opus.

### Chat: confirming draft is near pass-through

> Look at the output vs input above: the authored prompt mirrors your string almost
> word-for-word. Draft passes through near-verbatim, so the literal wording is what hits
> the generator … And it's why my redraft meta-instruction last turn ("do not use the
> words falling/below") was a mistake: that's an instruction to me, and it risks landing
> in the image prompt as content. … "Head sits low on his shoulders / short neck" packs
> the head-shoulder zone tight, which can leave no room for hair to run down the back.

### Run log (verbatim)

The four runs below show the pass-through behavior and the recurring shorter-than-canonical
wording. Spec/generation ids: `427df1a9` → gen `2d33b36f`; `47b62955` → gen `63fc0213`;
`c8f5c109` → gen `de5b3c7e` (best base, hair the lone miss); redraft `9037317a` (fixed
seed `2572462955`, "reach his shoulder blades").

```bash
# Run 1 — "black yarn dreadlocks falling just past his shoulders"
op run --env-file=.env -- uv run visual-generation draft "…short neck so his rounded felt head sits low and close to his shoulders … black yarn dreadlocks falling just past his shoulders …" --template visual-workflow --model opus --project celeste-you-dangerous -o ~/agent-data/visual-generation/batches/bar-exterior-draft.batch.md
# → Spec 427df1a9 → gen 2d33b36f ★4: proportions/TVs/relight landed; sleeves short; hair short.

# Run 2 — "black yarn dreadlocks falling a little past his shoulders" (+ heavy sleeve negatives)
# → Spec 47b62955 → gen 63fc0213 ★4: sleeves short again (4th miss); hair "good"/short.

# Run 3 — simplified positive prose, "dreadlocks falling to just below his shoulders"
# → Spec c8f5c109 → gen de5b3c7e ★4: BEST base. Long sleeves finally landed; TVs centered low; hair too short.

# Redraft — "long black yarn dreadlocks that reach his shoulder blades" (fixed seed 2572462955)
op run --env-file=.env -- uv run visual-generation redraft de5b3c7e-8a5d-4b1c-af6c-07b76508ef20 "Keep everything exactly as-is … Change only the hair length: long black yarn dreadlocks that reach his shoulder blades. State the length as a literal endpoint …" --model opus --project celeste-you-dangerous -o ~/agent-data/visual-generation/batches/bar-exterior-redraft.batch.md
# → Spec 9037317a, recipe inherited, seed re-pinned fixed. Still shorter than canonical "middle of his back".
```

The recurring `── Your own technique lessons (relevant) ──` block in every run listed the
same four **recipe/inpaint** lessons (1152×896 stall; Z-Image recipe; glass-only screen
mask ×2) — **none about hair** — confirming §6: the system surfaced and used exactly those
four, and had nothing stored to steer hair length.
