---
title: "z-image-turbo-craft"
document_type: "living-generation-craft-guide"
model: "Tongyi-MAI Z-Image-Turbo"
modality: "image"
status: "active"
version: "1.0.0"
created: "2026-06-26"
last_updated: "2026-06-26"
maintainer: "Chris Bryant"
evidence_scope: "Celeste-you-dangerous project empirical results + official/external Z-Image references"
---

# Z-Image Turbo Craft

## Purpose

This is a living, evidence-based craft guide for **Z-Image Turbo** as used in the `visual-generation` workflow.

It captures:

- the exact recipe proven in this environment;
- prompt language that produced satisfactory or loved results;
- phrases that appeared useful but remained unreliable;
- failures tied to composition, depth, clothing graphics, tiny facial details, and masking;
- the report → context/notes → redraft loop;
- exact redraft patterns that preserved strong generations while changing only requested elements;
- externally sourced best practices kept separate from internal project evidence.

This is not a claim about every Z-Image Turbo implementation. Results are scoped to the project workflow, checkpoint, graph, hardware, and tested compositions described below.

---

# Instructions for a New LLM Chat

## Mandatory reading behavior

When this document is attached or pasted into a new chat:

1. Read it fully before writing a Z-Image Turbo prompt.
2. Treat **LOCKED** items as exact project constraints.
3. Treat **SUPPORTED** items as reusable but not universal.
4. Treat **RISKY** items as warnings, not reasons to block the user’s experiment.
5. Treat **EXTERNAL** items as a counterweight to internal assumptions, not automatic truth for this workflow.
6. Keep internal and external evidence visibly separate.
7. When the user requests a revision:
   - identify the parent generation;
   - list what must remain unchanged;
   - list only the requested changes;
   - preserve the inherited recipe;
   - state any known risk;
   - still produce the requested redraft.
8. Do not steer toward “good enough” because a prior attempt was close. Iteration is additive and does not damage the agent or prevent future retries.
9. Track cost, but never turn cost awareness into an unrequested creative veto.
10. After every generation, move to report/evaluation unless the user explicitly opts out.

## How to use this guide for generation

1. Start with the locked recipe.
2. Pull the exact style, subject, camera, and lighting blocks relevant to the shot.
3. Match requested detail to subject size:
   - tiny hardware-like facial details are more reliable on solo/close subjects;
   - they become risky on smaller, distant, or secondary faces.
4. Put the most important physical construction language inside each character’s own block.
5. Use literal object descriptions for critical details.
6. Use the POV and spatial phrases in this document instead of degree-based rotation commands.
7. Preserve successful staging with `Keep verbatim` and enumerate requested changes.
8. When a local detail repeatedly fails but the frame is otherwise correct, prefer masked inpaint over rerendering the whole composition.
9. Defer clothing graphics and exact logos to compositing unless later tests prove reliable.
10. Report the result and update this document from the observed image, not from the prompt alone.

## How to update this guide

For every completed generation:

1. Add a generation record with the full `gen_id`.
2. Preserve the user’s visual feedback verbatim.
3. Add the final report reaction, rating, context, and notes.
4. Include both:
   - the short redraft/change instruction;
   - the full prompt authored by the redraft.
5. Identify which requested changes landed and which did not.
6. Promote wording only after evidence:
   - **LOCKED:** repeated success, deterministic workflow fact, or explicit user lock;
   - **SUPPORTED:** one clear success;
   - **EXPERIMENTAL:** not yet rendered;
   - **RISKY:** known conditional failure;
   - **FAILED:** clearly failed in the tested case.
7. Keep failed wording so future chats know what not to repeat.
8. Do not promote a prompt claim merely because an LLM reasoned that it should work.
9. Record whether the fix was prompt-level, workflow-level, or post-production.
10. Update the changelog.

---

# Evidence Rules

## Confidence labels

| Label | Meaning in this document |
|---|---|
| **LOCKED** | Verified recipe fact, repeated success, or explicitly approved phrasing/visual result |
| **SUPPORTED** | Worked in a relevant generation, but not sufficiently repeated |
| **EXPERIMENTAL** | Proposed or externally advised; not yet validated here |
| **RISKY** | Known failure tendency under particular framing or workflow conditions |
| **FAILED** | Did not produce the requested visual result |
| **EXTERNAL** | Sourced outside the project |
| **SUPERSEDED** | Earlier guidance retained for history but replaced |

