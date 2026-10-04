# Execution-truth status — agent-shell Phase 0

Audited 2026-10-04 against the **working tree** at `f17ae89` (main). No source files were
changed. Covers the 13 "still open" items in
`packages/visual-generation/docs/coraline-failure-conclusions.md` §9 (`:343-358`), plus
KI-4, KI-8 and the batch-file regex.

Paths are relative to `packages/visual-generation/src/visual_generation/` unless they start
with `packages/` or `docs/`. Tests are in `packages/visual-generation/tests/`.

**Verdict: Gate 0 is not met.** Item 1 is still open on the `generate` path, in both `HEAD`
and the working tree. All 13 items are open. Phase 5 stays blocked.

**HEAD vs uncommitted.** Of the files cited, `generate.py`, `chains.py`, `retrieval.py`,
`canon.py`, `gpu_tracker.py`, `batch_file.py`, `models.py` and `draft.py` are clean — those
findings are in `HEAD`. `graph_build.py`, `slot_inference.py` and `constants.py` have
uncommitted changes and `quick.py` is untracked; each use is flagged below. The
`constants.py` diff only appends lines after `:233`, so the two `constants.py` lines cited
here are identical in `HEAD`.

## 1. Item 1 — random seed never written to the graph

**Open.** No regression test.

Trace of the `generate` path (all in `HEAD`):

1. The drafter may emit `seed_strategy: "random"` (`chains.py:69`, `chains.py:387`), stored
   on the spec (`draft.py:263`, `draft.py:549`).
2. `plan_generation` builds the graph first: `build_prompt_graph(spec, template)`
   (`generate.py:327`). That writes a seed only when `spec.seed is not None`
   (`graph_build.py:92-93`). For a random-strategy spec with no seed, nothing is written and
   the template's own seed stays in the graph.
3. Only afterwards is the random number drawn: `resolved_seed=_resolve_seed(spec)`
   (`generate.py:336`, function at `generate.py:133-136`). It is stored on the plan and never
   written to `graph`.
4. The same number is then recorded as if it had been used: `seed=sp.resolved_seed`
   (`generate.py:469`).

So a random-seed render runs on the template seed while the memory record claims another
seed. The doc's line references have drifted: it cites `graph_build.py:89-90`; the lines are
now `92-93`.

Uncommitted work and what it does to this item:

- `graph_build.py` diff adds only the `length` and `fps` setting slots (`:26-27`). It does
  not touch seed handling.
- `slot_inference.py` diff changes **which node** the seed slot points at for two-stage WAN
  graphs. It fixes slot *location*, not the missing write. Its tests
  (`test_slot_inference.py:178`, `:211`) assert the slot target only.
- `quick.py` (untracked) gets it right on its own path: it draws the seed first
  (`quick.py:134`), puts it on the spec as `fixed` (`quick.py:141-142`), then builds the
  graph (`quick.py:151`). `test_quick.py:81` covers the random case. It still discards
  `unmapped` (`quick.py:151`), so a template with no seed slot fails silently.

A fix for `generate` is to resolve the seed before building the graph, as `quick.py` does.

## 2. Items 2–13

