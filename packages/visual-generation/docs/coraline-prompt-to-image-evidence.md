# Coraline / LAIKA — prompt‑to‑image evidence & diagnosis

**Author:** Claude (Opus 4.8). **Date:** 2026‑07‑14.
**Companion to:** [`coraline-visual-quality-analysis.md`](coraline-visual-quality-analysis.md)
(the root‑cause analysis) and the visual **problem board**
(`~/agent-projects/celeste-you-dangerous/phase-e-PROBLEM-BOARD.png`).

This document is the **forensic layer**: it ties the *actual prompts we sent* and the *canon
documents that get injected* to the *specific images they produced*, then names the mismatch and
the diagnosis for each. Everything below is quoted from real records, not reconstructed — sources
in §7.

> **How to read this.** §1 shows how a prompt is actually assembled (this is where several defects
> are born, before the model even runs). §2 shows the raw canon documents being injected. §3 is the
> per‑image evidence: intent → config → real prompt excerpt → asked‑vs‑got → diagnosis. §4 collects
> the *prompt‑level* defects that are visible in the text itself. §5 maps everything back to the
> architectural root causes. §6 is the short version. §7 is reproduction.

---

## 1. How a prompt is actually built (the assembly pipeline)

For every generation, the final positive prompt is assembled in layers:

1. **LLM‑composed prose.** `draft` compiles the shot intent + project docs into a descriptive
   paragraph (the "composed prose"). This paragraph *already* describes the characters, the set,
   and the style.
2. **Canon injection (append).** For each `--canon` subject named, the subject's **full `locked`
   descriptor is appended verbatim to the end of the prompt**, and its **`forbid` phrases are
   substring‑stripped** from the whole thing. Canon also pins the subject's LoRA + strength.
3. **Result:** `[composed prose] + [Celeste.locked] + [narrator.locked] + [set.locked] +
   [style.locked]`, then forbid‑stripped. **No negative prompt** (we run cfg ≈ 1, so classifier‑free
   guidance is effectively off — there is nowhere for "don't do X" to live except the positive text).

The consequence, visible in every multi‑canon frame: the prompt balloons to **3,000–4,800
characters**, the **style boilerplate and each character description appear 2–3×**, and the
forbid‑strip **mutilates the injected canon text** (see §4). The model is handed a long, repetitive,
partly self‑contradictory, partly ungrammatical instruction — *before* any of the deeper
architectural problems apply.

## 2. The canon documents being injected (raw material)

These are the exact `locked` descriptors + `forbid` lists stored in
`~/agent-data/visual-generation/canon/celeste-you-dangerous.json` and appended into prompts.

**Celeste** (LoRA `celeste-zimage-coraline-v2.safetensors@1.0`)
> *locked:* "a young woman with her real face and slim natural real‑woman proportions, warm
> peach‑ivory clay skin with a subtle satin sheen — **clearly NOT gray, NOT ashen, NOT blue‑toned**
> — bare‑faced with no makeup, small round flat black Coraline button eyes, dark brown curly hair
> worn up in a voluminous textured bun with one long curly strand falling down in front of her face,
> dressed in a black long‑sleeve collared button‑down shirt with black slim jeans and a small pendant
> necklace, black low sneakers with white soles and white ankle socks"
> *forbid:* `human eyes, braid, pigtail, blush, rosy, short sleeve, short-sleeve, bare arms,
> sleeveless, felt skin, felt texture, yarn, lacquered sheen, red lips, glossy lips, heavy makeup,
> gray skin, grey skin, ashen, gray complexion, greyish, blue-grey skin, freckles, straight hair,
> Chuck Taylor`