## Evidence priority

1. Current explicit user direction.
2. User-approved loved/keeper generation.
3. Repeated internal results.
4. Single internal result.
5. Official model and implementation guidance.
6. Community prompting guidance.
7. Generic diffusion assumptions.

A risk must be described as a probability, not a certainty. A failed attempt does not corrupt the model, agent, store, or future iterations.

---

# Model and Workflow Identity

## Model

- **Family:** Z-Image
- **Variant:** Z-Image-Turbo
- **Project checkpoint:** `z_image_turbo_bf16.safetensors`
- **Project workflow:** `visual-workflow`
- **Primary task:** text-to-image
- **Refinement workflows:** `visual-workflow-img2img`, `visual-workflow-inpaint`
- **Project precision:** BF16 checkpoint naming indicates bfloat16 use
- **Identity LoRA state in the documented beats:** empty `lora_stack`
- **Planned durable consistency path:** a character LoRA, retained as future work rather than current evidence

## Internal generation loop

```text
draft / redraft → generate → report → update craft evidence → redraft or refine
```

`redraft` is a fresh text-to-image revision that inherits the parent recipe and seed. It is not img2img and must not carry a source image. Local pixel corrections belong to refinement/inpaint.

---

# Locked Recipe

| Parameter | Value | Status | Evidence |
|---|---:|---|---|
| Steps / NFEs | `8` | **LOCKED** | Successful project workflow; aligns with Turbo’s official eight-NFE positioning |
| CFG | `1.0` | **LOCKED for this graph** | Repeated successful project generations |
| Sampler | `res_multistep` | **LOCKED for this graph** | Repeated successful project generations |
| Scheduler | `simple` | **LOCKED for this graph** | Repeated successful project generations |
| Resolution | `1024 × 1024` | **LOCKED** | Confirmed working |
| Resolution `1152 × 896` | Do not use in this workflow | **FAILED** | Model stalled/wedged |
| Seed | `4471` for the documented sequence | **LOCKED per sequence** | Used for continuity across beats |
| Seed strategy | `fixed` | **LOCKED per redraft chain** | Recipe inheritance |
| Negative prompt | None in this graph | **LOCKED for this workflow** | Graph uses `ConditioningZeroOut`; negative content is not an active control |
| Model | `z_image_turbo_bf16.safetensors` | **LOCKED** | Parent recipe inheritance |
| LoRA stack | `[]` in current examples | **LOCKED per current parent** | Must still be inherited to prevent future identity drift |
| Workflow | `visual-workflow` | **LOCKED for text2img redraft** | Prevents accidental img2img routing |

## Recipe preservation checks after redraft

Verify:

```text
Model: z_image_turbo_bf16.safetensors
Seed: 4471 (fixed)
Settings:
  steps: 8
  cfg: 1.0
  sampler: res_multistep
  scheduler: simple
Template: visual-workflow
source: null
revised_from: <full parent gen_id>
lora_stack: inherited
```

## Important seed interpretation

The fixed seed preserves a latent starting point and can support continuity when the recipe and prompt structure remain related. It does **not** guarantee character identity, exact pose, or composition by itself. The parent generation also supplies prior prose, context, notes, and recipe lineage to redraft.

---

# Locked and Reusable Prompt Blocks

## Style and material block

**Status: SUPPORTED / repeatedly retained**

```text
storybook stop-motion anime hybrid still, Coraline-inspired handmade felt and clay texture
```

Associated finish language:

```text
visible fabric texture and slight puppet-like quality to surfaces, storybook illustration depth-of-field, cinematic frame composition, 2D-3D hybrid render style, rich saturated color palette, film grain overlay, short film production still quality
```

### Qualification

The aesthetic block worked for the project’s handmade puppet look. `Coraline-inspired` is useful as a broad style reference, but it was **not sufficient as the only description for exact button-eye construction**.

## Celeste character block

**Status: LOCKED within the documented sequence**