| # | Item | Status | Evidence | Regression test |
|---|---|---|---|---|
| 2 | `unmapped` never shown to the user | **Open** | Collected at `generate.py:327` and stored at `:337`; never read again. No reference in `cli.py`. `quick.py:151` discards it as `_unmapped`. | None for surfacing. `test_graph_build.py:38`, `:55` only prove values are collected. |
| 3 | Template-baked LoRAs apply on empty stacks | **Open** | `graph_build.py:112-117` only writes for LoRAs in the spec's stack; nothing neutralizes a loader when the stack is empty. Baked in: `packages/visual-generation/workflows/z-image-turbo-lora-api.json` node `30:48` → `narrator-zimage.safetensors` @ 1.0; `z-image-turbo-inpaint-lora-api.json` node `75` → `celeste-zimage-coraline-v2.safetensors` @ 1.0. | None |
| 4 | Canon pin beyond the loader count dropped silently | **Open** | Extra LoRAs fall into `unmapped` (`graph_build.py:113`), which is never shown (item 2). | `test_graph_build.py:55` asserts the drop is collected, not that it is reported. |
| 5 | Template default resolution 1152×896 | **Open** | `packages/visual-generation/workflows/z-image-turbo-lora-api.json:72-73`. Applies whenever the spec has no width/height (`graph_build.py:94-97`). | None |
| 6 | No validation or clamping of steps/cfg/denoise/strength/size; no prompt length budget | **Open** | No range checks in `models.py` (`VisualSpec` `:232-266`; the only validator is on `VisualSource`, `:64`), `draft.py`, `chains.py` or `generate.py`. `MAX_DRAFT_TOKENS` (`constants.py:131`) caps the LLM reply, not the prompt sent to the image model. | None |
| 7 | Drafter system prompt has no Z-Image guidance; Flux/euler example | **Open** | `chains.py:34` ("Flux, SDXL, WAN"); example at `chains.py:67-68` uses `"sampler": "euler"`, `flux_guidance`, `flux1-dev.safetensors`. No mention of Z-Image, Turbo or `res_multistep`. | None |
| 8 | `-2500` LoRAs marked `identity_bearing: false`; stale LoRAs offered | **Open (data)** | `~/agent-data/visual-generation/models.json`: `celeste-zimage-coraline-turbo-2500.safetensors` and `narrator-zimage-coraline-turbo-2500.safetensors` are both `identity_bearing=False` and still registered. | n/a — registry data, fixable with `model rm` |
| 9 | `[PROJECT CANON]` text sent as "LOCKED — never contradict"; stale docstring | **Open** | `retrieval.py:343`, `:354`, `:357`; docstring still claims deterministic enforcement at `retrieval.py:278-279`. `canon.py:8-9` says canon no longer rewrites prompt text. | None |
| 10 | Alias matching counts negated mentions | **Open** | `canon.py:236-243` is a plain word-boundary search; "no Celeste" matches. | None |
| 11 | Trigger tokens not part of the spec contract | **Open** | No trigger-token field in `VisualSpec` or `LoraRef` (`models.py:42-47`, `:232-266`). The only "trigger" in the package is an unrelated research-gap constant (`constants.py:202`). | None |
| 12 | No image-level verification | **Open** | No vision or image-check call anywhere in the package; `generate.py:440-452` writes the bytes without inspecting them. | None |
| 13 | GPU ledger misses pod uptime and training | **Open** | `gpu_tracker.py:6-7` documents uptime as an approximate proxy from first submit to drain; `SessionMeter` (`:93-128`) times only the agent's session. Nothing records `scripts/pod` uptime or `scripts/lora-train` runs. | None |

`graph_build.py` carries uncommitted changes, but none of the lines cited for items 2–5
are part of that diff; those findings hold in `HEAD` too (line numbers there are two lower).

## 3. Known issues that touch the REPL

**KI-4 — status never finalizes from PENDING** (`docs/visual-generation-known-issues.md:34`).
**Open, and it is a design mismatch rather than a missed write.** `status` is not stored on
its own: it is derived from `reaction` every time a record is written (`models.py:137`), and
only `report` flips it (`store.py:103-118`). A successful render therefore stays `pending`
until the user reacts, by construction. `test_generate.py:89` asserts the pending write;
`test_store.py:148` asserts the flip. The record has no field meaning "rendered
successfully", so a chat tool cannot tell a rendered-but-unreviewed generation from any
other pending one.

**KI-8 — template retrieval picks inpaint for text2img prose**
(`docs/visual-generation-known-issues.md:81`). **Fixed in code; the doc is stale.** Template
resolution now prefers a template whose modality matches the spec (`draft.py:67-90`), `draft`
warns on a sourceless spec landing on an img2img/inpaint template (`draft.py:330-337`), and
`generate` skips instead of returning a 400. Tests: `test_draft.py:137`, `:169`, `:199`;
`test_generate.py:395`. The known-issues doc still says "open".

**Batch-file metadata regex.** **Open.** `batch_file.py:37-38` captures non-greedily up to the
first `-->`. The comment at `:35` says `-->` cannot appear inside the JSON, but the metadata
includes LLM-written `rationale` and user-editable `negative_prompt`
(`batch_file.py:42-59`), and JSON encoding does not escape `-->`. A rationale containing
`-->` would truncate the capture and break parsing of that spec. No test covers it
(`test_batch_file.py:104` covers a missing comment, not a truncated one).

## 4. What this means for sequencing

- Phases 1–4 are unaffected: they spend no GPU.
- Phase 5 needs, at minimum, items 1 and 2 fixed with regression tests. Item 2 matters as
  much as item 1: without it, any future "value didn't reach the graph" defect is invisible
  again.
- A `record_evaluation` tool (Phase 4) would attach verdicts to records whose `seed`,
  LoRA stack and resolution may not match what ran (items 1, 3, 4, 5). Evaluations written
  before those fixes should be marked as such.

## Open questions

1. Item 1 is a small reorder in `plan_generation`. Fix it now in its own session, ahead of the other twelve?
2. Should `unmapped` values block a render, or only be printed at the cost gate?
3. KI-4: add a real "rendered" status to the record, or rename the current field so it says what it means?
4. Item 8 is registry data on this machine. Remove the two `-2500` LoRAs with `model rm`, or re-flag them?
5. KI-8 looks fixed. Mark it resolved in the known-issues doc?
6. Existing generation records made with `seed_strategy: random` carry a seed that never ran. Flag or correct them before any evaluation is recorded against them?
