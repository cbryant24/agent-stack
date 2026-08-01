# Phase 3A Editor Bake-Off — Session Log

**Session date:** 2026-07-16 · **Session question (Sheet 2):** Which editor stack preserves an
approved hero identity through multi-view derivation and successive edits, and preserves plate
geometry under edit — Qwen-Image-Edit 2511 or FLUX Kontext (+ one plate-depth/edge arm in
Test D)?

## Protocol constants

| Constant | Value |
|---|---|
| Pod | `bakeoff-eval` (`5nbelkahti66hv`), H100 SXM 80GB, US-NE-1, **$2.99/hr** |
| Volume | `qwen-eval` (`7dkrd2v238`, 150GB, US-NE-1) — reused eval volume, never production `gen-usne1` |
| ComfyUI | v0.17.2 on volume (`/workspace/runpod-slim/ComfyUI`), frontend 1.45.19, templates 0.10.7; custom nodes: KJNodes, Manager, + `comfyui_controlnet_aux` (installed this session for DA-v2) |
| Pod URL | https://5nbelkahti66hv-8188.proxy.runpod.net |
| Budget | **$10 cap, warn at $7** (Sheet 2 est. 2–4 pod-hours) |
| Models | Qwen-Image-Edit-2511 **bf16** (`ae42d927…`) + `qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` + 2511 Lightning 4-step bf16 LoRA (**explore-only**); Kontext dev **bf16** (`843a26dc…`, gated BFL repo via user HF token, sha256-verified 16:40 UTC — **precision asymmetry resolved**; fp8_scaled `630ba795…` retained as fallback) + `clip_l` + `t5xxl_fp8_e4m3fn_scaled` + `ae.safetensors`; Depth-Anything-V2-Large; InstantX Qwen ControlNet-Union (**best-effort sub-arm** — trained on base Qwen-Image, unvalidated on 2511) |
| Depth/edge arm | **Qwen-2511 native conditioning**: source → image1, DA-v2 depth map → image2 via `TextEncodeQwenImageEditPlus`, instruction references the map. Fully supported (stock nodes + `comfyui_controlnet_aux`). **Depth-on-Kontext not viable** (no Kontext ControlNet exists as of 2026-07) — Kontext scored on prompt-only edits per Sheet 2. |
| ComfyUI templates | native `image_qwen_image_edit_2511`, `flux_kontext_dev_basic` (+ `image_qwen_image_instantx_controlnet` for the sub-arm) — shipped by this build, no update needed |
| Fixed seeds | *(recorded per attempt series below)* |

**Volume provenance note:** the eval volume carried a Jul 6–10 prior attempt. Deleted to make
room (all public HF re-downloads): `flux2_dev_fp8mixed.safetensors`,
`mistral_3_small_flux2_fp8.safetensors`, `flux2-vae.safetensors` (53.8GB). Kept:
`qwen_image_edit_2511_fp8mixed.safetensors` (explore-only fast arm — cannot enter the hero
gate), `qwen_2.5_vl_7b_fp8_scaled.safetensors`, `qwen_image_vae.safetensors`, old Phase-C
`refsheets/` (superseded, left in place).

## Pod uptime ledger (cost)

| # | Up (UTC) | Down (UTC) | Hours | Cost | Running total |
|---|---|---|---|---|---|
| 1 | 2026-07-16 14:30:49 | 2026-07-16 17:20:15 | 2.82 | $8.44 | **$8.44** |
| 2 | 2026-07-17 06:53:59 (pod `uns1vorgw080gd`) | 2026-07-17 08:59:55 | 2.10 | $6.27 | **$14.71** |
| 3 | 2026-08-01 20:59:02 (pod `76eow9y60xjjis`, **$1.99/hr** — cheaper GPU than either planned) | 2026-08-01 21:04:17 | 0.09 | **$0.17** | **$14.88** |

> Final: **$14.71 total pod spend** vs the original $10 cap (overrun acknowledged in-session:
> day-1 estimates drifted low and $8.44 of day 1 was largely one-time provisioning; day 2 ran
> $6.27 under a declared $8 session cap). Volume storage continues at ~$10.50/mo until the
> volume is retired.

> Uptime 1 covered full provisioning (84GB verified downloads + gated Kontext bf16 + node
> install) **plus** attempts 1–5 — later uptimes are pure generation time. Paused mid-strike-3
> (Celeste child-face defect, brand-token purge queued). Everything persists on the volume:
> models, staged sources, attempt outputs. Volume storage bills separately (~$10.50/mo at 150GB).