```text
a young woman named Celeste with long black yarn hair just past her shoulders, a bare felt face with no makeup
```

Successful scene additions included:

```text
an intent delighted grin
sitting cross-legged on the floor
a vintage game controller held in both hands
```

## Narrator character block

**Status: LOCKED with variable facial-hair state**

```text
a young African American man with deep caramel-brown felt skin, long black yarn dreadlocks falling to the middle of his back
```

Nail wording:

```text
fingernails painted in alternating black and white, one solid color per whole nail
```

This supersedes ambiguous formulations that allowed white to appear layered over black.

### Facial hair variants

- `a trimmed 5 o'clock shadow tracing the lower half of his face` — used successfully when requested.
- `clean-shaven — remove all facial hair, no beard or shadow` — preferred when no facial hair is desired.
- `thin beard` — **SUPERSEDED** and should not return unless explicitly requested.

## Plain clothing plate wording

**Status: SUPPORTED**

```text
a plain black hoodie with a clear unmarked chest panel
```

More explicit production wording:

```text
a hoodie with a completely clean, unobstructed front
```

Use when graphics or typography will be composited later.

## TV POV and foreground prop wording

**Status: SUPPORTED**

```text
camera positioned from the television's point of view
```

```text
the dark back edge of a low flatscreen television is barely visible along the bottom foreground
```

This concrete foreground object cue was more actionable than merely saying `TV-point-of-view exactly as-is`.

## Cool TV lighting block

**Status: LOCKED for the successful shared-taste look**

```text
dark room illuminated primarily by cool blue television light
```

or:

```text
a soft cool blue screen glow as the key light over a warm amber fill
```

User feedback identified the stronger blue-TV-light version as exactly the desired lighting.

---

# Granular Technique Ledger

## Technique 1 — Use literal spatial staging, not angle arithmetic

- **Status:** LOCKED guidance
- **Unreliable wording:**

```text
rotate the staging scene 75 degrees or -25 degrees
```

- **Preferred wording:**

```text
both characters turned to face the camera/viewer directly
```

- **Reason:** Degree-based rotation does not provide a stable semantic target. Plain visible relationships do.
- **Evidence:** The chat explicitly translated degrees into direct viewer-facing staging.

## Technique 2 — Preserve known-good elements with explicit enumeration

- **Status:** LOCKED redraft practice
- **Working pattern:**

```text
Keep verbatim: the staging, poses, and framing — [enumerate each preserved element].
```

Then:

```text
Apply only these changes:
1. ...
2. ...
```

- **Why it works:** It separates preserved evidence from changed variables and limits prompt drift.
- **Caution:** A near-total restage is at the edge of redraft’s lane. It may still be used for recipe inheritance and reauthoring, but it is no longer a surgical change.

## Technique 3 — Repeat critical eye construction per character

- **Status:** SUPPORTED as a better prompt strategy; not proven reliable
- **Preferred structure:**

```text
Celeste's eyes: two round glossy black sewing buttons physically stitched onto her felt face with visible black thread, no white sclera, no pupils, no irises.

The narrator's eyes: two round glossy black sewing buttons physically stitched onto his felt face with visible black thread, no white sclera, no pupils, no irises.
```

- **Do not reduce to:**

```text
matching eyes
same style
both have button eyes
round black button eyes stitched in the Coraline style to match hers
```

- **Why:** Shared or merged descriptors were associated with one subject losing the intended eye construction.
- **Qualification:** Prompt repetition improves odds; it does not reliably overcome small subject size and depth.

## Technique 4 — Describe the object, not only the reference

- **Status:** SUPPORTED
- **Weak shorthand:**

```text
Coraline-style button eyes
```

- **Stronger physical construction:**

```text
two round glossy black sewing buttons physically stitched onto the felt face with visible black thread
```

Optional additional detail to test:

```text
four button holes
```

- **Positive construction should lead.**
- Because this project graph does not use conventional negative conditioning, exclusions such as `no white sclera, no pupils, no irises` belong in the main prose only when clarification is needed.

## Technique 5 — Do not blur away the detail you need

- **Status:** LOCKED warning
- **Failed/risky wording:**

