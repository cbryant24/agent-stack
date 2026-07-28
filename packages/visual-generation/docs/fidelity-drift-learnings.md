# Character & Style Fidelity — Models, LoRAs, Drift: everything we've learned

> **Scope.** A single, comprehensive account of *why it is hard to make a generative model
> render the specific character / setting / style we want*, every failure mode we hit, and —
> for each — the cause, the fix, or an honest "couldn't solve, here's why." Written 2026-07-13,
> consolidating the felt→Coraline pivot, the two character-LoRA builds, the model-shift bake-off
> (Qwen-Edit / FLUX.2), and the Celeste redesign. Living doc — append, don't rewrite.
>
> **How to read it.** §1 is the mental model (two ways to inject identity). §2 is the models.
> §3 is the drift taxonomy — the heart of the doc. §4–6 are training, prompt/canon craft, and
> RunPod ops. §7 is the honest list of what we *couldn't* make work and why.
>
> Companion docs: [`character-lora-plan.md`](character-lora-plan.md) (the original LoRA build +
> operational gotchas), [`z-image-turbo-craft.md`](z-image-turbo-craft.md) (locked recipe +
> technique ledger), [`canon-guide.md`](canon-guide.md) (code-enforced identity locks),
> [`../../..//docs/visual-generation-known-issues.md`](../../../docs/visual-generation-known-issues.md).

---

## 1. The core problem, and the two ways to inject identity

A base diffusion model has a strong **prior** — its own idea of "a young woman," "a stop-motion
puppet," "button eyes." Getting *our* specific character/setting means **fighting that prior**, and
the prior fights back. Everything in this doc is a special case of that tug-of-war. There are only
two levers for injecting a specific identity, and they fail in *opposite* ways:

| Lever | How identity enters | Dominant signal | Fails toward |
|---|---|---|---|
| **A. Character LoRA** | fine-tuned weights, triggered by a rare token (`clstwtrss`, `chrsnrtr`) | the *token* (+ training data) | over/under-application, identity bleed, memorized backgrounds |
| **B. Reference-edit** (img2img / Qwen-Edit) | pixels of a reference image | the *reference image* | reference attributes override the prompt |

**The single most important lesson:** these are not interchangeable. LoRA wants **pose/angle
variety and a consistent face across many frames**; reference-edit wants **few, clean references**
because the reference *dominates*. Pick the lever first; the whole workflow follows from it.

- **LoRA** is right when you need many shots of the same character in *new* poses/scenes with one
  cheap, promptable identity. Cost: a training run + the risk the LoRA bakes in things you didn't
  want (background, wardrobe, an averaged/blurry face).
- **Reference-edit** is right for a one-off restyle of an existing image where you already have a
  clean source. Cost: the reference's every attribute (skin tone, eye type, hair, framing) leaks
  into the output whether you asked for it or not.

---

## 2. The models, and the recipe each one actually needs

Training memory is unreliable for all of these (Z-Image and Wan post-date it; always consult the
model cards / craft guide, never recall). What we run:

### Z-Image-Turbo — text-to-image (the built path)
- **Locked recipe:** `steps 8, cfg 1.0, sampler res_multistep, scheduler simple, 1024×1024`.
  (`z-image-turbo-craft.md` is canonical.)
- **`1152×896` wedges the model** — it stalls. Render 1024×1024. This is a hard, repeatable trap.
- **cfg≈1** means the model barely listens to classifier-free guidance — prompt adherence is
  weaker than a cfg-7 model, so *staging* must be described as subject state, not camera geometry
  (see §5).
- Note the design docs originally said "Flux (stills) / WAN (video)", but the built stills path is
  **Z-Image-Turbo** — a different recipe. Don't trust the old design language.

### Z-Image-Base vs Z-Image-Turbo for LoRA *training* — the biggest single gotcha
- A LoRA **trained on Z-Image-Base under-applies on Z-Image-Turbo**: it only registers around
  **strength 2.0+**, and at 2.0 it *overrides prompt adherence* (pose/staging/background ignored)
  **and bleeds identity onto other figures** (background extras clone the character).
