# Execution-truth status — agent-shell Phase 0

Audited 2026-10-04 against the **working tree** at `f17ae89` (main). No source files were
changed. Covers the 13 "still open" items in
`packages/visual-generation/docs/coraline-failure-conclusions.md` §9 (`:343-358`), plus
KI-4, KI-8 and the batch-file regex.

Paths are relative to `packages/visual-generation/src/visual_generation/` unless they start
with `packages/` or `docs/`. Tests are in `packages/visual-generation/tests/`.

**Update 2026-10-07 (Phase 5 entry gate, session 1).** Rows 3, 4 and 6 below are fixed and committed, each with
regression tests, and a new gate item the audit did not list is done: the exact submitted graph and the
input/output hashes are now saved beside every output (`provenance.py`, `generate.py:508-540`,
`quick.py:236,263`; tests `test_execution_truth_provenance.py`, `2eb2ba5`). Row 5 (the template's
1152×896 default size) is **still open**: validation covers values a spec states, not a size it leaves
unset. The phase doc numbers these gate items 3 to 6; this table keeps the audit's own row numbers.
**Gate 0 itself has not been run:** it needs a pod. `packages/visual-generation/docs/gate0/RUN.md` has the
commands and `visual-generation gate0 verify` judges the evidence.

**Verdict at audit time: Gate 0 was not met.** Items 1 and 2 have since been fixed in the working tree
(2026-10-04, uncommitted, see below); items 3–13 are still open. Phase 5 needs those two fixes committed.

**HEAD vs uncommitted.** Of the files cited, `generate.py`, `chains.py`, `retrieval.py`,
`canon.py`, `gpu_tracker.py`, `batch_file.py`, `models.py` and `draft.py` are clean — those
findings are in `HEAD`. `graph_build.py`, `slot_inference.py` and `constants.py` have
uncommitted changes and `quick.py` is untracked; each use is flagged below. The
`constants.py` diff only appends lines after `:233`, so the two `constants.py` lines cited
here are identical in `HEAD`.

## 1. Item 1 — random seed never written to the graph

**Fixed 2026-10-04 (uncommitted, working tree).** `plan_generation` resolves the seed first and builds the graph from it
(`generate.py:339-341`); `random` overrides a leftover `spec.seed`, so graph and record agree. Regression tests in
`test_generate.py`: `test_random_seed_strategy_writes_the_rolled_seed_into_the_graph`,
`test_random_seed_strategy_overrides_a_pinned_seed_in_graph_and_record`, `test_fixed_seed_is_submitted_and_recorded_exactly`,
`test_two_plans_of_a_random_spec_get_different_seeds` (the first three failed before the fix; the fixed-seed test already
passed). Existing records are untouched (open question 6).

The trace below is the defect as audited, before the fix.

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
| 2 | `unmapped` never shown to the user | **Fixed 2026-10-04 (uncommitted)** | Gate prints it per spec before the confirm (`cli.py:725`, helper `cli.py:112`). Missing seed slot skips the spec with a reason (`generate.py:342-349`; `GenerationPlan.skip_reason` `:116`). `quick` prints it (`cli.py:939`) and raises `QuickSeedUnmapped` (`quick.py:160`). Carried on `VisualResult.unmapped` (`generate.py:514`) and `QuickResult.unmapped` (`quick.py:74`). Warn-only for every other value. | `test_cli_turn.py::test_cli_generate_gate_warns_on_unmapped_values_before_the_confirm`, `::test_cli_generate_prints_the_reason_when_every_spec_is_skipped`; `test_generate.py::test_spec_whose_template_has_no_seed_slot_is_skipped_with_a_reason`, `::test_random_strategy_on_a_template_with_no_seed_slot_is_also_skipped`, `::test_spend_reports_the_skip_reason_not_the_no_template_message`, `::test_unmapped_values_ride_on_the_plan_and_the_result`; `test_quick.py::test_quick_returns_unmapped_values_on_the_result`, `::test_quick_refuses_when_the_template_has_no_seed_slot`; `test_cli_quick.py::test_quick_warns_when_a_requested_value_has_no_slot`, `::test_quick_unmapped_seed_is_a_clean_cli_error`. |
| 3 | Template-baked LoRAs apply on empty stacks | **Fixed 2026-10-07 (`b117501`)** | `graph_build.neutralize_unused_loras` (`graph_build.py:127`) sets unused baked loaders to strength 0 (and `strength_clip`); called from `plan_generation` (`generate.py:402`) and `quick_generate` (`quick.py:205`). A baked loader with no strength slot skips the spec with a reason (quick raises `QuickLoraUnsafe`). The cost gate prints what was switched off (`cli.py`). | `test_execution_truth_loras.py` (11 tests, incl. the real `z-image-turbo-lora` workflow and the `quick` path) |
| 4 | Canon pin beyond the loader count dropped silently | **Fixed 2026-10-07 (`2a7b9b4`)** | `graph_build.dropped_identity_loras` (`graph_build.py:168`) finds identity-bearing LoRAs (registry decides) that landed in `unmapped`; `plan_generation` (`generate.py:391`) skips the spec with a plain reason and `quick_generate` (`quick.py:199`) raises. A style LoRA that does not fit stays a warning. | `test_execution_truth_identity_drop.py` (10 tests) |
| 5 | Template default resolution 1152×896 | **Open** | `packages/visual-generation/workflows/z-image-turbo-lora-api.json:72-73`. Applies whenever the spec has no width/height (`graph_build.py:94-97`). | None |
| 6 | No validation or clamping of steps/cfg/denoise/strength/size; no prompt length budget | **Fixed for explicit values 2026-10-07 (`dc30283`); prompt length budget still open** | `validation.validate_spec` (`validation.py:43`) checks the effective spec against `constants.VALUE_BOUNDS`; `plan_generation` (`generate.py:376`) skips with every reason before any spend, `quick_generate` raises `QuickInvalidSpec` (`quick.py:188`). Rejected, never clamped. | `test_execution_truth_validation.py` (every bound, both edges) |
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