```text
defocused and blurred in soft bokeh
```

when the same subject must retain tiny readable eye hardware.

- **Preferred wording:**

```text
body softly defocused, face still readable
```

or:

```text
soften only his body and surroundings — his face stays readable and his black button eyes clearly visible
```

- **Observed limitation:** Even this may fail when the secondary character remains small and distant.

## Technique 6 — Match fine detail to frame size

- **Status:** LOCKED empirical limitation
- **More reliable case:** solo or close character render.
- **Risky case:** two characters facing forward, especially at different depths.
- **Observed behavior:** Button eyes rendered on the near character but simplified into generic/cartoon eyes on the smaller background character; a prior face-forward two-shot dropped them on both.
- **Implication:** Prompt wording is not the only cause. Pixel allocation and composition priority matter.

## Technique 7 — Use masked eye inpaint as the reliable correction

- **Status:** LOCKED mitigation
- **Use when:** Composition, pose, wardrobe, and lighting are correct but a small face detail repeatedly fails.
- **Why:** It allocates the edit to the failed region rather than asking a fresh full-frame generation to resolve every competing requirement again.
- **Policy:** One prompt-level retry is reasonable; repeated prompt-only retries remain valid experimentation but are not the most reliable production path.

## Technique 8 — Mask only the intended region

- **Status:** LOCKED workflow practice
- **Screen lesson:** Mask the screen glass inset inside the bezel.
- **Failure:** Masking the frame/bezel allowed the model to reinterpret the whole prop and produce a framed poster instead of a lit screen.
- **General rule:** Use a tight region-only mask; do not include surrounding construction unless it should change.
- **Documented denoise:** Masked inpaint tolerated approximately `0.8` because the rest of the frame remained protected.

## Technique 9 — Separate staging passes from fine-detail passes

- **Status:** SUPPORTED workflow discipline
- **Pattern:**
  1. Land composition, pose, camera, wardrobe, and lighting.
  2. Report the keeper base.
  3. Correct tiny local failures with inpaint.
- **Benefit:** Avoids losing an otherwise loved frame while chasing one small feature.

## Technique 10 — Defer exact logos and text

- **Status:** LOCKED production policy for this project
- **Observed problem:** Text, logos, and clothing graphics garbled in diffusion.
- **Generation wording:**

```text
plain hoodie with a clear unmarked chest panel
```

- **Post-production:** Composite Coraline / Nightmare Before Christmas graphics and exact text in DaVinci Resolve.
- **External qualification:** Official Z-Image materials advertise strong English/Chinese text rendering, so this project result should be treated as workflow-, scale-, and scene-specific rather than universal inability.

## Technique 11 — Strong lighting needs environmental support

- **Status:** SUPPORTED
- **Successful wording:**

```text
Make the room darker so the cool blue glow from the TV reads more strongly on both characters.
```

- **Outcome:** User reported the lighting as perfect and exactly desired.
- **Keep:** Dominant cool blue TV light, dark room, restrained warm fill.

## Technique 12 — Clothing and prop specificity

- **Status:** SUPPORTED
- **Successful requests:**

```text
The man wears a WHITE hoodie; Celeste wears a BLACK hoodie.
```

```text
red and white high-top basketball sneakers
```

```text
each fingernail is one solid color, either solid black or solid white
```

- **Why:** Explicit per-object color assignment reduced blending and attribute ambiguity.

---

# Composition Ledger

| Composition | Internal outcome | Status |
|---|---|---|
| Solo/close face | Button eyes reliable in loved anchor | **SUPPORTED** |
| Two-person face-forward shot | Small face details dropped on one or both characters | **RISKY** |
| Foreground subject sharp, background subject blurred | Foreground eyes held; background eyes simplified | **RISKY** |
| Foreground Celeste cross-legged, narrator behind cheering | Staging eventually reached a loved keeper | **LOCKED keeper composition** |
| Narrator farther back near couch, jumping with one hand raised | User rated final staging ★5 | **LOCKED keeper composition** |
| TV POV with back edge visible low in frame | Successfully sold the POV | **SUPPORTED** |
| Degree-based rotation instruction | Replaced as unreliable | **FAILED wording** |