- **Fix:** train the LoRA on **Z-Image-Turbo + the Ostris `zimage_turbo_training_adapter`**
  (a de-distill "assistant LoRA" attached during training). Then it applies cleanly near **1.0**.
- This is why our current files are named `*-coraline-turbo` and why the redesign
  (`celeste-zimage-coraline-v2`) trains on Turbo, not Base.

### Qwen-Image-Edit 2511 — reference-edit (bake-off candidate)
- Identity comes from up to 3 reference images (`image1/2/3`), *not* a LoRA. img1 is also the latent
  base (`LoadImage → FluxKontextImageScale → VAEEncode`).
- Recipe: `ModelSamplingAuraFlow(shift 3.1) → CFGNorm(1.0) → KSampler(euler/simple, cfg 2.5, 30
  steps, denoise 1.0)`.
- **The reference dominates the text.** Gray skin, human eyes, bun hair, realistic face in the
  reference *override* prompt instructions to the contrary. This is the defining property and the
  source of most reference-edit pain (§3.2).

### FLUX.2 — reference-edit (bake-off candidate)
- In the bake-off, FLUX.2 produced the **best scene/background** but a **low-quality, pixelated
  Celeste face**. Verdict from that round: good for environments, weak for our character faces.

### Wan 2.2 — video (t2v/i2v, 14B fp8)
- Workflow JSON lives in `workflows/`. Not exercised deeply in the fidelity work yet; consult the
  ComfyUI Wan tutorial for pipeline/settings and the HF card for prompting.

---

## 3. The drift taxonomy — every fidelity failure, cause → fix / couldn't-fix

This is the heart of the doc. Each entry: **symptom → why it happens → what worked / what didn't.**

### 3.1 Style baked in at four layers (the felt→Coraline pivot)
- **Symptom:** every draft came out hand-felt (fabric weave, stitched seams) when we wanted smooth
  LAIKA clay, even after rewriting the prompt.
- **Why:** the felt look wasn't a prompt — it was baked at **four independent layers**: (1) both
  LoRAs were *trained* on felt frames with felt captions; (2) canon locked text said "felt skin",
  "felt-and-clay set"; (3) taste-memory priors (LOVED felt gens) steered every draft's style
  preamble; (4) per-prompt style vocabulary. Changing one layer leaves the other three pulling back.
- **Fix:** attack all four — **retrain** the LoRAs on restyled data, **rewrite** canon text,
  add a **deterministic style channel** (`canon set … --alias "the style"`, forced into every draft
  via `--canon "the style"`) to bypass the stale taste priors, and a new per-prompt style block.
  **Lesson:** a persistent look you can't prompt away is baked at a layer you're not editing —
  enumerate all four layers before concluding "the prompt is wrong."

### 3.2 Reference dominance (reference-edit)
- **Symptom:** Qwen-Edit ignored "button eyes / cream skin / puppet" and reproduced the reference
  photo's human eyes, real skin, realistic face.
- **Why:** in reference-edit the init image *is* the identity signal; text is a weak modifier at
  denoise 1.0 with the reference re-injected as image1/2/3.
- **Fix that worked:** **composite the attribute you need into the reference itself** — we pre-painted
  real black button photos onto a Celeste reference (`celeste-btn-anchor.png`) so the *pixels*, not
  the text, carried the buttons. **Lesson:** to change an attribute in reference-edit, change the
  *reference*, not the prompt.
- **Corollary:** fewer, cleaner references (2–4) beat a large noisy set — noise in the refs
  corrupts every output.

### 3.3 Button eyes — the recurring nemesis
- **Symptom:** flat black 4-hole Coraline buttons come out as human eyes, big glossy Pixar eyes, or
  mangled sockets.
- **Why:** "button eyes" is a weak text token against a strong "eyes = human/cartoon eyes" prior,
  especially in img2img where the source has real eyes.
- **What worked:** (a) **masked eye-inpaint** — mask *only* the glass/eye region (never the
  surrounding socket/frame), denoise ~0.85, re-run; the untouched surroundings keep it coherent.
  (b) **Backs-to-camera staging** sidesteps it (no faces to resolve). (c) **ChatGPT produced clean
  buttons directly** when we couldn't — see §3.6.
