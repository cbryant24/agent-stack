# celeste-you-dangerous — failure conclusions and causes (summary of record)

**Author:** Claude (Opus 5). **Date:** 2026-09-22.
**Status:** definitive post-mortem for the Z-Image-Turbo + character-LoRA + text-canon attempt.
It **supersedes the earlier write-ups as the summary of record**, which are kept as evidence
(§8 lists where they are wrong). The path forward is in the
[Consolidated audit](Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md), and this
doc doesn't repeat it.

**Scope:** why the pipeline (a) produced bad prompts, (b) failed to keep Celeste and the narrator
consistent with LoRAs, (c) failed to keep the sets consistent, and (d) either ignored requested
values or used values it should not have. It is based on re-reading every batch version, canon
version, LoRA dataset and workflow, the current code, and the ComfyUI graph embedded in all 375
`identity/celeste-you-dangerous/*.png` renders. The graph is the ground truth for what actually
ran. Reproduction is in §11.

---

## 1. Bottom line

1. **The core failure is architectural.** Identity came from a text paragraph plus LoRAs applied
   to the whole image. Set continuity came from text alone. The base model was a distilled Turbo
   model with no classifier-free guidance. There was no reference image, mask-region, pose or depth
   conditioning anywhere. That stack can't hold "the same puppet in the same room in every shot",
   whatever the prompt says. (This agrees with the earlier analyses. It is still the headline.)
2. **A silent seed bug invalidated most of the experiments.** A spec marked "random" never had
   its seed written into the ComfyUI graph. Every "random" render ran on the workflow template's
   baked seed, but the database recorded a freshly rolled number that was never used. **340 of 375
   identity renders (91%) ran on one of two fixed seeds.** Every Phase-E frame in the evidence doc
   ran on the same seed, `1065558432276088`, including all the "seed sweeps". Any conclusion drawn
   from "varying the seed" in this project is unfounded.
3. **The same bug shaped the LoRA training data.** All 13 frames of `lora/celeste/` that still carry
   metadata share seed `1065558432276088`. All 21 frames of `celeste-coraline` and
   `narrator-coraline` share `719249596297021`. The datasets were not only synthetic and generated
   by the target model itself, they were also generated from **one starting noise**.