## Keeper staging block

```text
Celeste sits cross-legged in the sharp foreground, facing the camera head-on and holding a vintage game controller. The narrator is farther behind Celeste near the couch, jumping with one hand raised and cheering. The dark back edge of a low flatscreen television is barely visible along the bottom foreground.
```

Preserve this when revising only wardrobe, eyes, or post-processing details.

---

# Button-Eye Failure Analysis

## What happened

Across the documented iterations:

- solo/near Celeste could retain black button eyes;
- the secondary, smaller, farther character often received generic round cartoon eyes;
- a face-forward two-shot could lose the intended button construction on both faces;
- adding `button eyes clearly visible` was not sufficient;
- `matching eyes` or a shared descriptor block was too easy for the authored prompt or image model to compress;
- blur language conflicted directly with the demand for tiny eye detail.

## Current best interpretation

The failure likely combines:

1. multi-subject composition priority;
2. smaller face size in the far plane;
3. requested blur/defocus;
4. tiny high-specificity facial hardware;
5. a distilled few-step model allocating detail to the dominant foreground face;
6. prompt compression or attribute merging.

This is empirical project reasoning, not an official diagnosis from the model developers.

## Prompt-level mitigation

```text
HIGHEST PRIORITY CHANGE — eyes: give EACH character their own full eye description, stated separately, do not merge them.
```

Then repeat the full physical eye description inside each character block.

## Workflow-level mitigation

Use a tight masked inpaint on the failed eye region after the composition becomes a keeper.

## Do not overclaim

The explicit eye prompt is better wording. It is **not a guarantee**. Opus or Sonnet can improve how the instruction is authored, but the same Z-Image Turbo checkpoint performs the render.

---

# Redraft Operating Rules

## What redraft preserves

A proper redraft inherits in code:

- seed;
- settings;
- workflow reference;
- model;
- LoRA stack;
- width and height.

It records `revised_from` and leaves `source` as `None`, so generation remains fresh text-to-image rather than img2img.

## Redraft is best for

- targeted staging changes;
- wardrobe/color changes;
- facial-hair changes;
- lighting language;
- camera wording;
- preserving a known-good parent recipe.

## Edge case: near-total restage

A full restage can still use redraft to inherit the parent recipe and lineage, but it conflicts with the ideal `apply only one targeted change` design. Mark such uses explicitly:

```text
Using redraft for recipe inheritance + prompt reauthoring, not a surgical edit.
```

## Exact successful redraft pattern

```text
Keep the staging, poses, framing, and TV-point-of-view exactly as-is: [enumerated keeper description]. Apply only these changes: 1) ... 2) ... Keep both locked descriptor blocks otherwise verbatim.
```

## Improved eye-specific redraft pattern

```text
Keep verbatim: [keeper staging, poses, framing, wardrobe, lighting, expressions, hair, and material construction].

HIGHEST PRIORITY CHANGE — eyes: give EACH character their own full eye description, stated separately, do not merge them.

Celeste's eyes: two round glossy black sewing buttons physically stitched onto her felt face with visible black thread, no white sclera, no pupils, no irises.

The narrator's eyes: two round glossy black sewing buttons physically stitched onto his felt face with visible black thread, no white sclera, no pupils, no irises.

Keep the narrator farther back but soften only his body and surroundings — his face stays readable and his black button eyes clearly visible, not blurred away.
```

---

# Reporting Protocol

## Default

Report every generated image unless the user explicitly says not to.

## Rating scale

| Rating | Reaction | Project meaning |
|---:|---|---|
| 5 | loved | Keeper; requested staging/look landed |
| 4 | loved or liked_with_changes | Strong image; isolated changes remain |
| 3 | liked_with_changes | Good direction; substantial changes remain |
| 2 | disliked-ish | Mostly off |
| 1 | disliked | Wrong direction |
| N/A | render_failed | Technical failure; no aesthetic judgment |

## Field definitions

- **`--context`**: why the result worked or did not; future craft memory.
- **`--notes`**: what should change next; intended input to the next redraft.
- **`--reaction`**: categorical judgment.
- **`--rating`**: numeric strength.

## Best reporting pattern

Context should preserve successful evidence:

```text
Staging is exactly right: [specific keeper details]. [Lighting, wardrobe, expressions, identity] all landed. Keeper base.
```

Notes should isolate remaining defects:

```text
1) [specific defect and planned post-production or prompt fix].
2) [specific defect and exact next-step wording].
```

Do not place successful attributes only in notes. They belong in context so future drafts know what to retain.

---

# Internal Results Summary

## Loved anchor: bar meeting

- **Generation:** `ed49b68c-856e-4ee4-b746-f5acd6c8a673`
- **Reaction:** loved
- **Rating:** 5
- **Use:** Proven solo/close identity and button-eye anchor.
- **Lesson:** Near, prominent facial construction is more reliable.

## Disliked shared-taste parent

- **Generation:** `42b2bcaa-2e18-432d-80d5-cb02cebbd857`
- **Reaction:** disliked
- **Rating:** 1
- **Problem:** Face-forward two-shot; button eyes dropped; staging required redesign.
- **Use:** Negative retrieval evidence and restage parent.
- **Important:** A disliked report does not poison the project. It remains one similarity-ranked negative example.

## Successful restage prompt result

- **Redraft spec:** `0401296f-4856-44cf-ac11-78d50ddc4865`
- **Parent:** `42b2bcaa-2e18-432d-80d5-cb02cebbd857`
- **Recipe:** Correctly inherited.
- **What landed:** Celeste sharp foreground, narrator blurred behind cheering, TV POV, blue key/warm fill, plain hoodie plates, 5 o’clock shadow, nails.
- **What remained risky:** Background subject’s button eyes.

## Six-fix redraft

- **Parent generation:** `612675b2-9ec7-4b75-bffa-780afd465cef`
- **Preserved:** staging, poses, framing, POV, expressions.
- **Changes:**
  1. narrator white hoodie;
  2. Celeste black hoodie;
  3. clean chest panels/no plastic drawstring tips;
  4. narrator clean-shaven;
  5. alternating solid-color nails;
  6. red/white high-top basketball sneakers;
  7. darker room/stronger blue TV light.
- **User result:** Lighting, shoes, sweater color, hair, expressions, and consistency were praised.
- **Remaining issue:** Characters stayed in old positions; background defocus and couch placement did not land.

## Final keeper staging

- **Generation:** `2c2c912e-22c3-4feb-8c7b-b276dcdbcc2d`
- **Reaction:** loved
- **Rating:** 5
- **What landed:**
  - Celeste head-on in sharp foreground;
  - controller;
  - narrator mid-jump with one hand raised;
  - couch placement;
  - TV back-edge low in foreground;
  - white narrator hoodie;
  - red/white high-top sneakers;
  - black Celeste hoodie;
  - dominant cool blue TV glow;
  - consistent hair and joyful expressions.
- **Open defects:**
  - background not blurred enough;
  - narrator eyes were cartoon-round rather than stitched buttons.
- **Decision:**
  - background blur can be completed in DaVinci;
  - one prompt-only eye retry, then masked inpaint if needed.

---

# What Worked

## Recipe and workflow

- `1024×1024`
- `8` steps
- `cfg 1.0`
- `res_multistep`
- `simple`
- fixed seed `4471`
- inherited parent recipe during redraft
- scratch batch inspection before touching the real batch
- reporting every render

## Visual language

- handmade felt/clay puppet material
- yarn hair/dreadlocks
- literal TV POV
- visible TV back edge low in foreground
- dominant cool blue television light
- darkened room
- explicit per-character wardrobe colors
- explicit sneaker color/type
- exact spatial verbs: sits, stands, jumps, near couch, farther behind
- one solid nail color per whole nail
- clean unobstructed hoodie fronts

## Process

- keep successful elements verbatim;
- enumerate only requested changes;
- use full generation UUID;
- inspect authored redraft prompt before GPU;
- preserve failures as evidence;
- treat iteration as safe and additive;
- separate staging success from local-detail correction.

---

# What Did Not Work or Was Not Reliable

## Settings/workflow failures

- `1152×896` stalled the workflow.
- Broad screen masks including bezel/frame changed the prop instead of the screen.
- Conventional negative-prompt assumptions do not apply to the project graph.