- **What didn't:** chained img2img (buttons degrade each pass); plain text at denoise ≤0.7 (never
  forms buttons); tiny eye-region inpaints on *full-body* frames (mangles the whole small face —
  2 failures). **Lesson:** button eyes are a *pixel* problem — solve them with masks/composites at
  face scale, not with words.

### 3.4 Real-photo → puppet conversion (Option B, this session — a clean failure)
- **Goal:** anchor Celeste's *true* facial geometry by converting her real photos into the puppet
  domain (Z-Turbo img2img, denoise ~0.7) and adding them to the LoRA dataset.
- **Result:** generic **Pixar-child** puppets — no button eyes, lost her likeness, hair went auburn,
  outfit became a plain dress. Actively worse than useless (would poison the dataset).
- **Why it's unsolvable in this pipeline:** there is **no good denoise**. High enough to read as a
  puppet (≥0.7) and the model repaints her face into its generic-cute prior; low enough to keep her
  face (≤0.5) and it keeps *human* eyes + real skin (the contamination we're avoiding). Z-Turbo
  img2img cannot do "real woman → LAIKA puppet with *her* likeness + buttons" in one pass.
- **Decision:** abandoned Option B; trained the LoRA on the ChatGPT frames alone. **Lesson:** img2img
  restyle preserves *composition*, not *identity* at high denoise — it is a style tool, not a
  likeness tool.

### 3.5 Idealization vs faithful likeness (the geometry gap)
- **Observation:** ChatGPT's on-design Celeste is **prettier and younger** than the real person —
  smaller/upturned nose (real: prominent, straight), rounder face (real: longer, more angular),
  softer jaw. It's a character *inspired by* her, not a portrait.
- **Why acceptable:** the director explicitly asked for "prettier, not lanky." Idealization *was*
  the brief. **Lesson:** decide up front whether you want *likeness* (train on real/consistent
  captures of the actual person) or *an approved idealized design* (train on the approved renders) —
  they are different goals and our pipeline can't give faithful likeness with button eyes anyway.

### 3.6 When the external tool wins: ChatGPT for the hero set
- **What happened:** after days fighting button eyes + likeness on the pod, **ChatGPT produced a
  full, on-design, correctly-button-eyed Celeste set directly** (multiple poses). We curated 11,
  captioned them, and used them as the LoRA dataset.
- **Lesson:** the pipeline isn't the only tool. When a general model nails the *design target*
  cheaply, it becomes valid dataset/reference input — provenance doesn't matter to a LoRA, only
  pixel quality and consistency.

### 3.7 LoRA over/under-application & stacking
- **Under-apply:** Base-trained LoRA on Turbo needs 2.0+ (see §2) → **retrain on Turbo**.
- **Over-apply / bleed:** at high strength the LoRA overrides pose/staging and clones the character
  onto background figures.
- **Stacking two LoRAs for the *same* character** (e.g. a checkpoint + a -2500 alternate) **muddies
  likeness and worsens bleed.** **Fix:** pin exactly **one** LoRA per character in canon; let canon
  (not the drafter) own which file + strength represents a character.
- **Silent QKV load failure** is the top LoRA risk — Z-Image stores fused QKV attention; a LoRA can
  *appear* loaded but do nothing. **Guard:** fixed-seed A/B at strength 0.05 vs 2.0 must differ
  night-and-day; if identical, the LoRA isn't really loading.

### 3.8 Hair color / style drift
- **Color:** to force brown→black, **pre-darken the brown pixels in code** (PIL hue-select
  `0.92·R−B>5` within a head region, multiply ×0.12) *then* whole-frame img2img at 0.80. A
  **masked hair-ring inpaint erases the hair mass** (0-for-3 — retired).
- **Style:** curl→sleek needs *straight-lean* language ("falls straight from the crown, wave at the
  ends"); "loosely wavy" loses to the curl prior.

### 3.9 Wardrobe recolor
- White/cream garment → black: **pre-darken the region ×0.25 + WHOLE-FRAME img2img 0.80.** A masked
  inpaint color-blocks into a flat gray box (the model can't infer folds from a flat fill).

### 3.10 Adding a missing feature / removing an unwanted one
- **Missing feature (e.g. a nose):** whole-frame img2img ~0.72 with the feature **named explicitly**.
- **Unwanted printed detail (controller buttons, ghost imprints):** **paint it out in code**, then a
  **low-denoise 0.45–0.55 blend** (1–2 passes converge). Don't try to inpaint-remove at high denoise.

### 3.11 Props degrade under local edits (the controller saga)
- **Symptom:** ~12 chained img2img/inpaint attempts to fix a game-controller all failed (slabs,
  giants, wrong orientation).
- **Why:** props render *correctly* in a whole-scene text2img (the model composes them holistically)
  but **degrade under chained local edits**.
- **Fix:** **re-roll the whole shot fresh as t2i** and scavenge the good frame — don't surgically
  edit a prop. **Lesson:** when a prop is wrong, regenerate the scene, don't operate on the prop.

### 3.12 Forbids self-clip (canon mechanics)
- `canon` forbids are a **raw substring strip** — they can strip their *own* canon text (e.g. a
  "no blush" forbid removing the word from the locked description). Use multi-word phrases
  (`felt texture`, never bare `felt`, which mangles "heartfelt"), and **verify the injected prompt
  after editing** and hand-repair.

---

## 4. LoRA training — the recipe and the operational gotchas

### Recipe (proven twice; step-1500 checkpoint won both times)
- **Base:** Z-Image-**Turbo** + `ostris/zimage_turbo_training_adapter` (so it applies ~1.0).
- **Network:** LoRA rank 8 (`linear 8 / alpha 8`), conv 16.
- **Train:** LR 5e-5, batch 2, 3000-step cap, save every 250, `flowmatch`, `adamw8bit`, bf16,
  qfloat8 quantization + `low_vram` (fits a 24 GB card comfortably, ~15 GB used, ~3.2 s/it on a 4090).
- **Datasets:** 512/768/1024 buckets, `flip_x: true`, caption dropout 0.05.
- **Trigger tokens:** `clstwtrss` (Celeste), `chrsnrtr` (narrator) — identity lives in the *token*.

### Captioning discipline (what makes identity promptable)
- **Constant identity uncaptioned** (face, eyes, skin, hair) → the token learns it.
- **Variables captioned** (view, framing, pose, expression, wardrobe, setting) → they stay promptable
  and don't fuse into identity. Mixing wardrobes (button-down vs shorts) *helps* disentangle clothing
  from identity — but only if every frame's wardrobe is captioned.
- **Consistency > count.** A dozen frames with a stable face beat twenty where the face wobbles
  (ChatGPT frames drift per-generation — cull outliers). Curate for angle variety
  (~front / rear / ¾ / profile); poses are promptable, so you don't need pose *coverage*, you need
  *angle* coverage and identity consistency.
- **Cull elongated frames** — a stretched crop teaches the lanky proportion you're trying to fix.
- **Watch scene-bleed:** if most frames share one background, the LoRA absorbs it; caption the
  background so it stays promptable, or favor plain-background frames.

### Operational gotchas (RunPod / ai-toolkit) — see also `character-lora-plan.md §Operational`
- **Deploy the TEMPLATE, never the bare image — both pods.** A bare `--image` pod boots with a GPU
  but never binds its port/SSH (`runtime`/`portMappings` null; training → SSH "pod not ready"
  forever; inference → 404 on :8188). Training template: **`LORAS_TEMPLATE_ID=0fqzfjy6f3`** (Ostris
  "AI Toolkit - ui - official"); inference: `TEMPLATE_ID=cnne9dp3rt`. `lora-train` now prefers
  `LORAS_TEMPLATE_ID` (the two collide otherwise). With the right template, SSH is up ~2 min after
  RUNNING.
- **RunPod DNS is broken on boot** → HF downloads fail with a misleading `httpx "client has been
  closed"`. Fix `resolv.conf` first (`lora-train dns`), always.
- **`training_folder: /mnt/output`** — the container disk is **wiped** on pod cycle; only the
  network volume (`/mnt`) survives. We nearly lost checkpoints this way.
- **The ai-toolkit UI queue wedges** ("queued" forever). Bypass the UI: write the YAML and
  `nohup python run.py <yaml>` directly; the Queue row stays "queued" but the CLI run is real.
  (We now `scp` a pre-patched YAML straight to `/mnt/configs/` and skip the wizard entirely.)
- **`scp` needs the direct-TCP SSH** (`root@<ip> -p <port>`, `-P` capital, add `-O` if "subsystem
  request failed") — the `ssh.runpod.io` proxy has no SFTP subsystem.
- **EU-RO-1 capacity is frequently exhausted across *all* GPU types.** The training volume is
  region-locked to EU-RO-1, so you can't switch regions — **poll `up` across a GPU list** until one
  frees. A 4090 (24 GB) trains this fine.
- **Lifecycle is create/delete ONLY** — never `pod start`/`stop` (a stopped pod's host GPUs are gone
  by resume), never any `runpodctl network-volume` subcommand. Kill the pod the instant training
  drains.

---

## 5. Prompt & canon craft (Z-Image-Turbo specifics)
- **Literal spatial staging, not camera arithmetic.** cfg≈1 means the model won't do "camera angle"
  math. Describe *subject orientation* (`rear view`, `from behind`, `facing the stage`), prefer
  "image perspective" over "camera." Backs-to-viewer also dodges button-eye dropout.
- **Preserve known-good elements by explicit enumeration** — when refining, re-state the parts you
  want kept; the model drops unmentioned detail.
- **Repeat critical eye construction per character** in multi-character frames.
- **Describe the object, not only the reference** — naming the thing beats gesturing at a ref.
- **Don't blur away the detail you need**, and **match fine detail to frame size** (buttons on a
  full-body frame are too small to resolve — hence face-scale inpaint).
- **Canon = deterministic identity.** `--canon "<alias>"` force-injects locked text + strips forbids;
  use it when the model refers to a subject by other words. Keep one LoRA pinned per character in
  canon. Don't lock a redesign into canon until a render is director-approved.

---

## 6. Character bootstrap (getting a consistent set to exist at all)
- A brand-new character has **no consistent reference set** — you can't train or reference-edit until
  one exists. Bootstrap it: generate a small consistent set (fresh t2i, or an external model like
  ChatGPT that hits the design), curate the most on-model frames, *then* train/reference from those.
- Real photos of a real person stay **local** — used only as img2img/reference sources on our own
  pod, never uploaded to external services.

---

## 7. What we could NOT solve, and why (honest ledger)
1. **Faithful real likeness + button eyes together.** Z-Turbo img2img can't restyle a real photo into
   a LAIKA puppet while keeping the actual person's geometry *and* forming buttons — no denoise value
   satisfies both (§3.4). Worked around by accepting an idealized ChatGPT design (§3.5).
2. **Button eyes from text alone.** Never reliably formed from the token; always needed a mask,
   composite, or an external model that draws them (§3.3).
3. **Surgical prop edits.** Chained local edits degrade props; the only reliable fix is a fresh full
   re-roll (§3.11).
4. **Masked hair-mass edits.** Ring-masking hair erases it; only whole-frame code-predark + img2img
   works (§3.8).
5. **Base-trained LoRA on Turbo at usable strength.** Only registers at 2.0+ where it overrides
   everything; not fixable by strength tuning — must retrain on Turbo (§2, §3.7).

---

## 8. One-line heuristics (the compressed version)
- Persistent look you can't prompt away → it's baked at a *different layer* (LoRA / canon / taste /
  vocab). Fix that layer.
- Need an attribute the prompt keeps losing → put it in the *pixels* (composite / mask / predark),
  not the words.
- img2img preserves **composition, not identity** at high denoise. It's a style tool.
- LoRA wants **angle variety + consistent face + captioned variables**; reference-edit wants **few
  clean refs**. Never mix the two philosophies.
- Train character LoRAs on **Turbo**, pin **one** per character, and A/B **0.05 vs 2.0** to prove it
  loaded.
- Props/settings render best **whole-scene t2i**; don't surgically edit them — re-roll.
- Deploy the **template**, never the bare image; `training_folder` on `/mnt`; poll for GPU capacity.
