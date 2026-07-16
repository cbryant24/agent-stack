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
| `wan2.2-flf2v-14B-lightx2v-api.json` | WAN 2.2 14B **first-last-frame** video | 2026-07-09 (derived, validated) | 0.17.2 |

### `wan2.2-flf2v-14B-lightx2v-api.json` — provenance + status

**Constructed, not browser-exported.** Derived deterministically from the committed
`wan2.2-i2v-14B-lightx2v-api.json` by the single change the native FLF2V template makes over
I2V: swap `WanImageToVideo` → **`WanFirstLastFrameToVideo`** and add a second `LoadImage`
feeding its **`end_image`** input (I2V's `start_image` is kept as the first frame). Everything
else — the two i2v 14B high/low UNETs, the i2v lightx2v 4-step LoRAs, `umt5_xxl`, `wan_2.1_vae`,
the dual `KSamplerAdvanced` passes, `CreateVideo` (fps 16), `SaveVideo` — is identical, which
matches the guide's Phase-0 note that native FLF2V "runs on the same weights with a
`WanFirstLastFrameToVideo` node." Node/input names are verified against ComfyUI master source
(`comfy_extras/nodes_wan.py`); slot inference produces the exact expected map (see
`tests/test_slot_inference.py::test_real_flf2v_export_infers_frames`, now active).

**✅ Live-validated 2026-07-09** on a `video-eval` pod (agent-stack template `cnne9dp3rt`,
volume `3wqkq1t8bq`, ComfyUI 0.17.2): submitted an 81→33-frame clip from two uploaded frames
and got `status=success` with a real 335 KB `Wan2.2_flf2v_00001_.mp4` (fetched via `view()`).
This also live-confirmed the client's video-history parsing — native `SaveVideo` reports the mp4
under the **`images`** key (PreviewVideo shape), and `videos_from_history` extracts it correctly.
The node inputs were verified against this pod's live `/object_info` (`WanFirstLastFrameToVideo`
optional `start_image`/`end_image`), matching the graph exactly. Harness:
`packages/visual-generation/scripts/validate_flf2v.py <endpoint>`.

### Expected (Phase-0 export — not yet committed)

| File | Purpose | Key nodes (verified vs ComfyUI master source) |
|---|---|---|
| `qwen-image-edit-2511-api.json` | Qwen-Image-Edit 2511 **keyframe edit** | `TextEncodeQwenImageEditPlus` (`prompt` text; ordered `image1`/`image2`/`image3` refs), and — in the native template — `FluxKontextImageScale`, `FluxKontextMultiReferenceLatentMethod`, `ModelSamplingAuraFlow` (shift 3.1), `CFGNorm`, a `VAEEncode` latent (not empty), and a turbo-toggle switch |

The Qwen native template is a **subgraph** with FluxKontext helper nodes (see the official
template `Comfy-Org/workflow_templates/.../image_qwen_image_edit_2511.json`) — materially more
complex than a one-node swap, so it needs a real **File → Export (API Format)** rather than a
hand-build. Its fixture-gated test (`test_real_qwen_edit_export_infers_edit_images`) skips until
committed. Note: its image ports route through `FluxKontextImageScale` before the encoder, so
edit-image slot inference may need to trace through that passthrough — verify against the export.

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
