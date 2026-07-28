# Coraline / LAIKA visual quality — comprehensive problem analysis

**Author:** Claude (Opus 4.8), from my own perspective after producing the Phase‑E
`celeste-you-dangerous` batch.
**Date:** 2026‑07‑14.
**Status:** honest post‑mortem / research briefing. This is not a to‑do list — it is my
best understanding of *why the output is disappointing* and *what would actually move the
needle*, written so the director can do deep external research from an informed starting point.

> **Bottom line up front.** The current pipeline (Z‑Image‑Turbo text‑to‑image + per‑character
> LoRAs + text‑only "canon" injection, run at 8 steps / cfg 1) can produce *individually pretty*
> frames, but it structurally **cannot deliver what a stop‑motion film needs**: the *same*
> character, in the *same* set, in a *consistent authentic LAIKA material*, across many shots,
> with controlled composition and reliable multi‑character staging. The disappointment is not a
> prompt‑tuning problem or a single bad render. It is the sum of several *architectural* limits
> stacking on top of each other. Below I separate the **symptoms** (§3) from the **root causes**
> (§4), then lay out **what to research** (§6) with honest trade‑offs.

---

## 1. What we are actually trying to make

A set of production stills (and eventually motion) for *celeste‑you‑dangerous* that look like
authentic **LAIKA stop‑motion** — the *Coraline* / *ParaNorman* / *Kubo* look:

- Hand‑sculpted puppets with **real material presence**: clay/resin/silicone skin with subtle
  surface imperfection, visible replacement‑face seams, hand‑painted micro‑detail, real fabric
  garments with true weave, fine sculpted hair strands.
- **Two specific, recurring characters** — Celeste (button eyes, curly hair up in a bun with a
  front strand, black button‑down + jeans + white‑soled sneakers) and the narrator (Black man,
  mid‑back dreadlocks, distressed black long‑sleeve, AJ1s) — who must be **recognizably the same
  puppet in every shot**.
- **Recurring sets** (the sports bar exterior/interior, the couch/living room) that must have
  **spatial continuity** shot‑to‑shot.
- Cinematic, motivated, high‑contrast **theatrical lighting**, shallow depth of field, anamorphic
  framing, gentle film grain — a *photographed miniature*, not a render.

That target is unusually demanding. It requires **identity consistency, set consistency, material
authenticity, and compositional control simultaneously.** Diffusion T2I is weakest at exactly
those four things.

## 2. What the pipeline actually does today

1. **Base model:** Z‑Image‑Turbo (a *distilled/turbo* text‑to‑image model) run at **8 steps,
   cfg ≈ 1.0, `res_multistep`/`simple`, 1024×1024**, no negative prompt (cfg 1 = classifier‑free
   guidance effectively off).
2. **Identity:** one **LoRA per character**, trained on a small synthetic dataset, applied at
   ~1.0 strength. Two characters in one frame = two LoRAs chained (`visual-workflow-lora2`).
3. **"Canon":** a **text descriptor** for each subject is string‑injected into the prompt, plus a
   list of "forbid" substrings that are stripped. Canon also pins which LoRA/strength represents a
   character. **This is text conditioning only — there is no visual/spatial conditioning.**
4. **Refinement:** img2img and inpaint workflows (and, new this session, a single‑LoRA inpaint
   template) for local edits and compositing.

Everything the model knows about "what Celeste looks like" comes from (a) the LoRA weights and
(b) a paragraph of English. There is **no reference image, no pose skeleton, no depth map, no
region mask, no camera control** in the normal generation path.

## 3. The symptoms — what is actually wrong (with evidence from the Phase‑E set)

I am grouping these by *what you see*, worst‑first. Almost every one traces back to a root cause
in §4.

### 3A. It reads as CGI / plastic, not photographed stop‑motion
The frames look like a competent **3D "cute character" render with a stop‑motion filter**, not a
photographed puppet. Skin is too uniformly smooth and slightly waxy; surfaces lack the tactile
micro‑imperfection, replacement‑face seams, dust, fingerprints, and fabric weave that make LAIKA
frames read as *physical objects under a real light*. The "smooth sculpted clay‑resin" language we
locked into canon actively pushes **away** from tactile handmade and **toward** clean CGI. This is
the most fundamental disappointment: even the "good" solo frames are not convincingly *stop‑motion*.