## Prompt/composition failures

- `rotate 75 degrees` / `-25 degrees`
- `TV-point-of-view exactly as-is` without concrete camera and foreground-object language
- `defocused and blurred in soft bokeh` while demanding readable tiny eye detail
- shared `matching eyes` language
- `Coraline-style button eyes` as the sole physical eye instruction
- two face-forward characters with tiny exact eye hardware
- expecting distance alone to protect the second character’s button eyes
- assuming stronger prompt wording guarantees recovery
- expecting a more capable prompt-authoring LLM to change the image model’s fundamental detail allocation

## Production failures

- exact hoodie graphics and logos were not trusted to diffusion;
- background blur remained insufficient even in a loved keeper;
- button-eye hardware on a distant secondary face remained unreliable.

---

# External Best Practices and Counter-Evidence

## Official model positioning

The official Hugging Face model card and Tongyi-MAI repository describe Z-Image-Turbo as:

- a 6B-parameter distilled model;
- designed for only eight NFEs;
- capable of fitting within approximately 16 GB VRAM;
- strong at photorealistic generation, bilingual English/Chinese text rendering, and instruction adherence.

**Relationship to internal evidence:**  
This confirms the eight-step design and strong prompt-following expectation. It qualifies the project’s text/logo failures: those failures may come from the stylized felt scene, small clothing areas, exact branded graphics, or the custom ComfyUI graph—not a universal lack of text capability.

Sources:

- Official model card: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- Official repository: https://github.com/Tongyi-MAI/Z-Image

## Negative prompt behavior

An early prompting discussion in the official model community states that the few-step distilled Turbo model does not rely on classifier-free guidance and does not use negative prompts conventionally.

**Relationship to internal evidence:**  
This agrees with the project graph’s `ConditioningZeroOut` behavior. The internal conclusion is workflow-specific: use positive visual construction in the main prompt.

Source:

- https://huggingface.co/Tongyi-MAI/Z-Image-Turbo/discussions/8

## Official ComfyUI example

ComfyUI’s documentation provides a Z-Image-Turbo workflow and describes the S3-DiT architecture and model components.

**Relationship to internal evidence:**  
Useful for validating model components and a standard workflow baseline. It does not directly validate the project’s custom sampler/scheduler combination or button-eye findings.

Source:

- https://docs.comfy.org/tutorials/image/z-image/z-image-turbo

## Official scheduler guidance

A Tongyi-MAI GitHub issue discussing recommended settings points to the model’s default scheduler configuration and notes that Euler works well.

**Relationship to internal evidence:**  
This is a useful counterpoint. The project’s `res_multistep` + `simple` combination is internally proven and should remain locked for continuity, but it should not be presented as the only valid Z-Image Turbo configuration.

Source:

- https://github.com/Tongyi-MAI/Z-Image/issues/11

## External/internal contradiction table

| Topic | Internal evidence | External evidence | Resolution |
|---|---|---|---|
| Steps | 8 works and is locked | Official Turbo target is 8 NFEs | Confirmed |
| Negative prompt | Graph zeroes negative conditioning | Official community guidance says Turbo does not use conventional negative prompts | Confirmed for current workflow |
| Text/logos | Clothing graphics garbled | Official model advertises strong English/Chinese text rendering | Treat failure as scene/workflow/scale-specific |
| Scheduler | `res_multistep` + `simple` proven internally | Official issue suggests default scheduler/Euler works well | Keep internal recipe for continuity; test alternatives separately |
| Button-eye dropout | Repeated internal failure in multi-character depth | No official source found diagnosing this exact behavior | Keep as empirical project evidence only |
| Inpaint | Tight masks worked internally | General edit/inpaint principles support local correction | Retain as internal validated practice |

---

# Recommended Prompt Architecture

```text
[Highest-priority concrete correction]

[Medium/style construction]

[Camera and foreground object]

[Celeste: full identity, full eye construction, pose, wardrobe, expression]

[Narrator: full identity, full eye construction, pose, wardrobe, expression]

[Exact spatial relationship and depth; qualify blur so face remains readable]

[Dominant cool blue TV lighting + room darkness + optional warm fill]

[Environment and couch]

[Material texture, cinematic finish, production-still language]

[Explicit preserved elements]
```