4. **The LoRAs were trained on the wrong character.** Every LoRA before v2 bakes in traits that the
   final canon forbids: straight black hair, large glossy buttons, blush, and a goatee on the
   narrator. The design changed four times (felt → sleek-straight clay → v2 curly bun → "LAIKA
   painted resin"). The LoRAs trailed each change, and canon was re-locked before any render was
   approved.
5. **The trigger tokens were almost never used.** Face, hair and eyes were deliberately left out of
   the captions so the trigger token would carry them. Yet only **9 of 83** renders that loaded a
   Celeste LoRA contained `clstwtrss`, and **4 of 85** narrator renders contained `chrsnrtr`.
6. **Prompt assembly damaged its own instructions.** Canon text was appended, and forbidden
   substrings were then stripped from the whole prompt. That strip mangled the canon it was meant
   to protect (`clean-shaven with no,` in 71 renders, `NOT, NOT blue-toned` in 22). Duplicates
   accumulated across redrafts. Prompts grew to **9,027 characters**, with a median of about 4,000
   in the later batches, and there was no length limit.
7. **Negations lived in the positive prompt.** At cfg 1 the negative is zeroed out, so "NOT gray",
   "no blush" and "they must not look alike" could only act as positive mentions of gray, blush and
   likeness.
8. **The drafter was never told which model it was writing for.** Its system prompt targets
   "Flux, SDXL, WAN", and its example spec uses `euler`. The agent called Z-Image "Flux-adjacent",
   gave SDXL advice (CFG 7, DPM++, 30 steps), and switched the final batch to `euler` without
   recording a reason.
9. **What the agent said it ran often differed from what it ran.** Rationales name strengths or
   LoRA files that differ from the recorded `lora_stack` in every batch version. Values with no
   slot in the template are silently dropped, and the list of dropped values is computed but never
   printed.
10. **The sets were never actually fixed.** Set canon changed in every version: TV placement moved
    four times, and the Lakers/Knicks sides are reversed between the batches and the canon. Even
    identical set text produced a different room each render.
11. **Nothing checked the images.** There was no identity, continuity or "did the graph match the
    spec" check. The GPU ledger shows $3.74 against more than $100 actually spent.

**Implication:** cleaning up the prompts would have improved the solo frames slightly and nothing
else. Fixing the silent bugs (§9) is required before *any* future run on *any* model. Otherwise the
next bake-off will be measured with the same broken instruments.

---

## 2. What was attempted — timeline

**Goal:** LAIKA/Coraline-style stills for a short film. Two recurring puppets must look the same in
every shot: Celeste the waitress, and the narrator (Chris). Recurring sets must keep the same
layout: the bar storefront, the bar interior and the couch.

**Stack:**
- `z_image_turbo_bf16` with the `qwen_3_4b` text encoder.
- 8 steps, cfg 1.0, `res_multistep`/`simple`, `ModelSamplingAuraFlow shift 3`, 1024².
- Negative conditioning zeroed out (`ConditioningZeroOut`).
- An LLM drafter (`draft`) writes each spec.
- A "canon" layer appends locked text and strips forbidden substrings.

The batch file names are **not** in chronological order. The `created_at` headers are
authoritative: v3g (Jul 6 03:42Z) came **before** v3f (Jul 6 07:40Z), and v3f carries v3g's
seeds forward.

| Batch (file) | Date | Look | Character LoRAs @ strength | Canon change | Prompt median / max (chars) | Headline failure |
|---|---|---|---|---|---|---|
| v1 `visual-batch-v1-pre-lora.md` | Jun 14–26 | storybook felt + clay | none | none (prose only) | 958 / 2,041 | button-eye dropout on faces; seed 4471 reused "for continuity" |
| side batches `batches/*.batch.md` | Jun 20–Jul 2 | felt | none, then `*-zimage` @2.0 | — | ~1,500 / 3,977 | narrator hair collapses to a short cap; long sleeves "after four misses" |
| v2 `visual-batch-v2-felt.md` | Jul 2 | felt | `narrator-zimage`, `celeste-zimage` 2.0 solo, 1.5/1.5 two-shot | set canon appended | 1,986 / 2,642 | brown/braided drift; cool-edge drift |
| v3a | Jul 3 | felt → "LAIKA smooth clay-resin" | `*-coraline` 2.0 / 1.5+1.5 | Celeste "sleek jet-black straight"; style canon on every prompt | 3,111 / 3,317 | forbid-strip mangling starts (`clean-shaven with no,`) |
| v3b | Jul 4 | clay | same | storefront rebuilt, spacious interior, narrator "white hoodie" | 3,769 / 4,691 | "painted backdrop sky" + "no sky is visible" in one prompt |
| v3c | Jul 5 | clay | 1.8 / 1.5 | mid-back dreads, black distressed shirt; high-tops; Argentinian patrons | 4,116 / 4,437 | render failed when the narrator was named in a shadow shot; dreads short |
| v3d | Jul 5 | clay | `*-coraline-turbo` 1.0 | TVs on the sill; "no lipstick, no eyeshadow, no blush" | 4,135 / 5,640 | model adds lipstick and blush; high-tops at normal height; stray TV; patrons ignored |
| v3e "hand-drafted" | Jul 6 01:31 | clay | turbo 1.0 | Celeste "Chuck Taylor", hair "pulled up" | 4,120 / 6,014 | crimson vs canon amber; "no shoes" vs canon Jordans |
| **v3g** "oldceleste" | Jul 6 03:42 | clay | turbo 1.0/1.0, **fixed seeds** | canon re-appended per edit (2×) | 5,337 / 7,416 | dreads dropped; Celeste bleeds onto patrons |
| **v3f** | Jul 6 07:40 | clay | turbo 1.0 / Celeste 0.88 | "HUMAN skin… NOT gray, NOT and NOT blue-toned" | **6,992 / 9,027** | canon 3× per prompt; TVs on the sill in shot 1 but high in shots 2 and 6 |
| redesign `celeste-v2-design-TARGET.md` | Jul 10 | — | — | Celeste v2: curly bun + strand, peach-ivory, button-down, slim jeans | — | locked into canon Jul 13, before any approved render |
| current 8-shot `visual-batch.md` | Jul 13 | clay | narrator-turbo 1.2 + celeste-v2 0.85 (two-shot); 1.0 solo | — | 4,000 / 5,712 | two-shot cross-bleed (Celeste in his AJ1s); identity drift; gray skin on shot 7 |
| composite `celeste-composite.batch.md` | Jul 13 | clay | narrator solo, then inpaint Celeste v2 only | — | — | bleed eliminated; seam on a plain wall; the 0.3 "unify" pass made it worse |
| editor bake-off `bakeoff/session-log.md` | Jul 16–Aug 1 | "LAIKA painted resin" | none (Qwen-Image-Edit 2511 reference edit) | — | — | a two-stage recipe works for a hero; not yet gate-approved; $14.71 |

---

## 3. Failure A — prompt generation

| # | Cause | Evidence | Status |
|---|---|---|---|
| A1 | **The drafter had no Z-Image knowledge.** The system prompt addresses "(Flux, SDXL, WAN)" and its example spec is `steps 20, cfg 1.0, euler, flux_guidance 3.5`. The CLI loads **no** craft doc (`draft_redraft_analysis.md` §1), so the locked recipe and locked phrases never reach it unless retrieval happens to surface them. | `chains.py:34`, `chains.py:67`. "Flux-adjacent" in v3b:14 and v3e:44. v1:4 recommends "CFG 7.0 with DPM++ 2M Karras at 30 steps". `euler` on every spec in the current batch. | **Open** |
| A2 | **Canon was appended and then forbid-stripped over the whole prompt.** It used a raw substring regex with no word boundaries, and the regex also ran over the canon text itself. | Old `canon.py:262-284` (at `93b8b56^`). Rendered prompts contain `clean-shaven with no,` (71), `plain uncolored cheeks with no,` (27), `no lipstick, no eyeshadow, no,` (23), `NOT, NOT blue-toned` (22) and `NOT gray, NOT and NOT` (7). | Removed in `93b8b56` |
| A3 | **Duplicates accumulated.** `_dedupe_locked` only collapsed *verbatim* copies. Once a strip altered the injected copy, every redraft appended another one. The LLM had also already paraphrased the canon, because it received the text through the cast block and `[PROJECT CANON]`. | Canon appears 2× per prompt in v3g and 3× in v3f. Median length went 958 → 1,986 → 3,111 → ~4,100 → 6,992 characters (v1 → v3f). | Removed in `93b8b56` |
| A4 | **No prompt length or token limit.** `MAX_DRAFT_TOKENS = 4096` lets the LLM emit essay-length prompts. Canon was appended *at the end*, so if the text encoder truncates, the identity text is what gets cut. | `constants.py:131`. Max 9,027 characters. Nothing in the code is aware of the encoder. | **Open.** The truncation length is unverified (see §11). |
| A5 | **Negations in the positive prompt at cfg 1.** The negative goes through `ConditioningZeroOut`, and any negative the LLM writes is dropped, so every "don't" was written as a positive mention. A diffusion text encoder doesn't reliably bind "NOT" to the next word. Mentioning "gray", "blush" or "look alike" adds those concepts to the conditioning. | Examples: "no twists, no curl" (v2:16); "NO faces, NO profiles" (v3c:51); "ONE television only no second screen" (v3d:46); "they must not look alike" (current:15); Celeste canon "NOT gray, NOT ashen". Result: shot 7 Celeste has gray-blue skin, and blush persists. `z-image-turbo-craft.md` Technique 14 had already recorded "positive descriptors beat negative subtraction". | Negation still reaches the LLM via `[PROJECT CANON]` text (`retrieval.py:353-357`) — **open** |
| A6 | **LLM prose and appended canon contradict each other in the same prompt.** The model averages or picks between them. | Hair: "black hair just past shoulders" vs "dark brown curly … bun" (composite:16). Legs: "black slacks" vs "slim jeans". Sky: "painted backdrop sky" vs "no sky is visible" (v3b:11). Light: "crimson" vs "warm amber" (v3e:36). Shoes: "no shoes" vs "Jordan 1 sneakers" (v3e:41, v3f:41). Floor: "terracotta tile" vs "honey wood plank" (composite:16). Eyes: "slightly oversized expressive eyes" vs button eyes (v3d:16). | Partly removed along with injection; the LLM can still contradict retrieved canon |
| A7 | **Subject-presence matching can't read negation.** "No Celeste in this shot" matches the alias, so Celeste's LoRA or descriptor was pulled into narrator-only shots. | v3d:11 and v3e:11 ("No Celeste present. … a young woman with warm cream …"). `README.md:247-257` documents this as planned work. | **Open** |
| A8 | **Trigger tokens were never part of the prompt contract.** No code inserts them, and the canon JSON has no trigger field. | `clstwtrss` appears in 9 of 83 Celeste-LoRA renders, and `chrsnrtr` in 4 of 85 narrator-LoRA renders. The only batch that uses them consistently is the QKV load test. | **Open** |
| A9 | **Locked wording didn't survive into prompts.** The proven narrator phrase "long black … dreadlocks falling to the middle of his back" was sent as "just past his shoulders", "reach his shoulder blades" and so on. | `bar-exterior-*.batch.md`; `draft_redraft_analysis.md` §1 | Process gap — **open** |
| A10 | **Stated rationales don't match the recorded settings**, in every version. | v2: "0.85", "1.8" claimed, 2.0 ran. v3b: 1.8 claimed, 1.5 ran. v3d/v3e: 0.85/1.2/1.3/1.5/1.8 claimed, 1.0 ran. Current: "1.0 each" claimed, 1.2/0.85 ran; "turbo-2500" named, v2 ran; "at 1.5 each" claimed, 1.0 ran. `celeste-realconv`: "LoRA at 1.0 anchors" claimed, `lora_stack: []`. | **Open.** Nothing cross-checks the rationale against the spec. |

**Conclusion (A):** a prompt layer that damaged itself, grew without bound, and contradicted itself
made every multi-subject prompt worse. It is **not** why the project failed. `a0399398`, a short,
clean 502-character prompt, still came out waxy and CGI-looking. But it muddied every experiment
and hid the real causes.

---

## 4. Failure B — LoRAs and character consistency

### 4.1 The training data

| Dataset | Frames | Source | Seed(s) actually used | Coverage problems |
|---|---|---|---|---|
| `lora/celeste/` (felt) | 15 | Z-Image-Turbo t2i, no LoRA | 13 of 13 with metadata = `1065558432276088` | "long straight black yarn hair", "large glossy four-hole" eyes; blush captioned in 10 of 15 |
| `lora/narrator/` (felt) | 12 | Z-Image-Turbo t2i, 5 cropped to remove Celeste | 4 of 7 = `1065558432276088`, 2 = 42, 1 = 2855117723 | 6 of 12 rear views with no face; no profile; two repeated compositions (`character-lora-narrator-audit.md`) |
| `lora/celeste-coraline/` | 12 | Z-Image-Turbo img2img (denoise 0.62–0.85) of earlier gens | 12 of 12 = `719249596297021` | "sleek jet-black shoulder-length hair … absolutely no curls"; blush captioned in 6 of 12 |
| `lora/narrator-coraline/` | 9 | Z-Image-Turbo img2img (0.75–0.82) of real photos | 9 of 9 = `719249596297021` | **goatee** in the generating prompt (canon forbids it); 4 of 9 in a beanie or cap; non-canon outfits; 2 frames from one photo |
| `lora/celeste-coraline-v2/` | 11 | ChatGPT renders (another model) | n/a | 11 of 11 captioned "in a sports bar"; 6 of 11 sit cross-legged; almost only smiles; 2 in short sleeves and shorts |

**Causes, in order of weight:**

- **B1. The target model generated its own training data from one noise seed.** Four of the five
  datasets are Z-Image-Turbo outputs of Z-Image-Turbo prompts. A LoRA trained on them learns the
  base model's own prior back, including its waxy CGI surface. The shared seed comes from the seed
  bug (§6, D2-1), and it cut composition and pose variety further.
- **B2. The identity being learned wasn't the identity wanted.** Each dataset reflects the design
  of its moment. The final canon forbids straight hair and blush, requires *small flat* buttons,
  and requires a clean-shaven narrator. The earlier LoRAs had been taught the opposite, so text
  canon and LoRA fought each other in every render that used an older LoRA.
- **B3. The captioning scheme needed a token that was never sent.** Face, eyes, hair and skin were
  deliberately left uncaptioned so the token would own them. Wardrobe, background and pose were
  captioned. Without `clstwtrss` / `chrsnrtr` in the prompt (A8), the LoRA's identity was only
  weakly engaged. Meanwhile the captioned background ("in a sports bar" in 11 of 11 v2 frames) and
  the wardrobe ("ripped jeans", canon says "slim jeans") were still absorbed.
- **B4. No single approved sculpt, no multi-view sheet, no held-out validation.** The Consolidated
  audit §7 covers this fully. The key point is that consistency matters more than count, and these
  frames vary in face width, jaw, button construction, bun size and proportions.
- **B5. The training record is missing or contradictory.** No training YAML, learning rate or log
  exists under `~/agent-data`. Only the v2 safetensors header survives: ai-toolkit 0.10.24, base
  `zimage`, rank 8, step 1250/1500, epoch 37/45. On the base model: the v2 README says "train on
  Z-Image-Base", `celeste-v2-qkv.batch.md` says "Turbo-trained", and the narrator audit plans Base.
  `fidelity-drift-learnings.md` §2 states that Base-trained LoRAs under-apply on Turbo. **Which base
  each shipped LoRA was trained on can't be established from the artifacts.**

### 4.2 How the LoRAs were used at inference

- **B6. Strength wandered: 0.05, 0.85, 0.88, 1.0, 1.2, 1.5, 1.8, 2.0** across 7 LoRA files in the
  renders (the registry lists 9). At 1.5–2.0 a LoRA overrides the prompt's pose and staging and
  copies the character onto background extras. The rationales record this repeatedly: "bled onto
  background figures", "patrons read nearly all-female".
- **B7. Two identity LoRAs applied to the whole image.** 59 renders chained a Celeste LoRA and a
  narrator LoRA as `LoraLoaderModelOnly → LoraLoaderModelOnly` on the shared model, with no region
  masks. This is **why** two-shots cross-bleed. Strength rebalancing only changes which character
  wins (`0646f23c`: at narrator 1.2 / Celeste 0.85 she wears his AJ1s). It was confirmed
  architectural by `dc1456d8`, where inpainting one LoRA per region removed the bleed.
- **B8. Two Celeste LoRAs from different designs stacked together.** Spec `92439e5a`
  (`celeste-v2-verify.batch.md`) runs `celeste-zimage-coraline-turbo` @1.0 **plus**
  `celeste-zimage-coraline-v2` @1.0: the old straight-hair design and the new curly-bun design at
  the same time.
- **B9. Stale LoRAs stayed available to the drafter.** `models.json` lists all 9 character LoRAs,
  each `present_on_endpoint: true`. The `-turbo-2500` files are marked `identity_bearing: false`, so
  `prune_noncanon_identity` and the dual-identity advisory skip them. Retrieval feeds past
  generations with `narrator-zimage@2.0` and "felt and clay" prose back in as few-shot examples.
  Redraft and refinement inherit the parent's `lora_stack`. The composite "unify" pass
  (`4900c5fe`'s spec) lists the **old** `celeste-zimage-coraline-turbo`.
- **B10. The canon pin can be silently dropped.** Canon LoRA pins are appended *after* whatever
  the LLM chose (`draft.py:122-131`). On a single-loader template the pin lands at `lora_1`, has no
  slot, and is discarded (`graph_build.py:110-115`) with no message. Spec `f58a6388` stacked
  celeste@2.0 + narrator@2.0 on `visual-workflow-lora`, so the narrator LoRA never ran.
- **B11. A LoRA is baked into the template.** `workflows/z-image-turbo-lora-api.json:146` hardcodes
  `narrator-zimage.safetensors` @1.0, and the inpaint template hardcodes `celeste-zimage-coraline-v2`.
  A spec with `lora_stack: []` never writes the slot, so the template's LoRA runs. *No render in
  `identity/` shows `narrator-zimage` at 1.0, so this is a latent defect with no observed damage in
  the records.*

### 4.3 Correction to earlier evidence

- The five strong-looking Celeste pose images were **training inputs**, not LoRA outputs
  (Consolidated §1).
- `4452cf44` (solo is fine) vs `9ba816fd` (two-shot fails) proves that cross-bleed comes from the
  multi-subject setup. It does **not** prove the LoRA holds a stable identity: `7de112cb` vs
  `b7c7d55a`, both solo, are visibly different puppets.

**Conclusion (B):** the LoRAs were trained on too few frames, and those frames were generated by
the target model itself from one seed. They matched earlier designs, and the prompts rarely
engaged them through their trigger tokens. At inference they were stacked globally at wandering
strengths, alongside stale siblings. Whatever identity they did encode was a character class
("dark-haired button-eyed woman in black, in a bar"), not one puppet.

---

## 5. Failure C — scene and set consistency

- **C1. The set was re-specified in every version.** Storefront TVs went on a low stand, then
  mid-window, then centred, then at the bottom on the sill. In v3f the TVs sit on the sill in shot
  1 and hang high in shots 2 and 6, within one batch. Neighbouring buildings, the sky, the chairs
  (teal upholstered → matching high-top stools), the TV count, the patrons and the jazz band all
  changed between canon versions.
- **C2. Canon and batches disagree on basic facts.** The bar-exterior batches put Lakers left and
  Knicks right, while canon from v3b on puts Knicks left and Lakers right. Time of day drifts
  (v3d: dusk, then day, then night). The composite puts a terracotta tile floor where canon says
  wood plank.
- **C3. Subjects' canon clashed with each other.** Patrons are "pale skin with dark straight hair",
  while Celeste's forbid list contains `straight hair`. Under the old whole-prompt strip, one
  subject's forbid list edited another subject's description. Likewise the forbid "corner"
  (storefront) would strip "corner" from any prose.
- **C4. Text can't pin geometry.** The identical ~800-character interior block appended to shots
  2, 3, 4, 5 and 7 produced a different room each time (evidence doc §3J). There was no set plate,
  depth map, ControlNet or img2img from a master frame. The only structural lever tried, img2img
  from real bar photos at denoise 0.6–0.7 (v1, bar-exterior), was dropped.
- **C5. Seeds were used as a continuity tool, and couldn't be.** Seeds were chosen per shot, not
  per set, and in practice were mostly the template seed (D2-1). A shared seed across different
  prompts gives no geometric continuity in any case.
- **C6. The original look plan was dropped.** `techniques.md` planned the handmade texture as a
  Fusion composite of scanned paper and canvas, outside the model. Every tutorial-research lookup
  returned 0 items (`techniques.md:99-103`), and the plan never reached a batch. The texture job
  moved into prompt words ("smooth … satin sheen") that push toward CGI.

**Conclusion (C):** set continuity was never designed in. It was requested in prose, and the prose
itself kept changing.

---

## 6. Failure D — ignored values, and values that should not have been used

### D1. Values requested but ignored by the model

| Requested | What rendered | Where | Why |
|---|---|---|---|
| No makeup / no blush | lipstick and blush added | v3d:14,19,24; v3e:14,19; bake-off attempts 4–8 | Blush was **captioned into 16 training frames** (B2). "no blush" at cfg 1 is a positive mention (A5). The "Coraline" / doll prior. |
| Flat black button eyes | human, cartoon or glossy dome eyes; sizes wander | v1:54; v3a:14; evidence doc §3H | A weak token against a strong "eyes" prior; tiny at full-body scale; the training data varied the eye construction. It only succeeded via masks or composites (`fidelity-drift-learnings.md` §3.3). |
| Narrator mid-back dreadlocks | short cap, braids, or dropped | v3c:24; v3g:39; bar-exterior | Shorter wording was actually sent (A9). Black hair against a black sweater at night is near-zero contrast. Celeste's hair prior wins in two-shots (B7). A beanie hides the hair in 4 of 9 training frames. |
| Celeste curly bun + front strand | braids or straight hair | contact sheet shot 4 | The pre-v2 LoRAs learned straight hair (B2). Composite prose says "hair just past shoulders" (A6). |
| Warm peach-ivory skin | gray or blue-gray | shot 7 `b7c7d55a` | "NOT gray / NOT ashen" in the positive prompt (A5). `refsheets/README.md` says gray skin was present in the reference frames themselves. |
| Long sleeves | short sleeves | bar-exterior ("after four misses") | Sleeve length is a weak detail at 8 steps; only named garments worked. |
| Celeste's own shoes | narrator's red/white AJ1s | `0646f23c` | Global two-LoRA bleed (B7). |
| Tall high-top tables | normal-height tables | v3d:19; contact sheet | Object scale can't be enforced by text at cfg 1; there is no layout conditioning. |
| Argentinian patrons | ignored / nearly all-female / copies of Celeste | v3d:9; v3f:44; v3g:39 | Background extras take on the active LoRA identities at high strength (B6). |
| One TV only | a stray second TV | v3d:44 | Counting isn't reliable. "no second screen" names a second screen (A5). |
| Blocking ("waving", "backs to camera") | the blocking inverts; profiles instead of backs | v3f:29; v3g:24; v3b:49 | Spatial words carry little weight at cfg 1 (`fidelity-drift-learnings.md` §5). |
| Narrator scale | too large for the doorway | v3f:9 | Same as above. |
| "Knicks" signage | misspelled | v3f:4 | Text rendering at TV scale is unreliable. |

### D2. Values the pipeline used that it should not have

| # | Value that ran | Where it came from | Why it is wrong | Status |
|---|---|---|---|---|
| D2-1 | **The template's baked seed** (`1065558432276088` t2i, `719249596297021` inpaint/img2img) in place of every "random" seed | **Bug:** `graph_build.py:89-90` writes only `spec.seed`. `_resolve_seed` (`generate.py:133-136`) runs, but its value is only *recorded* (`generate.py:162,469`). | Every "random" re-roll reuses the same noise. The recorded seed is fictional, so "reproduce seed X" can't work. A redraft that re-pins `parent.seed` (`chains.py:336-337`) pins the fictional value and runs a *different* seed from the parent. **Explicitly fixed seeds were applied correctly** (v3g/v3f seeds, 123, 42, 7 and 778899 all appear in the rendered graphs). | **Fixed 2026-10-04** (§9 item 1) |
| D2-2 | 1152×896 (template default) and 832×1152 (current:19) | template latent default; LLM | 1152×896 stalls this workflow (`z-image-turbo-craft.md:167`). The project rule is 1024². Any spec without width and height inherits the bad default. | **Open.** The template default is still 1152×896. |
| D2-3 | `euler` sampler in the final batch and one composite plate, `res_multistep` elsewhere | the drafter's example JSON (`chains.py:67`) | Euler isn't wrong for Z-Image; the official guidance says Euler works well (`z-image-turbo-craft.md:929`). But it changed an uncontrolled variable mid-project with no recorded reason, so the Phase-E renders can't be compared with the earlier ones. | **Open** (drafter example) |
| D2-4 | LoRA strength 1.5–2.0 | canon pins @2.0 overriding the LLM (`39f7971`), plus Base-trained LoRAs that under-apply on Turbo | Overrides the prompt and copies identity onto extras (B6). | Canon now pins 1.0. There is no range check (warn-only at ≥1.5, `lora_guard.py`). |
| D2-5 | Two identity LoRAs globally; two Celeste LoRAs together | drafter, the `lora2` template, inheritance | B7, B8 | `lora2` deleted in `93b8b56`; stacking is advisory only — **open** |
| D2-6 | Stale LoRAs (old `celeste-zimage-coraline-turbo` in the unify pass; `-2500` named in rationales) | registry, retrieval, parent inheritance | B9 | **Open** |
| D2-7 | Template-baked LoRAs on empty stacks | `z-image-turbo-lora-api.json:146`, inpaint template | B11 | **Open** (latent) |
| D2-8 | `DEFAULT_DENOISE = 0.5` for source specs, `settings: {}` falling back to template defaults, `ModelSamplingAuraFlow shift 3` with no slot | `constants.py:213`, `generate.py:148-156`, `chains.py:318` (refinement wipes settings) | These values apply silently. Inpaint and img2img specs record only denoise, so steps, cfg and sampler are whatever the template holds, and the batch file doesn't show them. | **Open** |
| D2-9 | Dropped values (LoRAs beyond the loader count, settings with no slot) | `graph_build.py:82-84,110-115` | Collected into `unmapped`, then **never printed** by `cli.py`. The user believes a value ran when it didn't. | **Fixed 2026-10-04** (§9 item 2; warn-only except a missing seed slot) |
| D2-10 | Negation phrases as positive tokens | canon `locked` text, LLM prose | Official guidance is guidance 0 for Turbo, so there is no working negative (model card: "Guidance should be 0 for the Turbo models"). Negations therefore can't work as intended, and they add the very concept they try to exclude. | Canon injection removed; the LLM still writes them — **open** |
| D2-11 | Style words "smooth … matte clay-resin … satin sheen", with the style subject **forbidding** "stitched seams" and "visible fabric weave" | the style canon | Pushes away from LAIKA's tactile imperfection and toward CGI (evidence doc §4.5). Also contradicts itself: Celeste forbids "lacquered sheen" while the style block asks for "soft lacquered gloss". | Superseded by the bake-off material spec ("painted resin", `ad10796`); the old canon JSON still holds it |
| D2-12 | SDXL-era advice (CFG 7 / 3.5, DPM++ 2M Karras, 30 steps) | LLM rationale (v1:4, v1:9) | Wrong model family. It wasn't applied (recorded cfg was 1.0), but it shows A1. | Open (A1) |
| D2-13 | **Correct and held throughout:** cfg 1.0, 8 steps, negative null | — | Matches the official card (9 inference steps ≈ 8 DiT forwards, guidance 0) and the craft doc. The failure wasn't in these core numbers. | — |

---

## 7. Process and tooling gaps

- **Nothing checks the output image.** `verify.py` checks retrieval coverage only. There is no
  face or identity similarity check against a reference, no presence or wardrobe check, and no
  comparison between the submitted graph and the spec. Judging was manual and one image at a time,
  so gradual drift across shots wasn't visible until the contact sheet.
- **Records can't be trusted:** fictional seeds (D2-1), unprinted `unmapped` values (D2-9), and
  rationales that differ from the spec (A10). `inspect` shows *recorded* settings, which inherits
  all three problems.
- **Cost wasn't tracked.** `gpu_ledger.json` = $3.74. `audit-prompt.md` reports more than $100 over
  about three weeks, plus training pods. The bake-off separately logged $14.71. Pod uptime and
  training runs never reached the ledger.
- **Artifacts were lost.** The composite masks lived in a session scratchpad (`/private/tmp/…/mask_s3.png`
  and others) and are gone. `narrator-eye-inpaint.batch.md` references
  `assets/masks/narrator-eye-mask.png`, which doesn't exist. `batch.batch.md` references mask names
  that don't match the files on disk.
- **Batch-file parsing is fragile.** The spec-metadata regex stops at the first `-->`
  (`batch_file.py:38`), so a rationale containing `-->` leaves the JSON incomplete. When metadata
  fails to parse, the spec's settings, LoRAs and seed are silently discarded.
- **The design target moved four times** (felt → sleek straight clay → v2 curly bun → painted
  resin). Canon was relocked each time before any render was approved, despite `celeste-v2/design.md`
  warning: "Do NOT lock canon to this until a render is director-approved."
- **Iteration without a stopping rule.** Seed sweeps (not real sweeps, per D2-1), strength
  rebalancing and prompt re-wording went on for weeks. The bake-off's "three strikes per defect"
  guardrail was the first explicit stop rule, and it worked: it forced the two-stage recipe.

---

## 8. Where the earlier write-ups are wrong or superseded

| Earlier claim | Doc | Correction |
|---|---|---|
| Per-image seeds (e.g. `9ba816fd` seed 131467551, `0646f23c` 3977768408, `4452cf44` 2636692908) | `coraline-prompt-to-image-evidence.md` §3 | These are the recorded values. The rendered graphs show **all** of those images, and every other Phase-E t2i frame listed, ran on `1065558432276088` (composites on `719249596297021`). |
| "8 targeted attempts (strength rebalance + explicit-seed sweeps)" | quality analysis §3C; evidence doc §3B | The "random" re-rolls weren't seed sweeps. The conclusion (cross-bleed is structural) still holds because of the `dc1456d8` composite, but the sweep adds no evidence. |
| "The LoRA is not the problem — the multi-character frame is" | evidence doc §3D | True **only** for cross-bleed. Solo identity drifts too (`7de112cb` vs `b7c7d55a`), and the data problems in B1–B4 are real. |
| Strong solo Celeste images = LoRA outputs | earlier arguments; corrected in Consolidated §1 | They were training inputs. |
| "Training recipe proven twice … trained on Turbo + adapter" | `fidelity-drift-learnings.md` §2, §4 | The v2 artifacts don't show which base was used (README says Base, batch notes say Turbo, header says `zimage`). Treat the recipe as unverified. |
| Increase LoRA rank to ~64 | earlier recommendation | Rejected (Consolidated §7). Rank doesn't fix inconsistent source data. |
| Prompts "3,000–4,800 chars" | evidence doc §1 | The spread is wider: medians from 958 (v1) to 6,992 (v3f), max 9,027. |
| `fidelity-drift-learnings.md` / `coraline-visual-quality-analysis.md` "do not exist" | `docs/agent-retrospective-corrections.md` caveats | Both are now in `packages/visual-generation/docs/`. |

---

## 9. Fixed vs still open

**Landed:**

| Commit | Change |
|---|---|
| `39f7971` | canon-pinned LoRA strength overrides the LLM's guess |
| `1de80c7` | `lora_guard` strength warnings, `prune_noncanon_identity`, `model rm` (prune has the `-2500` gap) |
| `515eb49` / `9d1afca` | two-slot `lora2` template (later **reversed**) |
| `8666392` | prompt-to-image evidence doc |
| `93b8b56` | removed `enforce_canon`, forbid-strip, `_tidy`/`_dedupe_locked`, locked-text injection and the `lora2` template; canon became a subject registry |
| `40f0ba6` | removed the last `enforce_canon` reference from the playbook |
| `ad10796`, `d598337` | bake-off material spec correction; hero resolution pass |

**Still open.** Fix these before any further generation, on any model:

1. ~~Random seed never written to the graph~~ **Fixed 2026-10-04 (uncommitted)** (D2-1). `plan_generation` now resolves the seed
   before building the graph (`generate.py:339-341`), so the recorded seed is the submitted seed; `random` overrides a leftover
   `spec.seed`. Tests: `test_generate.py::test_random_seed_strategy_writes_the_rolled_seed_into_the_graph`,
   `::test_random_seed_strategy_overrides_a_pinned_seed_in_graph_and_record`, `::test_fixed_seed_is_submitted_and_recorded_exactly`,
   `::test_two_plans_of_a_random_spec_get_different_seeds`. Records made before this fix still carry seeds that never ran.
2. ~~`unmapped` never shown to the user~~ **Fixed 2026-10-04 (uncommitted)** (D2-9). The `generate` cost gate prints it per spec
   before the confirm (`cli.py:725`, helper `cli.py:112`); a spec whose template has no seed slot is skipped with a reason
   (`generate.py:342-349`); `quick` prints it (`cli.py:939`) and refuses on a missing seed slot (`quick.py:160`); the list rides on
   `VisualResult.unmapped` (`generate.py:514`) and `QuickResult.unmapped` (`quick.py:74`). Tests:
   `test_cli_turn.py::test_cli_generate_gate_warns_on_unmapped_values_before_the_confirm`,
   `test_generate.py::test_spec_whose_template_has_no_seed_slot_is_skipped_with_a_reason`,
   `::test_unmapped_values_ride_on_the_plan_and_the_result`, `test_quick.py::test_quick_returns_unmapped_values_on_the_result`,
   `::test_quick_refuses_when_the_template_has_no_seed_slot`, `test_cli_quick.py::test_quick_warns_when_a_requested_value_has_no_slot`.
   Other dropped values (LoRAs beyond the loader count, etc.) now warn but still do not block.
3. LoRAs baked into the templates apply on empty stacks (B11).
4. Canon pin dropped beyond the loader count, silently (B10).
5. Template default resolution 1152×896 (D2-2).
6. No validation or clamping of steps, cfg, denoise, strength or size; no prompt length or token budget (A4).
7. The drafter system prompt has no Z-Image guidance and uses a Flux/euler example (A1).
8. `-2500` LoRAs marked `identity_bearing: false`; stale LoRAs offered to the drafter (B9).
9. `[PROJECT CANON]` text still sent to the LLM as "LOCKED — never contradict", with a stale
   docstring claiming deterministic enforcement (`retrieval.py:278-280, 353-357`).
10. Alias matching counts negated mentions (A7).
11. Trigger tokens are not part of the spec contract (A8).
12. No image-level verification (§7).
13. The GPU ledger doesn't capture pod uptime or training.

---

## 10. Conclusions and implications

- **Why the prompts failed:** a drafter with no model-specific grounding, a canon layer that
  appended and blindly stripped text, and no length budget produced long, repetitive,
  self-contradicting, negation-heavy prompts. The worst of the machinery is now gone (`93b8b56`).
  The drafter-grounding and length problems are not.
- **Why the LoRAs failed to hold the characters:** they learned a *class*, not a puppet. The data
  was small, generated by the target model from one seed, set in one location, and matched an
  outdated design. The trigger was rarely sent. At inference they were stacked across the whole
  image at wandering strengths next to stale siblings. No LoRA recipe fixes spatial binding
  (two-shots) or guarantees one exact face.
- **Why the scenes didn't stay consistent:** there was never a set asset. There was only prose,
  and the prose kept changing.
- **Why values were ignored or wrongly used:** partly model limits (cfg 1 adherence, the scale of
  small details, prior strength, bleed), and partly **the pipeline itself**: a template seed posing
  as random, template defaults, silently dropped slots, stale LoRAs, and positive-prompt negations.
- **What this means:** the Consolidated audit's direction still stands: approved hero reference
  packs, master set plates, sequential single-identity masked edits, and Z-Image kept for ideation.
  The bake-off's two-stage Qwen-Edit recipe is the first result on that path. **The §9 "still
  open" items are prerequisites:** a future bake-off run through this agent would otherwise report
  seeds, LoRAs and settings that never ran.

---

## 11. Sources and reproduction

**Inputs reviewed:**
- `~/agent-projects/celeste-you-dangerous/`: all `visual-batch*.md` versions, `story.md`,
  `script.md`, `directed.md`, `techniques.md`, `audit-prompt.md`, `audit-bundle/` (canon, batches,
  training frames and captions, proof images), `workflows/`, and the problem board and contact
  sheet.
- `~/agent-data/visual-generation/`: `lora/*` datasets and captions, `canon/*` (5 versions),
  `batches/`, `celeste-*.batch.md`, `refsheets/`, `identity/celeste-you-dangerous/` (375 PNGs),
  `assets/`, `bakeoff/`, `models.json` and `gpu_ledger.json`.
- `~/agent-data/drafts/`: **empty**. `user_knowledge/` and `music-curation/taste-pending/` contain no
  files, so there was nothing relevant.
- Code: `packages/visual-generation/src/visual_generation/` at HEAD `4454f3a`, plus old
  `canon.py` at `93b8b56^`.
- Model card: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo (9 steps ≈ 8 DiT forwards; "Guidance
  should be 0 for the Turbo models"; 1024² example). It says nothing about negative prompts or a
  token cap.

**How the numbers were produced.** A stdlib Python script parses the ComfyUI API graph from each
PNG's `prompt` tEXt chunk. For every sampler, LoRA loader and text-encode node it extracts
`seed`/`noise_seed`, `lora_name`/`strength_model`, and the longest `text`. It then counts:
- seeds per dataset and per render date;
- trigger tokens among renders that loaded a LoRA;
- occurrences of the mangled canon strings;
- prompt lengths.

Batch prompt lengths come from the body text after each `<!-- vg-spec: … -->` block. Results at
the time of writing:

```
lora/celeste 13/13 seed 1065558432276088 · celeste-coraline 12/12 & narrator-coraline 9/9 seed 719249596297021
identity renders: 375; on a template seed: 340 (719249596297021 ×265, 1065558432276088 ×75)
Jul 6 (explicit v3g/v3f seeds): 18/18 non-template · Jul 13: 28/37 template (explicit 123/42/7/778899 applied)
Celeste-LoRA renders 83, with clstwtrss 9 · narrator-LoRA renders 85, with chrsnrtr 4 · two-character stacks 59
"clean-shaven with no," 71 · "cheeks with no," 27 · "no eyeshadow, no," 23 · "NOT, NOT blue-toned" 22 · "NOT gray, NOT and NOT" 7
LoRA strengths seen: 0.05 0.85 0.88 1.0 1.2 1.5 1.8 2.0 · samplers: res_multistep 353, euler 22
```

**Qdrant (recorded, not actual, seeds):**
```bash
curl -s "$QDRANT_URL/collections/visual_generation_memory/points/scroll" -H "api-key: $QDRANT_API_KEY" \
  -d '{"filter":{"must":[{"key":"memory_type","match":{"value":"generation"}}]},"limit":50}'
```

**Unverified:**
- Whether ComfyUI's lumina2 / Qwen3-4B text path truncates long prompts, and at what length. If it
  does, the appended canon was the part cut off in the longest prompts.
- Whether an identical graph resubmitted as a "random" re-roll was served from ComfyUI's execution
  cache (no new image) or re-sampled.
- Which base model (Z-Image-Base or Turbo + adapter) each shipped LoRA was trained on.

**Related docs:** [quality analysis](coraline-visual-quality-analysis.md) ·
[prompt-to-image evidence](coraline-prompt-to-image-evidence.md) ·
[Consolidated audit](Consolidated-Coraline-Stop-Motion-Visual-Generation-Audit.md) ·
[fidelity-drift learnings](fidelity-drift-learnings.md) ·
[narrator LoRA audit](character-lora-narrator-audit.md) ·
[draft/redraft analysis](draft_redraft_analysis.md) ·
[bake-off log](bakeoff/session-log.md) ·
[retrospective corrections](../../../docs/agent-retrospective-corrections.md) ·
[cleanup report](../../../docs/visual-generation-cleanup-report.md)
