# visual-generation — ComfyUI workflow graphs

Reference ComfyUI graphs (API format) for the visual-generation agent. These are the
graphs `visual-generation workflow register <file>` consumes to build a reusable
template + slot map. They are version-controlled here because they are durable agent
assets, not throwaway outputs.

**Scope note (2026-06-19):** WAN video is set up at the *pod/ComfyUI* level — these
graphs run manually in ComfyUI today. Driving them through the agent CLI is **Phase 2**
(not yet built). See `docs/handoffs/visual-generation-video-phase1-handoff.md`.

## Graphs

| File | Purpose | Captured | ComfyUI |
|---|---|---|---|
| `wan2.2-t2v-14B-lightx2v-api.json` | WAN 2.2 14B **text-to-video** | 2026-06-19 | 0.17.2 |
| `wan2.2-i2v-14B-lightx2v-api.json` | WAN 2.2 14B **image-to-video** | 2026-06-19 | 0.17.2 |

Captured from the ComfyUI default WAN 2.2 14B templates on the RunPod pod
(RTX PRO 6000 Blackwell, 96 GB, US-NE-1), exported in **API format**.

### `wan2.2-t2v-14B-lightx2v-api.json`

Required models (all under `ComfyUI/models/`): `diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors`,
`diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors`,
`text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `vae/wan_2.1_vae.safetensors`,
`loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors`,
`loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors`.

Recipe (lightx2v 4-step, baked in): two-expert MoE split across two `KSamplerAdvanced`
passes — high-noise `start 0 → end 2`, low-noise `2 → 4`; `cfg 1.0`, `euler` / `simple`,
`shift 5.0`; LoRAs at strength 1.0; `EmptyHunyuanLatentVideo` 832×480, length 33,
`CreateVideo` fps 16.

### `wan2.2-i2v-14B-lightx2v-api.json`

Required models: the `i2v` high/low experts + the **`i2v`** lightx2v LoRAs (`_v1_`,
distinct from the t2v `_v1.1_`), same encoder + VAE. Adds a `LoadImage` (seed frame) →
`WanImageToVideo` node (the seed-frame path; outputs positive/negative/latent).

**Dual recipe via a toggle:** a `PrimitiveBoolean` "Enable 4steps LoRA?" drives
`ComfySwitchNode`s that route steps/cfg/split_step/model between two presets:

| | 4-step (LoRA ON) | 20-step (LoRA OFF) |
|---|---|---|
| steps | 4 | 20 |
| cfg | 1.0 | 3.5 |
| boundary (split_step) | 2 | 10 |
| sampler / scheduler | euler / simple | euler / simple |
| shift | 5.0 | 5.0 |

So one registered graph covers both the fast path and the higher-quality 20-step path —
flip the boolean. Full slot maps for both graphs are in
`docs/handoffs/visual-generation-video-phase1-research-signals.md`.

## What these JSONs do and don't contain

- **Do:** the node graph, model/LoRA/VAE/encoder filenames, all sampler/latent/fps
  settings, prompts as they were at export.
- **Don't:** provenance (date, pod, ComfyUI version), "is this the working baseline,"
  or any model *weights* (just filenames — the weights live on the pod volume). That
  provenance is what this README and the research-signals doc carry.

## Preserving and updating

- **Always export in API format**, never the UI "Save" format — only API format
  registers (`workflow register` infers the slot map from flat `node_id → {class_type,
  inputs}`; the Save format breaks inference). See the package README §"Save vs Export".
- **If you change a graph in ComfyUI** (rewire nodes, swap models, change the recipe):
  re-export API format, **replace the file here**, bump the "Captured" date above, and
  re-run `workflow register <file>` so the agent's stored template + slot map match.
  `workflow register` is replace-by-name (idempotent), so re-registering overwrites.
- **Versioning** is git: commit each change with a message noting what changed and why.
  If you need to keep an old recipe alongside a new one, copy to a new filename
  (e.g. `wan2.2-i2v-14B-lightx2v-api.v2.json`) rather than overwriting, and note it here.
- **Editing a refinement/spec recipe at generate time** does *not* require re-exporting
  the graph — the `vg-spec` settings override the baked-in values via the slot map. Only
  re-export when the graph's *structure* changes.