## Do not allow the LLM to compress this

For any tiny identity-critical attribute:

```text
Repeat the complete requirement separately inside each character description. Do not replace it with “matching,” “same style,” “both,” or merged shorthand.
```

---

# Wan 2.2 Adaptation Notes

The general template is ready for Wan 2.2, but the future video document must add motion-specific evidence:

- duration;
- FPS;
- frame count;
- resolution;
- motion strength;
- camera motion;
- temporal consistency;
- first/last-frame conditioning;
- image-to-video source;
- prompt timing;
- action phases;
- subject deformation;
- motion artifacts;
- looping;
- seed behavior across clips;
- shot transition strategy;
- audio or lip-sync if applicable.

Do not copy image-only conclusions into Wan 2.2 without testing. In particular:

- a phrase that fixes a still pose may cause temporal stiffness;
- depth of field can change across frames;
- small facial features may flicker instead of simply disappearing;
- `keep verbatim` must include motion, timing, and camera trajectory;
- report fields should distinguish first-frame quality, motion quality, temporal consistency, and ending-frame quality.

---

# New Generation Record Template

## Generation `[full gen_id]`

- **Date:**
- **Parent / revised from:**
- **Spec ID:**
- **Asset:**
- **Model:**
- **Workflow:**
- **Seed:**
- **Settings:**
- **LoRA stack:**
- **Prompt:**
- **Reaction:**
- **Rating:**
- **User feedback, verbatim:**
- **Context:**
- **Notes:**
- **Requested changes:**
- **Redraft instruction:**
- **Authored redraft prompt:**
- **What landed:**
- **What failed:**
- **Phrase promotions:**
- **Phrase demotions:**
- **Next action:**
- **Post-production debt:**

---

# Open Experiments

## Experiment 1 — Explicit physical button construction

- **Status:** Awaiting outcome or later record
- **Parent:** `2c2c912e-22c3-4feb-8c7b-b276dcdbcc2d`
- **Change:** Separate physical eye construction inside both character blocks.
- **Prompt author:** Opus selected for sharper prose.
- **Important control:** Same Z-Image Turbo render model.
- **Success:** Both characters receive physically stitched glossy black buttons.
- **Partial success:** Foreground eyes correct; background eyes still generic.
- **Failure:** One or both faces retain human/cartoon eyes.
- **Fallback:** Masked eye inpaint.

## Experiment 2 — Mild body defocus with readable face

- **Question:** Can the background body and room be softened while preserving face hardware?
- **Changed wording:** `body softly defocused, face still readable`.
- **Risk:** Subject remains too small for exact eye detail.
- **Fallback:** DaVinci background blur + masked eye inpaint.

## Experiment 3 — External scheduler baseline

- **Question:** Does the official/default Euler-oriented setup improve detail or harm the locked project look?
- **Rule:** Use a separate batch and seed comparison; do not replace the locked recipe from one result.
- **Metrics:** identity, button-eye detail, style retention, composition, runtime.

---

# Post-Production Ledger

| Element | Reason deferred | Tool | Current instruction |
|---|---|---|---|
| Hoodie graphics / logos | Exact graphics garbled or uncertain | DaVinci Resolve | Generate clean chest panels, composite later |
| Stronger background blur | Generation did not sufficiently defocus | DaVinci Resolve | Preserve readable face if eye detail matters |
| Tiny narrator eye correction | Repeated prompt-level failure risk | Inpaint | Tight mask over eyes/face only |
| Exact screen content | Screen/prop reinterpretation risk | Inpaint/composite | Mask glass only, preserve bezel |

---

# Changelog

## 2026-06-26 — v1.0.0

- Created the Z-Image Turbo evidence document.
- Added locked project recipe.
- Added exact style, character, POV, lighting, wardrobe, and eye phrases.
- Added granular failure conditions and mitigations.
- Added report/redraft workflow instructions for new LLM chats.
- Added official and implementation references.
- Added a contradiction table so internal experience does not become an unchallenged assumption.
- Added Wan 2.2 adaptation requirements.
