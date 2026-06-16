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
