# test fixtures — exported ComfyUI graphs (API format)

Slot-inference tests load these API-format graphs and assert the inferred slot maps.

- `flux_txt2img_api.json` — the committed Flux txt2img graph (present).

## Phase-0 fixtures (not yet committed — tests skip until they land)

The FLF2V/Qwen slot-inference tests are **fixture-gated**: they `pytest.mark.skipif` when
the file is absent, so the suite stays green before the Phase-0 export
(`tests/test_slot_inference.py::test_real_flf2v_export_infers_frames` /
`test_real_qwen_edit_export_infers_edit_images`).

To activate them, copy the committed Phase-0 workflow exports here under these exact names:

- `wan2.2-flf2v-14B-lightx2v-api.json` — copy of `workflows/wan2.2-flf2v-14B-lightx2v-api.json`
- `qwen-image-edit-2511-api.json` — copy of `workflows/qwen-image-edit-2511-api.json`

The committed `workflows/wan2.2-i2v-14B-lightx2v-api.json` is loaded directly by the I2V
tests (no copy needed) and already exercises the video-conditioning + dual-sampler paths.