**The narrator / Chris** (LoRA `narrator-zimage-coraline-turbo.safetensors@1.0`)
> *locked:* "a young Black man, warm medium caramel‑brown smooth sculpted clay skin with a subtle
> satin sheen, **clean‑shaven with no facial hair**, long dreadlocks falling to the middle of his
> back, dressed in streetwear — a long black distressed long‑sleeve shirt, dark denim jeans, and
> red‑and‑white Jordan 1 sneakers"
> *forbid:* `short hair, shoulder-length, buzz cut, lanky, skinny, slender, felt skin, felt texture,
> yarn, goatee, facial hair, stubble, sleeveless`

**"the style"** (no LoRA — deterministic style channel, forced on every shot)
> *locked:* "a LAIKA stop‑motion production still … hand‑sculpted puppets with **smooth matte
> clay‑resin skin and a subtle satin sheen** … clothing is real miniature fabric with fine knit and
> weave texture — fabric texture belongs to garments only, never to skin …"
> *forbid:* `felt and clay, felt-and-clay, felt puppet, handmade felt, felt texture, felt skin,
> stitched seams on every surface, visible fabric weave and stitched seams, yarn hair`

**The bar interior** (no LoRA) — an ~800‑character locked block ("the spacious deep interior of a
modern Buenos Aires sports bar with smooth painted clay‑and‑resin surfaces, burnt‑orange terracotta
… long polished wood bar counter … Edison‑bulb cage pendant lights …"). This *same block* is appended
to shots 2, 3, 4, 5, 7 — yet each renders a **different room** (see §3F).

**Two things to notice already:**
- The word **"smooth"** is baked into *every* character and set descriptor, and "the style" **forbids
  the exact tactile cues** ("stitched seams", "visible fabric weave") that make LAIKA read as
  handmade. We are prompting ourselves into the plastic look.
- Celeste's locked text contains three **positive‑prompt negations** ("NOT gray, NOT ashen, NOT
  blue‑toned") and her forbid list contains `ashen` — which then strips the word out of her own
  locked text at injection time (§4.2).

## 3. Per‑image evidence

Each entry: **gen_id** · reaction · workflow · LoRA stack · seed · denoise → intent → prompt excerpt
→ asked‑vs‑got → diagnosis. Images are on the problem board and in
`~/agent-data/visual-generation/identity/celeste-you-dangerous/<gen_id>.png`.

### 3A. Cross‑bleed — `9ba816fd` (shot 3, two‑shot, **render_failed**)
`visual-workflow-lora2` · `narrator-turbo@1.0 + celeste-v2@1.0` · seed 131467551 · denoise 1.0

*Intent:* narrator seated at a high‑top, Celeste standing over him with a tray, smug.
*Prompt (excerpt — note it describes two clearly distinct people):*
> "…the narrator Chris seated at a tall high‑top stool … head tilted upward looking up at Celeste …
> long dreadlocks falling to his back … red‑and‑white Jordan 1 sneakers … Celeste the waitress
> stands beside him on the right … dark brown curly hair worn up in a voluminous textured bun …
> black low sneakers with white soles … power dynamic blocking: standing figure dominant over
> seated figure …"

*Asked vs got:* asked for a **Black adult man with mid‑back dreadlocks** seated + a **distinct
woman**. Got: the seated figure rendered as a **young braided girl** — the narrator's identity
collapsed and absorbed Celeste's hair prior. Two people, one look.
*Diagnosis:* **§4.1 (no identity guarantee) + §4.3 (no regional conditioning).** Two LoRAs paint the
whole canvas with nothing to say "this region is A, that region is B." The smaller/seated figure
loses. Prompt phrasing ("two distinct people", "power dynamic blocking") has no spatial force.

### 3B. Cross‑bleed, worst case — `ee3b2587` (shot 5, two‑shot, pending)
`visual-workflow-lora2` · `narrator-turbo@1.0 + celeste-v2@1.0` · seed 1286433016 · denoise 1.0

*Intent:* narrator + Celeste at the bar, tequila toast.
*Asked vs got:* both figures rendered as **near‑identical young girls with braided buns** — neither
is the adult male narrator, neither is clearly Celeste. Total identity collapse.
*Diagnosis:* same as 3A; this is the extreme of the failure mode. Across **8 targeted attempts**
(strength rebalance + explicit‑seed sweeps) no single frame got both characters right.

### 3C. Attribute swap (the smoking gun) — `0646f23c` (shot 5 rebalanced, pending)
`visual-workflow-lora2` · `narrator-turbo@1.2 + celeste-v2@0.85` · seed 3977768408 · denoise 1.0

*What changed:* pushed the narrator LoRA up (1.2) and Celeste down (0.85) to fight the bleed.
*Asked vs got:* the narrator now **holds** his dreadlocks — but **Celeste is wearing his red/white
Jordan 1 sneakers** and picked up braided buns. The bleed didn't stop; it **reversed direction**.
*Diagnosis:* this is the clearest single proof that the two LoRAs **imprint on each other's
figures** (§4.3). Strength tuning only moves *which* character wins; it cannot separate them. Only
regional/masked conditioning (or one‑LoRA‑at‑a‑time compositing) can.

### 3D. Solo holds — `4452cf44` (shot 1, narrator solo, **loved**)
`visual-workflow-lora` · `narrator-turbo@1.0` · seed 2636692908 · denoise 1.0

*Asked vs got:* clean, on‑model narrator (mid‑back dreadlocks, distressed black, AJ1s), correct rear
staging, storefront TVs showing the game. **This is the control case.**
*Diagnosis / significance:* the **same narrator LoRA** that collapses in 3A/3B is crisp here.
**Therefore the LoRA is not the problem — the multi‑character frame is.** `4452cf44` vs `9ba816fd`
is the single most diagnostic comparison in the set (problem board row 3). It isolates the cause to
§4.3 (missing regional conditioning), not identity quality.
*Prompt note:* even this "good" prompt is mangled — it contains **`clean-shaven with no,`** (the
forbid `facial hair` stripped the object of the sentence) and the whole style block appears twice.
It rendered well *despite* the prompt, because it's a solo with a strong LoRA and simple staging.

### 3E. Composite seam — `065cfbf0` (shot 5 inpaint‑composite, pending)
`visual-workflow-inpaint-lora` · `celeste-v2@1.0` **only** · seed 234583645 · denoise 0.9 · source
`f93aebd0` (narrator base solo)

*Method:* render the narrator solo in‑scene (`f93aebd0`), then inpaint Celeste into the empty right
side with **only her LoRA** (no narrator LoRA present → no cross‑bleed).
*Asked vs got:* **both identities are now correct and distinct** (the cross‑bleed is gone — the new
`visual-workflow-inpaint-lora` template works) — but the rectangular mask regenerated a strip of
**plain wall**, leaving a **visible vertical tonal seam** down the middle.
*Diagnosis:* **§4.3 solved for identity, §4.7 introduced for compositing.** The fix for bleed
creates a blending artifact when the mask crosses featureless background. Figure‑tight masks nested
in existing scene detail (as in `dc1456d8`, 3G) blend cleanly; large plain‑area masks seam.

### 3F. Refinement degradation — `4900c5fe` (shot 5 "unify" pass, pending)
`visual-workflow-img2img` · seed 1746909202 · denoise 0.3 · source `065cfbf0`

*Method:* a low‑denoise (0.3) full‑frame img2img pass to try to dissolve the `065cfbf0` seam.
*Asked vs got:* the **seam remained** and Celeste's **face got rougher** (bluish eyes, greenish skin
patch). The "fix" made it worse.
*Diagnosis:* **§4.7 — chained img2img/inpaint edits are lossy and accumulate error.** A gentle
global pass can't rescue a hard local seam without softening the subject. (Note: this spec's stored
`lora_stack` even lists the **old v1** `celeste-zimage-coraline-turbo` — drafter LoRA contamination,
§4.8 — though the img2img graph has no LoRA slot so it was inert here.)

