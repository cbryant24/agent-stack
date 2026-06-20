# Research signals — visual-generation video / WAN 2.2 (Phase 1 → Phase 2)

Between-phase knowledge gathering for the video fast-follow. This picks up exactly
where the stills research-signals doc left it: *"WAN 2.2 ComfyUI workflow — the
T2V/I2V/VACE graphs and the high/low-noise split … unseeded and will need
tutorial-research when video work begins"* and *"I2V input handling (`/upload/image`)
and keyframe selection — surfaces with video."*

The stills course (*Diffusion Mastery*) does **not** cover WAN — it mentions WAN only
in passing and teaches different video tools (LivePortrait, Animate Anyone, Deforum)
plus Google Veo3. So WAN-via-ComfyUI is a genuine cold gap. Two arms: **`tutorial-
research` delegations** (the primary route, since there's no course doc to ingest) and
**manual doc ingest** of the canonical WAN/ComfyUI pages.

Phase 2 opens against a knowledge base with these gaps closed. Gathering happens
between phases — Phase 1 only identifies the signals.

---

## The load-bearing gap: WAN recipe ranges for the sanity check

BP1's thin sanity check needs **concrete valid ranges** to flag a bad recipe before
spending. These are the highest-priority facts to land in `user_knowledge`
(`domain=comfyui_mechanics`, or a dedicated `wan_mechanics` if preferred). Capture, per
WAN 2.2 14B:

- cfg range (and the I2V vs T2V difference, if any)
- steps range and the **boundary/split step** convention (where high-noise hands to
  low-noise) + per-stage step counts
- shift typical value/range
- sampler/scheduler pairing recommended for WAN
- supported/known-good resolutions and frame counts (the stills work already hit a
  resolution-hang failure mode — capture WAN's known-good resolutions explicitly)
- fps convention

Without these the sanity check is ungrounded. They are facts, so the doc-ingest /
`fact add` path is the right home (not just tutorial transcripts).

---

## Arm 1 — `tutorial-research` delegations (run now, pre-seed `tutorial_research`)

`tutorial-research` already exists; these can run before Phase 2. Match the exact
subcommand/flags to your CLI.

```bash
# WAN 2.2 in ComfyUI: the native T2V workflow, the MoE high/low-noise two-model split
tutorial-research "WAN 2.2 ComfyUI text to video workflow high noise low noise model"

# WAN 2.2 image-to-video: the I2V graph, seed/init frame via LoadImage, settings
tutorial-research "WAN 2.2 ComfyUI image to video I2V workflow init frame setup"

# WAN settings semantics for the sanity-check ranges (cfg/steps/shift/boundary/fps)
tutorial-research "WAN 2.2 settings cfg steps shift boundary frames recommended"
```

---

## Arm 2 — manual doc ingest (deterministic, complements Arm 1)

These export cleanly to markdown; stage them (flatten to one folder of `.md`, strip
MDX/JSX, re-add frontmatter `title:` as a top-level `##`, add a `url:` line) and run
`knowledge ingest-docs` with `domain=comfyui_mechanics` under `op run`, `--dry-run`
first. (See the visual-generation README troubleshooting note on `fact ingest-docs`
parsing.)

- ComfyUI's official WAN 2.2 workflow page (`docs.comfy.org/tutorials/video/wan/wan2_2`)
  — the canonical native T2V/I2V graph reference.
- The Wan-Video/Wan2.2 model card / GitHub README — the authoritative source for the
  MoE split, model variants (14B vs 5B), and resolution/length limits.

---

## Deferred research (not for video v1)

- **VACE graphs** — the third WAN mode; gather when VACE is picked up.
- **WAN LoRA training** — v1 is LoRA use-only; training research travels with the
  deferred ai-toolkit subsystem.
- **Stitching / long-clip techniques** — WAN clips are ~5s; multi-clip continuity is
  out of v1 scope.

---

## CAPTURED — WAN 2.2 14B T2V baseline (2026-06-19, verified working on the pod)

First T2V clip generated successfully on the RTX PRO 6000 pod. The template used is the
ComfyUI default **"Wan 2.2 14B Text to Video"**, which now ships **with the lightx2v
4-step speed LoRAs baked in** — so this baseline is the *accelerated* recipe, not the
plain ~20-step one. Exported API graph saved at
`workflows/wan2.2-t2v-14B-lightx2v-api.json` (the registration artifact for
`workflow register`).

**Recipe (lightx2v 4-step path):**

- Two-expert MoE split across two `KSamplerAdvanced` passes: high-noise expert runs
  `start_at_step 0 → end_at_step 2` (add_noise enable, return_with_leftover_noise
  enable); low-noise expert runs `2 → 4` (add_noise disable, return_with_leftover_noise
  disable). Nominal `steps = 4`, **boundary at step 2**.
- `cfg = 1.0`, `sampler = euler`, `scheduler = simple` (both passes).
- `shift = 5.0` (two `ModelSamplingSD3` nodes, one per expert).
- Both `lightx2v_4steps` LoRAs at `strength_model = 1.0`.
- Latent: `EmptyHunyuanLatentVideo`, 832×480, `length 33` (4n+1 rule), batch 1.
- Output: `CreateVideo` at `fps 16` → `SaveVideo`.
- Text encoder: `umt5_xxl_fp8_e4m3fn_scaled` (the template's default; the fp16 we also
  have is interchangeable).

**Sanity-check implication (BP1):** the valid recipe ranges are **conditional on the
LoRA stack**. The lightx2v path wants `cfg≈1, steps≈4, boundary≈2`; a *standard*
(no-LoRA) WAN run would want `cfg≈3–5, steps≈20, boundary≈10`. So the WAN sanity check
must key its expected ranges off whether the lightx2v LoRAs are present, not a single
fixed WAN range. Capture the standard ranges too if/when a non-accelerated clip is run.

**Slot map (from the exported graph — for Phase 2 `workflow register`):**

| Spec field | Node id . input |
|---|---|
| high-noise model | `75.unet_name` |
| low-noise model | `76.unet_name` |
| text encoder | `71.clip_name` |
| vae | `73.vae_name` |
| high LoRA (+ strength) | `83.lora_name` (`83.strength_model`) |
| low LoRA (+ strength) | `85.lora_name` (`85.strength_model`) |
| shift | `82.shift` + `86.shift` |
| width / height / length | `74` |
| positive prompt | `89.text` |
| negative prompt | `72.text` |
| high-noise sampler (pass 1) | `81` (seed, steps, cfg, sampler, scheduler, start=0, end=2) |
| low-noise sampler (pass 2) | `78` (steps, cfg, sampler, scheduler, start=2, end=4) |
| fps | `88.fps` |
| output | `80` (SaveVideo) |

## CAPTURED — WAN 2.2 14B I2V baseline (2026-06-19, verified working on the pod)

First I2V clip generated successfully (seed = a prior z-image still, `starter.png`).
Exported API graph saved at `workflows/wan2.2-i2v-14B-lightx2v-api.json`.

**Important — the I2V template encodes BOTH recipes behind a toggle.** A
`PrimitiveBoolean` "Enable 4steps LoRA?" (node `129:131`) drives `ComfySwitchNode`s that
route steps / cfg / split_step / model between two presets. So one registered graph does
both the fast and quality paths by flipping one boolean:

| | 4-step (LoRA ON, `switch=true`) | 20-step (LoRA OFF, `switch=false`) |
|---|---|---|
| steps | 4 | 20 |
| cfg | 1.0 | 3.5 |
| boundary (split_step) | 2 | 10 |
| sampler / scheduler | euler / simple | euler / simple |
| shift | 5.0 | 5.0 |
| model path | i2v experts + lightx2v LoRAs | i2v experts, no LoRA |

This **closes the standard 20-step recipe gap** too (steps 20, cfg 3.5, boundary 10) and
is the director's preferred quality path — available without a different graph, just the
toggle. It also confirms the BP1 sanity-check design: ranges are conditional on the LoRA
stack, and here the graph itself exposes which preset is active.

**I2V-specific structure (vs T2V):**

- `WanImageToVideo` (node `129:98`) replaces the empty-latent node: takes `start_image`
  (from `LoadImage` `97`) + width/height/length and outputs positive/negative/latent.
  This is the seed-frame path — the I2V analog of the img2img source.
- Two `KSamplerAdvanced` (`129:86` high: start 0 → end split_step, add_noise enable;
  `129:85` low: start split_step → end steps, add_noise disable) — same two-expert split.
- Latent params on this run: 512×512, length 33, fps 16 (`CreateVideo` `129:94`).

**Slot map (from the exported graph — for Phase 2 `workflow register`):**

| Spec field | Node id . input |
|---|---|
| seed image | `97.image` (LoadImage) |
| width / height / length | `129:98` (WanImageToVideo) |
| high-noise model | `129:95.unet_name` |
| low-noise model | `129:96.unet_name` |
| high LoRA / low LoRA | `129:101.lora_name` / `129:102.lora_name` |
| text encoder | `129:84.clip_name` |
| vae | `129:90.vae_name` |
| shift | `129:103.shift` + `129:104.shift` |
| positive / negative prompt | `129:93.text` / `129:89.text` |
| seed | `129:86.noise_seed` |
| steps (4 vs 20) | `129:118` / `129:128` (via switch `129:119`) |
| cfg (1 vs 3.5) | `129:122` / `129:126` (via switch `129:120`) |
| boundary (2 vs 10) | `129:124` / `129:127` (via switch `129:125`) |
| 4-step toggle | `129:131.value` (bool) |
| fps | `129:94.fps` |
| output | `108` (SaveVideo) |

**Slot-map note for Phase 2:** the switch-node indirection means the agent should write
steps/cfg/boundary to the *active* preset's PrimitiveInt/Float nodes (or set the toggle
and the matching preset), not directly onto the samplers — the samplers read those values
through the switches. Simpler alternative when registering: set `129:131` and the one
preset you intend to use, and treat the other preset as fixed.

Both T2V and I2V baselines are now captured; the between-phase research/setup is complete.
