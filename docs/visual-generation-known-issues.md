# Visual Generation — Known Issues & Tech Debt

Tracked limitations and deferred fixes for the `visual-generation` agent. Each entry
carries a status and either the planned fix or the reason it is an accepted limitation.

## KI-1 — Refinement inherits LoRAs/dims the img2img template can't apply
**Status: advisory implemented — full support deferred**

An edit-mode `draft --from` inherits the parent generation's `lora_stack` and
`width`/`height`, but the `visual-workflow-img2img` template exposes no LoRA-loader or
width/height slots, so those values are silently dropped (`build_prompt_graph` collects
them as `unmapped`, and img2img output size actually comes from the init image).

The draft-time `inert_inheritance` advisory (models/draft/cli) now warns the user when
inherited attributes won't apply — shipped alongside the refinement work. The remaining
gap is real support: an img2img+LoRA template, part of the deferred ControlNet + LoRA work.

## KI-2 — Refinement prompt-style preservation is not enforced
**Status: accepted limitation**

Seed-from-parent seeds the parent's prompt and instructs the craft chain to edit-not-
rewrite, but style preservation depends on the LLM following that instruction; it cannot
be deterministically enforced for free text. (The recipe and model inheritance ARE
enforced in code, so the render-affecting parts are guaranteed.)

## KI-3 — Rationale can cite recipe/denoise numbers that don't match applied settings
**Status: accepted (cosmetic)**

The crafted `rationale` is free text and may state values that contradict the enforced
settings (e.g. "denoise 0.75" when 0.5 was applied, "CFG 3.5" when the template recipe
stood). Metadata only — it does not affect the render. Seed-from-parent instructs the
model to omit recipe/denoise numbers in edit mode, but this is not enforced.

## KI-4 — Generation status never finalizes from PENDING
**Status: open bug — fix needed**

After a successful render, the generation record's status stays `PENDING` instead of
moving to a terminal state, even though `generate` reports "Status: completed". `chain
show` and any status-based filtering therefore misreport. It does not affect lineage or
source resolution (both ignore status), which is why img2img refinement works against a
PENDING parent.

Fix: set the terminal status on the generation record when a spec is successfully drained
in `generate.py`.

## KI-5 — mypy baseline: 73 pre-existing errors
**Status: open tech-debt (pre-existing)**

`mypy src` reports 73 errors on `main`, predating the refinement/dedupe work (verified by
stashing — HEAD shows the identical count and per-file distribution). Most are in untouched
files (e.g. `chains.py`). The refinement, seed-from-parent, advisory, and dedupe changes
introduce zero new type errors. Clearing the baseline is separate tech-debt.

## KI-6 — `draft` crashes when the batch directory doesn't exist
**Status: resolved**

On a machine where `~/agent-data/visual-generation/batches/` has never been created, `draft`
died after crafting the spec with `FileNotFoundError: …/batches/batch.batch.md` —
`write_batch`/`append_spec` (`batch_file.py`) wrote the batch file without creating its
parent directory. The spec was lost (the crash happened mid-write, before anything was printed
or persisted), and the Voyage retrieval line just above it is an unrelated, non-fatal
"degrading gracefully" message.

Fixed: `write_batch` now calls `path.parent.mkdir(parents=True, exist_ok=True)` before the
write (covering both the direct-write and `append_spec` paths), and
`test_write_batch_creates_missing_parent_dir` regression-tests the missing-`batches/`-dir case.

## KI-7 — Default batch file is named `batch.batch.md`; `Next:` hint prints a placeholder
**Status: resolved**

With no `--project`/`--output`, the batch path was `<project>.batch.md` and `project` defaulted
to the literal string `"batch"`, yielding the redundant `batch.batch.md`. Separately, the
`draft` success output printed `Next: visual-generation generate <batch.md> --section …` — a
generic `<batch.md>` placeholder rather than the real path, which is the one on the
`Appended to:` line.

Fixed: `_default_batch_path` (`draft.py`) now falls back to the stem `"default"`
(`default.batch.md`, matching the `assets/default/` convention) instead of `"batch"`, and the
`Next:` hint (`cli.py`) interpolates the real `result.batch_path`.

## KI-8 — `draft` template auto-retrieval can select the inpaint graph for text2img prose
**Status: open — workaround available; guard is a candidate fix**

`draft` resolves its workflow template by embedding-similarity retrieval over registered
templates. When the intent prose leans heavily on a television/screen — and the top-matching
technique lessons are screen-inpaint lessons — retrieval can select `visual-workflow-inpaint`
instead of the text2img `visual-workflow`. The inpaint template requires an `init_image` +
`mask`; a plain `draft` (no `--from`/`--image`/`--mask`) supplies neither, so the spec carries
inpaint slots that can't be filled. `draft` still succeeds (it's offline), but `generate` fails
at submit with ComfyUI `400 prompt_outputs_failed_validation` →
`node_errors … "Invalid image file: mask"` — before any render, so no GPU is spent and the local
cost tracker does not move; safe to re-run.

Tell: the draft output shows a `denoise` value in `Settings:` and `Template: visual-workflow-inpaint`
— a plain text2img draft has no `denoise` and should read `Template: visual-workflow`.

Workaround: pin the text2img template explicitly to bypass retrieval —
`visual-generation draft "<intent>" --template visual-workflow --project <P> -o <batch.md>`.

Candidate fix (not committed): have `draft` default to a text2img template when no
`--from`/`--image`/`--mask` is supplied.

## Considered alternatives / future bake-off — reference/edit-based identity
**Status: queued — bounded bake-off before any migration**

The identity model (one trained LoRA per character, applied at a blunt strength) is the root of
several recurring costs: a full retrain per style/wardrobe pivot, bleed/fade at strength extremes,
and weak adherence on complex staging. A reviewed proposal argues for carrying identity as
**reference images** and generating each shot as an instruction-driven **edit/compose** — primary
candidate **Qwen-Image-Edit 2511**, alternative **FLUX.2 dev**.

Verified feasible against this codebase: the pipeline is model-agnostic (slot inference is
wiring-derived; `workflow register` is generic; LoRA application isn't text2img-gated), and a
separate-pod-on-separate-volume eval is supported (`scripts/pod` honors `POD_NAME` /
`NETWORK_VOLUME_ID`). **Biggest caveat:** the `--from`/`--image` path is **single-image
img2img/inpaint only** (`VisualSource` enforces one origin, `models.py`) — there is **no
multi-reference input today**, so this is a real build, not a small extension. Migration is gated on
a bounded 3-shot bake-off (Qwen vs FLUX.2 vs current) judged as a set.

Decision record (proposal verbatim + full verification/corrections):
`~/obsidian/obsidian-vault-personal/production-agents/visual-generation/visual-generation-model-alternatives.md`.
Execution plan: `~/.claude/plans/review-this-alternative-lucky-codd.md`.