### 3G. The composite that *did* work — `dc1456d8` (shot 3 inpaint‑composite, **loved**)
`visual-workflow-inpaint-lora` · `celeste-v2@1.0` **only** · seed 2057051159 · denoise 0.9 · source
`6a155414` (narrator base solo)

*Asked vs got:* narrator seated (from the clean base) + Celeste inpainted standing with tray — both
**correct and distinct**, seamless blend (mask sat within existing scene detail). This is the best
two‑shot we produced and the template's proof‑of‑concept.
*Prompt mismatch note:* the composed prose says **"black hair just past shoulders"** while the
appended Celeste canon says **"dark brown curly hair worn up in a voluminous textured bun"** — the
prompt gives the model **two different hairstyles at once** (§4.4). Her outfit is likewise described
two ways ("fitted black button‑up bar uniform shirt, black slacks" vs canon's "black long‑sleeve
collared button‑down shirt with black slim jeans"), which is why her lower garment reads as a long
apron/skirt. Correct identity survived only because Celeste's v2 LoRA is strong.

### 3H. Identity drift — `7de112cb` (shot 4) vs `b7c7d55a` (shot 7), both Celeste solo, **loved**
Both `visual-workflow-lora` · `celeste-v2@1.0` · denoise 1.0 (seeds 643464697 / 4171515329).

*Asked vs got:* both are "good" solo Celestes — but placed side by side they are **not the same
puppet**: face geometry, eye size, hair volume, and skin tone differ (shot 7 skews cool/greyish).
*Diagnosis:* **§4.1 (LoRA encodes a distribution, not one fixed model) + §4.5 (tiny synthetic
dataset).** Each seed samples a different "Celeste‑ish" face. Also note shot 7's greyish skin
despite — or plausibly *because of* — the positive‑prompt negation "NOT gray, NOT ashen" carried in
her canon (§4.3‑prompt): at cfg 1 a negation in the positive text can summon the very token
(the word `ashen` is even stripped mid‑phrase by her own forbid, leaving `"NOT, NOT blue-toned"`).

### 3I. Plastic / CGI look — `a0399398` (QKV calibration, Celeste solo, pending)
`visual-workflow-lora` · `celeste-v2@1.0` · seed 778899 · t2i

*Prompt (full — this one is short and clean, no canon pile‑up):*
> "clstwtrss, a LAIKA stop‑motion Coraline puppet portrait of a young woman, warm cream peach‑ivory
> clay skin with a subtle satin sheen, small round flat black Coraline button eyes, dark brown curly
> hair worn up in a voluminous bun with one long curly strand falling in front of her face, smiling
> warmly, black long‑sleeve collared button‑down shirt, plain neutral light gray studio backdrop,
> soft even studio key light, head‑and‑shoulders front view, finely painted facial details, shallow
> depth of field"

*Asked vs got:* asked for a LAIKA puppet; got a **smooth, waxy, big‑eyed 3D‑render** — competent but
unmistakably CGI, not a photographed miniature.
*Diagnosis:* **§4.2 (distilled Turbo base, cfg 1) + §4.6 (the model's "stop‑motion" prior is
generic‑CGI, and our own "smooth … satin sheen" wording reinforces it).** This is the cleanest proof
that the plastic look is **not** a prompt‑bloat problem — even a short, well‑formed prompt yields
plastic. It's the base model + the "smooth" style target.

### 3J. Set discontinuity — `013e3d9d` · `7de112cb` · `ee3b2587` · `b7c7d55a` (shots 2, 4, 5, 7)
All four inject the **identical ~800‑char "bar interior" canon block**. Yet the TV count/placement,
bar position, window layout, and patron arrangement **change in every shot** — it is a different room
each time.
*Diagnosis:* **§4.4 (canon is text, not a spatial lock) + §4.3 (no depth/lineart/ControlNet to hold
geometry).** Identical text cannot pin identical geometry; the room is re‑improvised every render.
A film cut between any two of these would break the space.

## 4. Defects visible in the prompt text itself (before the model runs)

These are independent of any single image — they degrade *every* multi‑canon generation.

**4.1 Prompt bloat / triple‑description.** Multi‑canon prompts are **3,000–4,800 chars**. Structure
is `[composed prose that already describes everything] + [Celeste canon] + [narrator canon] + [set
canon] + [style canon]`. The **style block appears twice** (prose opener + appended "the style"),
and each character is described **2–3×**. A distilled model at 8 steps has weak prompt adherence to
begin with; drowning the key instruction in repetition makes it weaker.

**4.2 Forbid‑strip mutilates the canon (quotable).** `forbid` is a blunt substring removal applied to
the whole prompt, including the canon text it is meant to protect:
- Celeste locked "clearly NOT gray, **NOT ashen**, NOT blue‑toned" + forbid `ashen` → injected as
  **`"clearly NOT gray, NOT, NOT blue-toned"`** (seen in `9ba816fd`, `dc1456d8`).
- Narrator locked "**clean‑shaven with no facial hair**" + forbid `facial hair` → injected as
  **`"clean-shaven with no,"`** (seen in `9ba816fd`, `4452cf44`).
The model receives ungrammatical fragments where identity cues used to be.

**4.3 Positive‑prompt negations at cfg 1.** With no negative prompt, "don't be gray" lives in the
*positive* text as "NOT gray, NOT ashen". Diffusion frequently renders the negated token; this is a
plausible contributor to Celeste's occasional greyish skin (`b7c7d55a`).

**4.4 Contradictory descriptors in one prompt.** The LLM‑composed prose and the appended canon
disagree — e.g. `dc1456d8`: "black hair just past shoulders" (prose) vs "dark brown curly … bun"
(canon); "bar uniform shirt, black slacks" vs "collared button‑down … slim jeans". The model
averages or picks — hence wardrobe/hair drift.

**4.5 "Smooth" is hard‑coded and tactile cues are forbidden.** Every character/set says "smooth …
clay skin / satin sheen"; "the style" **forbids** "stitched seams" and "visible fabric weave". The
canon is actively steering away from the LAIKA handmade texture (§3I).

**4.6 Drafter LoRA contamination.** The `draft` step repeatedly attaches **old/incorrect LoRAs**
(v1 `celeste-turbo`, `-2500` checkpoints, or even a Celeste LoRA into a narrator‑solo shot). I had to
**normalize every spec's `lora_stack` by hand** before generating. `4900c5fe` still shows the old
`celeste-turbo` in its stored stack. Retrieval surfaces stale assets; the drafter trusts them.

## 5. Diagnosis — mapping evidence to root causes

| Symptom (image) | Immediate cause (prompt/config) | Architectural root cause |
|---|---|---|
| Cross‑bleed / identity collapse (`9ba816fd`, `ee3b2587`) | two LoRAs, whole‑canvas, no regions | **No regional/reference conditioning (§4.3 analysis)** |
| Attribute swap — Celeste in his AJ1s (`0646f23c`) | strength tuning only shifts the winner | same — bleed is structural, not a knob |
| Solo is fine (`4452cf44`) vs two‑shot fails | one LoRA vs two in one frame | isolates cause to multi‑subject conditioning |
| Identity drift shot‑to‑shot (`7de112cb` vs `b7c7d55a`) | seed samples a different face | **Diffusion has no identity lock (§4.1) + tiny synthetic LoRA data (§4.5)** |
| Set changes every shot (`013e3d9d`…`b7c7d55a`) | identical text, no geometry lock | **Canon is text, not spatial (§4.4) + no ControlNet (§4.3)** |
| Plastic/CGI look (`a0399398`) | short clean prompt still plastic | **Distilled Turbo base (§4.2) + generic‑CGI prior + "smooth" wording (§4.6)** |
| Composite seam (`065cfbf0`), degrade (`4900c5fe`) | mask over plain wall; chained edits | **Compositing is a patch for missing regional control (§4.7)** |
| Wardrobe/hair drift (`dc1456d8`) | contradictory prose vs canon | **Text‑only canon, forbid mangling (§4.4/§4.2 above)** |

The through‑line: **the prompt/canon layer has fixable hygiene problems (§4.1–4.6), but the
disqualifying failures — identity drift, cross‑bleed, set discontinuity — are architectural and
cannot be prompted away.** Cleaning the prompts would make the *solo* frames marginally better; it
would not make two‑shots or continuity work. Those need conditioning surfaces the pipeline lacks
(regional prompting, IP‑Adapter/reference identity, ControlNet depth) and/or a non‑distilled base
model. See the companion analysis §6–7 for the research directions.

## 6. TL;DR

- The images fail in three *architectural* ways (identity drift, two‑character cross‑bleed, set
  discontinuity) and one *material* way (plastic CGI look). Proven with `4452cf44` (solo works) vs
  `9ba816fd`/`ee3b2587` (two‑shot collapses), and `0646f23c` (Celeste literally wearing his shoes).
- On top of that, the **prompt assembly is unhealthy**: 3–5k‑char prompts, canon appended 2–3×,
  forbid‑strip producing `"NOT, NOT blue-toned"` and `"clean-shaven with no,"`, positive‑prompt
  negations at cfg 1, contradictory hair/wardrobe, and stale‑LoRA contamination from the drafter.
- The **one thing that worked** was the new single‑LoRA inpaint composite (`dc1456d8`) — render one
  character solo, inpaint the second with only their LoRA. It eliminates cross‑bleed but needs
  figure‑tight masks (plain‑wall masks seam, `065cfbf0`).
- **Cleaning prompts helps solos, not the core failures.** The fixes are: a controllable
  (non‑Turbo) base model, reference‑image identity (IP‑Adapter/InstantID‑class) + a real multi‑view
  identity dataset, regional conditioning for multi‑character, and ControlNet‑depth set plates for
  continuity.

## 7. Reproduction / sources

- **Generation records** (exact prompt, settings, seed, LoRA, source per image): Qdrant collection
  `visual_generation_memory`, `memory_type=generation`, `project=celeste-you-dangerous`
  (458 records). Look up by `asset_path` → `<gen_id>.png`.
- **Canon documents:** `~/agent-data/visual-generation/canon/celeste-you-dangerous.json`.
- **Batch files (the specs + composed prose):** `~/agent-projects/celeste-you-dangerous/visual-batch.md`
  (8‑shot), `~/agent-data/visual-generation/celeste-composite.batch.md` (composite bases + inpaints),
  `…/celeste-v2-qkv.batch.md` (QKV calibration), `…/celeste-v2-verify.batch.md` (identity verify).
- **Images:** `~/agent-data/visual-generation/identity/celeste-you-dangerous/<gen_id>.png`.
- **Visual exhibits:** `~/agent-projects/celeste-you-dangerous/phase-e-PROBLEM-BOARD.png` (annotated)
  and `…/phase-e-final-contact-sheet.png` (the 8 "finals").
- **Companion analysis:** [`coraline-visual-quality-analysis.md`](coraline-visual-quality-analysis.md).

*Gen‑id quick index:* `4452cf44` shot1 narrator solo (loved) · `013e3d9d` shot2 (loved) · `9ba816fd`
shot3 two‑shot (render_failed) · `7de112cb` shot4 Celeste (loved) · `ee3b2587` shot5 two‑shot ·
`b7c7d55a` shot7 Celeste (loved) · `f7202e50` shot8 couch (liked_w_changes) · `0646f23c` shot5
rebalanced · `6a155414`/`f93aebd0` narrator composite bases · `dc1456d8` shot3 composite (loved) ·
`065cfbf0` shot5 composite (seam) · `4900c5fe` unify pass · `a0399398` QKV plastic · `9cb15c83`
identity verify.