### 3B. Character identity is not locked — it drifts shot to shot
Celeste is not the **same puppet** in shots 3, 4, 5, 7, 8. Her face geometry, eye size/shape, hair
volume, skin tone, and proportions vary noticeably. The narrator drifts worse — his dreadlocks
become braids, his age reads younger or older, his build changes. A LoRA encodes a *distribution*
of "Celeste‑ish" faces, not a single fixed model; every seed/pose/context samples a different point
in that distribution. **For a film this is disqualifying** — the audience needs the same face every
cut. This is the core structural failure, not a tuning miss.

### 3C. Multi‑character frames cross‑bleed
When both LoRAs are active in one frame, attributes **swap between characters**: a seated narrator
collapses into a young braided figure (Celeste's hair prior dominates); when the narrator holds his
dreadlocks, Celeste inherits *his* red/white AJ1 sneakers and sometimes braided buns. Across 8
attempts (strength rebalancing + explicit‑seed sweeps) each frame got **one** character right, never
both. See `fidelity-drift-learnings.md` and the technique lessons recorded in memory.

### 3D. Proportions and anatomy
Figures trend **lanky/elongated** — the exact defect the v2 redesign was meant to fix. Hands are
frequently mangled (fused fingers, wrong count), especially when holding props (tray, shot glass).
Full‑body framings elongate worse than close‑ups.

### 3E. Wardrobe and prop drift
Celeste's outfit is not stable — apron appears/disappears, "jeans" become a long skirt, shoe style
swaps. Props degrade or vanish under editing (the tequila shot glass got painted out during a
composite). The narrator's AJ1s bleed onto Celeste. Wardrobe lives only in the text descriptor, so
it is a *suggestion*, not a lock.

### 3F. Set / background discontinuity
The "sports bar" is a **different room in every shot** — TV count and placement, bar position,
window layout, patron arrangement all change. There is no persistent 3D set, so there is zero
spatial continuity. A film cut between two of these would break the geography instantly.

### 3G. Composite seams and refinement artifacts
The inpaint‑LoRA composite (this session's fix for cross‑bleed — genuinely the best two‑shots we
got) still shows a **visible vertical tonal seam** when the inpaint mask regenerates a large strip
of plain wall. A low‑denoise (0.3) "unify" pass did **not** dissolve a hard seam and mildly degraded
the face. Chained img2img/inpaint edits also progressively **degrade** faces, eyes, and props
(a repeatedly observed pattern — "chained local edits degrade; re‑roll fresh instead").

### 3H. Faces, eyes, and the uncanny middle
Button eyes are inconsistent — sometimes flat four‑hole buttons (correct), sometimes glossy domes,
sizes wander. Faces land in a generic **big‑eyed cartoon** proportion rather than a specific sculpt.
Skin often desaturates toward grey under cool light. Under the button‑eye constraint the faces lose
most acting range, so expression has to come from brow/mouth/pose — which the model renders
crudely.

### 3I. Lighting is often flat or muddy
Amber bar interiors read as evenly‑lit and soft rather than **motivated, high‑contrast, theatrical
key + deep shadow**. cfg 1 and 8 steps give the sampler little room to resolve dramatic contrast and
crisp practical highlights. The images lack the "lit by a gaffer" quality of a LAIKA still.

## 4. Why we are facing these — root causes (my understanding)

This is the important part for your research. The symptoms above are **downstream of six root
causes.** I've ordered them by how much I think they matter.

### 4.1 Diffusion text‑to‑image gives no *identity* or *continuity* guarantee (structural)
A diffusion model samples a plausible image from a text (+LoRA) conditioning. Nothing in the process
*pins* a specific face, a specific set, or a specific composition. LoRAs bias the distribution
toward a character but do **not** collapse it to one exact model — pose, framing, seed, lighting,
and the presence of other subjects all move the sampled identity. **Consistency is not a feature of
this architecture; it is something you have to bolt on** with extra conditioning (reference images,
control maps, or by generating one canonical asset and reusing it). We have bolted on *none* of
that. This single fact explains 3B, 3C, 3E, and 3F.

### 4.2 The base model is a distilled *turbo* model (quality/control ceiling)
Z‑Image‑Turbo is optimized for **speed** (8 steps, cfg 1). Distilled/turbo models generally trade
away: (a) fine detail and texture fidelity, (b) **prompt adherence** (fewer steps + no CFG guidance
= the prompt is a weaker steering signal), and (c) controllability. Running at cfg 1 means **there is
no negative prompt and no guidance scale to push contrast, suppress artifacts, or enforce
instructions.** This directly drives 3A (texture), 3D/3E (adherence to proportions/wardrobe), 3H
(eye/face precision), and 3I (lighting/contrast). A full (non‑distilled) model at 20–40 steps with
real CFG is a categorically different quality tier.

### 4.3 No spatial / regional / reference conditioning (missing tooling)
There is no **ControlNet** (pose/depth/lineart/canny), no **IP‑Adapter / reference‑image
conditioning** (InstantID / PuLID‑style identity), no **regional prompting / attention masking**,
and no camera/composition control anywhere in the pipeline. Consequences:
- **Multi‑character (3C):** with no way to say "*this* region is character A and *that* region is
  character B," both LoRAs paint the whole canvas and bleed into each other. This is expected
  behavior, not a bug we can prompt our way out of.
- **Continuity (3F):** with no depth/lineart lock to a fixed set layout, the room is re‑improvised
  every generation.
- **Composition (general):** we can't reliably specify camera angle, blocking, or eyelines; the plan
  even documents that *spatial direction words are ignored* and we must resort to "scene‑motivated
  staging" tricks. That is a symptom of having no real compositional control surface.

### 4.4 "Canon" is *text*, not *visual*, conditioning (design limit of our stack)
Our identity/continuity mechanism is **string injection + substring forbids**. Text cannot pin a
face or a room. Worse, "forbid" is a blunt substring strip that can mangle its own canon text, and a
paragraph of adjectives competes with the LoRA and the seed rather than overriding them. This is why
wardrobe, hair, and shoes remain *suggestions*. A visually‑grounded canon (reference embeddings /
control maps per subject) would be a different thing entirely; ours is essentially a very elaborate
prompt.

### 4.5 The LoRAs are trained on small, synthetic, single‑source data (garbage‑in)
The character LoRAs were trained on **~11 frames** that were themselves **AI‑generated / img2img‑
converted** (ChatGPT hero images, photo→puppet conversions) — a *copy of a copy*. Problems:
- Too few images and too little viewpoint/lighting variety → the LoRA can't generalize to new poses
  without drifting (3B, 3D).
- Synthetic source means the "identity" is already an approximation with baked‑in inconsistencies
  (e.g., the button eyes themselves varied in the training frames).
- No true multi‑view character sheet (consistent front/¾/profile/back of the *same* sculpt), so the
  model never learned a single coherent 3D identity — only a vibe.
A robust identity LoRA typically wants dozens of *consistent* views of one subject. We trained on a
handful of *inconsistent* synthetic ones.

### 4.6 The style prior fights us, and our own style words point the wrong way
The model's internal prior for "stop‑motion / clay puppet" is dominated by **generic 3D‑render and
Pixar‑ish cute‑character imagery**, not authentic LAIKA. So it defaults to the plastic look (3A).
And our canon deliberately says **"smooth sculpted clay‑resin with a subtle satin sheen"** — which,
in trying to avoid the earlier "felt" era, over‑corrected toward *smooth*, i.e. toward CGI. We are
partly prompting ourselves into the plastic look. Authentic LAIKA is *not* smooth — it's full of
deliberate tactile imperfection.

### 4.7 (Secondary) Editing chains and composites accumulate error
Every img2img/inpaint pass is a lossy re‑encode; chaining them degrades faces, eyes, and props
(3G). The single‑LoRA inpaint composite is the right idea for cross‑bleed, but rectangular masks
over plain areas seam, and low‑denoise unify passes can't fully hide a seam without softening the
subject. Compositing is a patch over 4.3, not a cure.

## 5. Honest assessment of the ceiling

With the **current architecture**, I believe the realistic ceiling is: *nice individual
concept‑art frames*, useful for mood/pitch, **but not a shippable, continuous stop‑motion film
look.** No amount of prompt craft, strength tuning, seed sweeping, or canon text editing will fix
3B/3C/3F, because those are architectural (§4.1, §4.3, §4.4). We have, in effect, already spent
many iterations proving this: the two‑shot cross‑bleed survived 8 targeted attempts; identity
drifts every shot; the set changes every render. Those are the pipeline telling us it lacks the
conditioning surfaces the task requires. **The path forward is adding conditioning and/or changing
the base model — not tuning the current one further.**

## 6. What to research — options, mechanisms, and trade‑offs

Grouped by the problem each addresses. I've flagged what I'd prioritize in §7.

### 6.1 Identity consistency (fixes 3B; helps 3C, 3E)
- **Reference‑image / face‑ID conditioning at inference:** IP‑Adapter, InstantID, PuLID,
  "FaceID," or the model‑native equivalent. These inject a *reference image's identity* into every
  generation, which is far stronger than a LoRA alone for "same face every time." Research whether
  Z‑Image (or a chosen base) has an IP‑Adapter/reference ecosystem; if not, that's a reason to
  switch base.
- **Much better character LoRA / DreamBooth training:** build a **true multi‑view character sheet**
  of *one* consistent sculpt (ideally 30–100+ images, varied pose/light, *not* AI‑copies), higher
  rank, and — critically — **train on the exact model you infer on** (a Turbo‑trained LoRA behaves
  differently from a base‑trained one; we already learned this the hard way).
- **Generate‑once‑then‑reuse:** produce one canonical, director‑approved "hero" render per
  character/expression, then drive all shots by **img2img/reference from that hero** rather than
  re‑sampling identity from scratch. Trades novelty for consistency.
- **Textual inversion / embeddings** as a lighter identity anchor to stack with the above.

### 6.2 Multi‑character staging (fixes 3C)
- **Regional prompting / regional conditioning** (a.k.a. attention couple / latent couple / regional
  IP‑Adapter): assign each character's LoRA/reference to a *masked region* of the canvas so they
  can't bleed. This is the *correct* fix for two‑shots and is standard in ComfyUI ecosystems for
  full models.
- **Our inpaint‑composite (built this session):** render one character solo in‑scene, then inpaint
  the second with only their LoRA. Proven to eliminate bleed, but seams on plain areas and needs
  figure‑tight masks. Keep it as a fallback; regional conditioning is cleaner.
- **True compositing:** render clean solos on a neutral/keyable backdrop, matte, and comp onto a
  plate with matched light and contact shadows. Highest control, most manual, needs matting tools
  (e.g., SAM/rembg‑class segmentation) not currently installed.

### 6.3 Set / spatial continuity (fixes 3F)
- **ControlNet depth/lineart/segmentation locked to a fixed set layout:** build (or render once) a
  canonical set plate, extract a depth/line map, and condition every shot of that location on it so
  the geometry stays put while camera/action change.
- **Build the set once in 3D** (Blender / a simple greybox), render depth/normal passes, and use
  those as ControlNet inputs. This is how you'd get real continuity + camera control.
- **Photobashed/painted master plates** reused across shots via img2img.

### 6.4 Composition & camera control (fixes the "directions are ignored" problem)
- **ControlNet openpose / depth** for blocking and eyelines; **camera‑control LoRAs**; or drive
  composition from a rough 3D previz. This replaces the "scene‑motivated staging" guesswork with
  actual control.

### 6.5 Material authenticity / the LAIKA look (fixes 3A, 3I)
- **Rewrite the style target away from "smooth."** Explicitly ask for tactile imperfection:
  replacement‑face seam lines, silicone/clay surface with pores and fingerprints, real fabric weave,
  dust, subsurface scattering, practical light. Consider a **style LoRA trained on actual LAIKA
  frames** (careful re: rights — for style study, not distribution) to move the prior off generic
  CGI.
- **Move to a base model with better texture fidelity** (see 6.6) and run **real steps + CFG** so
  contrast and micro‑texture can resolve. Add a **film‑look grade** in post (grain, halation, subtle
  anamorphic, contrast) — a lot of "LAIKA feel" is grade/lens, not the puppet.

### 6.6 Base model / architecture (fixes 3A, 3D, 3H, 3I; unlocks 6.1–6.4 tooling)
- **Switch from Turbo to a full, controllable model.** Candidates to evaluate: **FLUX.1/​FLUX.2**
  (strong prompt adherence + rich ControlNet/IP‑Adapter ecosystem), **SDXL** (the deepest ControlNet/
  IP‑Adapter/regional tooling of any open model — best *control surface* even if base fidelity is
  lower), **Qwen‑Image / Qwen‑Image‑Edit** (strong editing/identity), or a **non‑Turbo Z‑Image** if
  one exists. The decisive question for each: *does it have mature ControlNet + IP‑Adapter/reference
  + regional tooling?* That ecosystem matters more than raw single‑image quality, because control is
  our actual bottleneck. Note we already have a bake‑off eval volume with Qwen‑Edit 2511 + FLUX.2
  pre‑downloaded — a natural place to start comparisons.
- **Trade‑off:** full models cost more per image and per training run and are slower — but that is
  the price of the control we lack. Given the film goal, quality/control should win over speed.

### 6.7 Different medium entirely (worth knowing the boundary)
- **Actual stop‑motion / real puppets** (the real thing) — highest fidelity, highest effort.
- **3D CG built to *look* stop‑motion** (Blender + shaders emulating replacement animation; this is
  how a lot of "stop‑motion‑style" content is actually made now) — full continuity/camera control by
  construction, at the cost of a CG pipeline.
- **Video/keyframe models** (Kling, Runway, Wan, etc.) for motion, with image‑to‑video from
  approved keyframes — relevant once stills are solved, and some have better temporal identity
  coherence than frame‑by‑frame T2I.

## 7. What I would prioritize (my opinion)

1. **Decide the base model first (6.6).** Everything else (IP‑Adapter, ControlNet, regional
   prompting) depends on the ecosystem around the base. A distilled Turbo model is the wrong
   foundation for a control‑heavy film pipeline. Run a small bake‑off (we have the eval volume) on:
   texture/LAIKA‑look, prompt adherence, and — most importantly — **available control tooling.**
2. **Add reference‑image identity conditioning (6.1)** — IP‑Adapter/InstantID‑class — and retrain
   character identity on a **real, consistent, multi‑view dataset**. This is the fix for the #1
   disqualifier (identity drift).
3. **Add regional conditioning for two‑shots (6.2)** and **ControlNet‑depth set plates for
   continuity (6.3).** These make multi‑character and recurring‑location shots actually possible.
4. **Re‑aim the style toward tactile imperfection + add a post grade (6.5).** Cheapest win for the
   "it looks like CGI" problem, partially independent of the above.

Items 1–3 are architectural and are where the real gains are. Item 4 is a quick partial improvement
you can test immediately.

## 8. Things I'm uncertain about / worth verifying independently

- **Z‑Image‑Turbo's exact ecosystem** — whether ControlNet/IP‑Adapter/regional tooling exists for it
  today. It post‑dates my training; I've relied on the project's own craft docs for its behavior.
  Verify before investing more in it vs switching.
- **Whether a non‑distilled Z‑Image variant exists** that keeps the look but restores CFG/steps.
- **Current best‑in‑class open identity method** (InstantID vs PuLID vs newer) — this space moves
  fast; check what's state‑of‑the‑art now.
- **Rights posture** for training a style LoRA on real LAIKA frames — fine for private style study,
  but worth being deliberate about.
- My claims about texture/adherence trade‑offs of *distilled* models are well‑established in general;
  the *magnitude* for this specific model is worth measuring in the bake‑off rather than assuming.

## 9. What this session did produce (so it isn't lost)

- A full 8‑shot Phase‑E batch in the v2 canon (solos are the strongest; two‑shots are the weakest).
- A **new reusable `visual-workflow-inpaint-lora` template** — single‑LoRA inpaint that eliminates
  two‑shot cross‑bleed by construction (render one solo in‑scene, inpaint the second with only their
  LoRA). This is the correct stopgap for multi‑character shots until regional conditioning exists.
- Two recorded technique lessons (cross‑bleed cause; inpaint‑LoRA cure + seam caveat) and a wired,
  verified Celeste v2 identity LoRA — see `fidelity-drift-learnings.md`.

None of that changes the §5 conclusion: to reach the LAIKA bar, the work is **adding conditioning
and moving off the Turbo base**, not further tuning the current path.