## Source staging (lineage: INPUTS)

Staged 2026-07-16 ~15:20 UTC to the pod's ComfyUI input dir (`input/real/`, `input/gen/`);
real photos exist ONLY there and on the unsynced local `~/agent-data` staging — never repo,
vault, or reports.

| Staged file (pod) | Source | Px | Role |
|---|---|---|---|
| `input/real/celeste-real-face-hero.png` | IMG_6048 (real photo) | 3664×4366 | primary face + face-strand |
| `input/real/celeste-real-outfit-fullbody.png` | IMG_6046 (real photo) | 2715×5891 | outfit + shoes + proportions |
| `input/real/celeste-real-hair-bun.png` | IMG_6036 (real photo) | 1772×2504 | bun volume backup |
| `input/gen/narrator-solo-4452cf44.png` | gen `4452cf44-62ed-4e5c-a5d9-aa12ec3e798a` (loved solo render) | 1024×1024 | **back view only** — demoted to back-view reference (Test A); face not visible |
| `input/narrator-walkin-013e3d9d.png` | gen `013e3d9d-522b-425f-a3d4-e56fd8f56383` (Phase-E walk-in, loved, seed 1504812959) | 1024×1024 | **narrator hero source** — front-facing, face held |

**Handoff 15:50 UTC:** all model files sha256-verified against HF manifests (Qwen bf16 + TE +
VAE + Lightning verified first; Kontext/FLUX/depth files verified minutes later — all OK).
Staged inputs at ComfyUI input root: `celeste-real-face-hero.png`,
`celeste-real-outfit-fullbody.png`, `celeste-real-hair-bun.png`, `narrator-solo-4452cf44.png`
(+ prior-session `cel-*.png` downscaled stagings of the same photos, left in place). Native
templates confirmed: `image_qwen_image_edit_2511` (select **bf16** in the loader for gate
candidates — the template defaults to fp8mixed), `flux_kontext_dev_basic`;
`DepthAnythingV2Preprocessor`/`Canny` registered after ComfyUI restart.

## Attempt log

Every attempt: seed · editor · instruction text (or the ONE clause changed) · input lineage ·
output filename · `explore` vs `candidate`. Guardrail 3 strikes tracked per defect.

| # | Time | Editor | Seed | Input (lineage) | Instruction / clause changed | Output file | Label | Result / defect |
|---|---|---|---|---|---|---|---|---|
| 1 | ~16:20 UTC | Qwen 2511 bf16 | 424242 | `narrator-solo-4452cf44.png` (gen `4452cf44`, back view) | Sheet 3 narrator re-stage, verbatim: "Keep this exact stop-motion puppet character unchanged — same face, same caramel-brown clay skin, same mid-back dreadlocks, same black distressed long-sleeve shirt, dark denim jeans, and red-and-white Jordan 1 sneakers. Full-body front view, standing relaxed facing camera, plain neutral studio backdrop, soft even studio key light." | `Qwen_Edit_2511_00001` | candidate | **FAIL — view unchanged** (still back view). Strong scene preservation; background patrons drifted (unmasked). Strike 1: defect "view unchanged". *Series closed: input had no face pixels — input swapped, not a clause change.* |
| 2 | ~17:00 UTC | Qwen 2511 bf16 | 555555 | `narrator-walkin-013e3d9d.png` (gen `013e3d9d`, Phase-E walk-in) | same Sheet 3 instruction, unmodified (new series on face-visible input) | `Qwen_Edit_2511_00003` | candidate | **Staging PASS** (full-body front, studio backdrop). **Identity PARTIAL**: skin lightened, face rounder, dread tips lost. Strike 1: defect "identity drift" (Qwen) |
| 3 | ~17:05 UTC | Kontext bf16 | 555555 | `narrator-walkin-013e3d9d.png` (same input, same instruction — head-to-head) | same Sheet 3 instruction, unmodified | `flux_1_kontext_dev_00001` | candidate | **Identity PARTIAL-GOOD** (skin tone + dreads held). **Staging FAIL**: hybrid background, patrons retained, **white-sclera eyes** (button-eye break). Strike 1: defect "staging incomplete" (Kontext) |
| 4 | ~17:25 UTC | Qwen 2511 bf16 | 111111 | image1 `celeste-real-face-hero.png` + image2 `celeste-real-outfit-fullbody.png` (real photos) | Sheet 3 Celeste conversion, verbatim | `Qwen_Edit_2511_00004_.png` | candidate | **REJECT** — Sheet 1 #1 (generic child face) / #4 (childlike proportions) + blush. Strike 1: defect "child-face/doll pull" (confirmed by director) |
| 5 | ~17:35 UTC | Qwen 2511 bf16 | 111111 | same image1+image2 | +1 clause: adult-woman clause added | `Qwen_Edit_2511_00005` | candidate | **REJECT** — Sheet 1 #1 (face structure reads child) / #4 (proportions) + blush persists. Strike 2. Hypothesis: "Coraline" tokens pull child face + doll blush |
| 6 | 2026-07-17 ~07:2x UTC | Qwen 2511 bf16 | 111111 | same image1+image2 | brand tokens purged both sites ("LAIKA-style stop-motion puppet"; "small round flat black button eyes"); rest identical incl. adult-woman clause | `Qwen_Edit_2511_00006` | candidate | **REJECT** — Sheet 1 #1/#4, blush persists. **Strike 3 → recipe STOPPED (guardrail 3).** Token-pull hypothesis falsified for this defect class |
| 7 | 2026-07-17 ~07:5x UTC | Qwen 2511 bf16 | 111111 | same image1+image2 | **NEW SERIES — two-stage recipe (option B), stage 1**: conversion with pose/view/camera locked (profile in → profile puppet out); no view-change language | `Qwen_Edit_2511_00007` | candidate | **MAJOR PASS on the stopped defect** — adult face, HER facial structure from the photo, no child pull. **Architecture question answered: task decomposition fixes it; invent-the-face was the failure.** Residuals: blush (now prompt-independent — reclassified, see notes), painted-human eye not button (new defect series if pursued at this stage), mannequin articulated hand, slight photo-grain bleed, **face-strand missing** (agent-observed: nape curl only) |
| 8 | 2026-07-17 ~08:4x UTC | Qwen 2511 bf16 | 111111 | image1 `celeste-stage1-00007.png` (= attempt 7 out) + image2 `celeste-real-outfit-fullbody.png` | **two-stage, stage 2 (turn to front)**, verbatim: "Keep this exact stop-motion puppet woman unchanged — same face, same facial structure, same clay material, same bun with loose strands, same black collared button-down shirt. Turn her to face the camera directly: full-body front view, standing relaxed. Replace her eyes with small round flat black button eyes. Remove the blush from her cheeks. Her hands are smooth sculpted clay, not articulated mannequin hands. She wears the full outfit from image 2: black slim jeans, small pendant necklace, black low sneakers with white soles and white ankle socks. Plain neutral studio backdrop, soft even studio key light." (turbo=false — full-quality path, agent-verified template wiring) | `Qwen_Edit_2511_00008` | candidate | **TWO-STAGE RECIPE VALIDATED** — adult front-view puppet; outfit/proportions/hands PASS (articulated-hand defect fixed by spec clause). Face **softened vs stage-1 profile** (turn = partial invention) — director identity call pending. Defects: **button eyes not taking (strike 1, own series — 2nd occurrence cross-recipe)**, faint blush persists (routed to finishing), **face strand lost** (note: strand clause absent from stage-2 instruction — "bun with loose strands" ≠ spec's "one long curly strand falling in front of her face"; instruction gap, not model refusal). Agent-noted: bun reads flatter/less voluminous than spec; output ~944×1104 — **short edge < Sheet-1 criterion 9's 1024 floor** (see notes) |

| 9 | 2026-07-17 ~08:5x UTC | Qwen 2511 bf16 | 111111 | image1 `Qwen_Edit_2511_00008_.png` solo (attempt 8 out) | **two-stage, refinement bundle**, verbatim: "Keep this exact stop-motion puppet woman completely unchanged — same face, same pose, same outfit, same backdrop, same lighting. Make only three changes: replace both eyes with small round flat matte black buttons with four thread holes, like Coraline's button eyes. Remove all pink blush from her cheeks so the skin is even cream. Add one long curly dark brown strand of hair falling down in front of the right side of her face." (turbo=false) | `Qwen_Edit_2511_00009` | candidate | **ALL THREE PASS** — button eyes w/ thread holes, blush removed, strand present; face/pose/outfit/backdrop held. **BANKED as `celeste_hero_draft_v1`.** Pending before formal gate: resolution pass (criterion 9 — still ~944×1104), director identity call, fresh-eyes review |

| 10 | 2026-08-01 21:00–21:03 UTC | Qwen 2511 bf16 | 111111 | image1 `Qwen_Edit_2511_00008_.png` (attempt-8 out) — **same input as attempt 9** | **Resolution pass — ONE variable vs attempt 9:** node `170:160` `FluxKontextImageScale` (parameterless, snapped to ~1MP) replaced with `ImageScale` (lanczos, 1088×1272, aspect held). Prompt byte-identical to attempt 9, seed 111111, turbo=false. Driven over the ComfyUI HTTP API (new operator model), graph diffed against the export: exactly one node changed | `Qwen_Edit_2511_00010` (`attempt-10-…`) | candidate | **Criterion 9 PASS — 1088×1272** (was 944×1104). A3 re-verify of the attempt-9 fixes: button eyes w/ thread holes **held**, blush **absent**, face strand **present** (reads as a thicker cascading section, marginal vs "one long curly strand"). **New regressions vs v1 at the larger latent:** eyebrows lost, skin cooled from warm peach-ivory to pale cream, face longer/flatter and less like her, head-to-body ratio more elongated. Director gate call pending |

## Draft hero record

**`celeste_hero_draft_v1` = `Qwen_Edit_2511_00009`** (attempt 9). Full lineage:
`celeste-real-face-hero.png` (IMG_6048) + `celeste-real-outfit-fullbody.png` (IMG_6046)
→ attempt 7 (stage 1: view-locked photo→puppet conversion, seed 111111)
→ attempt 8 (stage 2: turn to front, + outfit ref, seed 111111)
→ attempt 9 (refinement bundle: eyes/blush/strand, seed 111111).
All full-quality bf16 (turbo off, template-wiring verified). NOT yet gate-approved: needs
criterion-9 resolution pass, director identity call vs the real profile, fresh-eyes Sheet-1
review.

**Validated recipe (the actual Phase-3A product so far):** two-stage + refine —
(1) convert in-pose (never ask for view synthesis and conversion in one edit);
(2) re-stage the puppet;
(3) bundle spec-detail refinements with "make only N changes" framing, naming object
construction, not category ("four thread holes" beat two prior button-eye failures).

## Wall-clock per accepted image (Sheet 2 tie-breaker 3)

| Editor | Accepted images | Total active wall-clock | Per accepted |
|---|---|---|---|
| Qwen 2511 | 3 (attempts 7, 8, 9 — the validated chain) | ~65 min incl. inter-attempt review (07:50–08:55 UTC) | **~22 min** (upper bound; queue time per image was ~1–2 min) |
| Kontext | 0 (attempt 3 partial — not accepted) | ~10 min | n/a |

> Methodology note: wall-clock measured from session timestamps, not queue telemetry — treat
> as upper bounds. Tie-breaker 3 unusable this session anyway: Kontext accepted nothing, and
> the formal Tests A/B1/B2/D were not reached.

## Strike tracker (guardrail 3 — three per defect)

| Defect | Editor | Strikes | Disposition |
|---|---|---|---|
| view unchanged (back→front re-stage) | Qwen 2511 | 1 | closed — input-swap fix (no face pixels in back view), not an instruction defect |
| identity drift (skin tone / face shape / dread tips) | Qwen 2511 | 1 | **paused** (director call ~17:15 UTC — signal captured, Celeste priority). Banked clause fix for resumption: "same face" → "same exact face shape and deep caramel-brown skin tone, unchanged" |
| staging incomplete (hybrid bg, patrons) | Kontext | 1 | **paused** (same call). Banked clause fix: "plain neutral studio backdrop" → "plain neutral studio backdrop, no other people, empty background" |
| **button-eye break (white sclera)** | Kontext | 1 | **open — standing watch item**: white sclera = instant Sheet-1 criterion-2 fail on any candidate; if it recurs on Celeste or resumed narrator work, it strikes independently of the instruction being tested |
| child-face + doll blush (Celeste conversion, Sheet 1 #1/#4 + blush) | Qwen 2511 | 3 | **STOPPED per guardrail 3** (attempts 4/5/6, seed 111111 held). Prompt layer exonerated. **RESOLVED by architecture change** (attempt 7, two-stage recipe): child-face gone when no face geometry is invented |
| blush (Qwen habit) | Qwen 2511 | — | **Reclassified 2026-07-17**: survives every prompt variant incl. brand purge and task decomposition → prompt-independent Qwen rendering habit. **Routed to finishing/local edit (inpaint), not re-rolls.** Not a strike series |
| painted-human eye instead of button (stage-1 output) | Qwen 2511 | 0 | superseded by the live button-eye series below (stage 2 gave the clean read: spec clause present, eyes still not button) |
| **button eyes not taking** | Qwen 2511 | 1 | **CLOSED — resolved at attempt 9**: geometry phrasing beat the cross-editor defect ("small round flat matte black buttons **with four thread holes, like Coraline's button eyes**") — no inpaint needed. Lesson: name the object's construction, not its category |

### Architecture question (guardrail 3, recorded 2026-07-17)

The #1/#4/blush rejection survives prompt-layer changes, so the suspect layers are:
(a) **source/task shape** — a dim profile-ish face photo forces simultaneous profile→front view
synthesis + photo→clay conversion + outfit merge from a second dim photo; the model fills the
*invented* front face from its doll prior; (b) **the editor**. Prompt wording is exonerated for
this defect class.

Next-series candidates (one variable each vs the stopped recipe):
- **A)** ~~swap image1 to a front-facing source~~ — **RULED OUT 2026-07-17**: direct inspection
  of all five staged photos (face-hero, face-profile, hair-bun, outfit-fullbody,
  outfit-profile) found no front-facing face source; all are profile/near-profile in dim bar
  light. Corroborates the task-shape hypothesis: the front face in attempts 4–6 was 100%
  invented. *(Durable fix outside this session: shoot controlled front/¾/profile photos in
  even light — exactly audit §7's "controlled front/profile views" gap, which applies to the
  photo layer too.)*
- **B)** two-stage recipe — stage 1: photo→puppet conversion keeping exact pose/camera
  (profile in, profile puppet out — no invented geometry); stage 2: re-stage the puppet to
  front view as a separate edit (Qwen's proven strength, attempt 2);
- **C)** Kontext fresh series on the same task.

## Gate / scoring events

*(Sheet 1 hero gates and Sheet 2 test scores recorded here as they happen.)*

- No formal Sheet-1 gate was scored this session. `celeste_hero_draft_v1` is **banked, not
  approved** — gate blocked on: criterion-9 resolution pass, director identity call vs the
  real profile (stage-2 turn softened the face — partial invention), fresh-eyes review.
- Sheet-2 Tests A/B1/B2/D: **not reached.** No editor decision can be made yet; Qwen leads on
  progress (validated hero recipe) but Kontext has had only one attempt, and the depth arm and
  InstantX sub-arm never ran.

## Session 1–2 close-out: exports + artifacts

- Workflow API JSONs (export only, NOT registered), from pod `/history` — exact graphs as run:
  `workflows/bakeoff-qwen2511-hero-stage1-convert-api.json` (attempt 7),
  `workflows/bakeoff-qwen2511-hero-stage2-front-api.json` (attempt 8),
  `workflows/bakeoff-qwen2511-hero-refine-api.json` (attempt 9).
- Outputs (lineage-labeled, real-photo sources excluded): `docs/bakeoff/outputs/attempt-0{7,8,9}-OUTPUT-*.png`.
- Draft hero staged for next session: pod `input/celeste-hero-draft-v1.png` (on the volume) +
  local unsynced `~/agent-data/.../refsheets/celeste-v2/hero/celeste-hero-draft-v1-Qwen_Edit_2511_00009.png`.

## Next-session queue

1. **Resolution pass** on `celeste_hero_draft_v1` (criterion 9: short edge ≥1024; current
   ~944×1104) — upscale-in-style or re-run refine with a ≥1024 scale target.
2. **Formal Sheet-1 gate** on the result: director identity call (face softened by the stage-2
   turn — compare against `attempt-07` profile), fresh-eyes review, all 10 criteria scored.
3. **Test A derivations** from the approved hero (5 views per Sheet 2) — Qwen first; the
   attempt-07 profile is a near-free profile-view candidate.
4. **Narrator hero** via the validated two-stage recipe (re-stage series paused at strike 1
   both editors; banked clause fixes in strike tracker).
5. **Kontext continuation** — needs its own hero attempt (two-stage recipe) for any Sheet-2
   decision; button-eye construction phrasing now known to transfer.
6. **Depth/edge arm** (never ran) — required by Test D before a Phase-3A verdict.
7. **Controlled photo shoot** (front/¾/profile, even light) — the durable source fix; removes
   the invention step for all future derivations. No pod needed.
