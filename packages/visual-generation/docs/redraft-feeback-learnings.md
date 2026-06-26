# Claude Code Prompt — visual-generation doc updates (README + TROUBLESHOOTING + prompt-craft learnings doc)

## Goal

Update the `visual-generation` package documentation to reflect this session's findings, and transform the raw dialogue-extract doc I added into a structured living prompt-craft learnings doc. **Use plan mode (Shift+Tab).** Return the plan for review before writing.

## Mode

Plan mode. Several README sections plus a doc transformation — show what you'll change and where before editing.

## Files in scope

- `@packages/visual-generation/README.md`
- The learnings doc I recently added under the visual-generation package docs — locate it (filename is `redraft-feeback-learnings.md`, likely under `packages/visual-generation/docs/`). Confirm the path in your plan.

## Task 1 — README: command-surface verification

A prior doc-edit prompt (from the 2026-06-25 session) may or may not have been applied. Verify the README documents the current command surface and add anything missing:

- `redraft <gen_id> "<change>"` — directed, recipe-locked text2img revise (inherits parent seed/settings/model/LoRAs/dims/template in code; re-authors prose; lineage via `revised_from`; append-only; spends no GPU).
- `--model {sonnet|opus}` on `draft`/`redraft` (default sonnet; `opus` → `claude-opus-4-8`).
- `batch list` / `batch rm` group.
Report in your plan which were already present vs. added.

## Task 2 — README: known-issue / gotcha

Add (to the appropriate existing issues/usage section — your judgment on placement):

- **`--project` omission misfiles the asset.** Running `draft`/`redraft` without `--project <id>` files the generated asset under `assets/default/` instead of `assets/<project>/`. Because `edit-brief` discovers visual-generation's assets by `project_id`, a misfiled asset will not be discovered downstream. Always pass `--project <id>` for project work.

## Task 3 — README TROUBLESHOOTING section

Add, in the existing TROUBLESHOOTING section, to the list of commands that require `op run --env-file=.env` because they embed (run retrieval/embeddings):

- Add **`redraft`** to that list — it embeds via retrieval, same as `draft`/`generate`/`recall`. (It is currently missing.)
- Confirm **`recall`** is listed there too and that its embed requirement is stated; add if absent.
Frame each as: what the symptom is (e.g. an embedding/credential error when run without `op run`), and the fix (prefix with `op run --env-file=.env -- uv run …`).

## Task 4 — Transform the learnings doc into a living prompt-craft reference

The file I added (`redraft-feeback-learnings.md`) is currently a raw verbatim dialogue transcript. Restructure it into a concise, durable prompt-craft learnings doc for `celeste-you-dangerous` (you may rename it to `docs/celeste-you-dangerous-prompt-craft.md` if that reads better — note the rename in your plan). It should be a living reference we append to as we draft/redraft, organized as:

**Section: How `redraft` actually conditions on its parent (code-verified 2026-06-26)**

- Always text2img; `source=None` hard-coded; never conditions on the parent image.
- Inherited in code: the full recipe — seed (re-pinned fixed), settings, model, LoRA stack, dimensions, template.
- NOT inherited in code: the prompt prose. The prompt is fully LLM-authored from the parent prose (given as input) plus the change instruction. Verbatim preservation is requested in the system prompt, not enforced.
- Continuity therefore rests on the inherited recipe + fixed seed + a stable descriptor block. The prose is the only un-pinned drift surface. True lock would require a character LoRA (none exists).

**Section: Confirmed working levers**

- Treat the change instruction as a director's note, not a scene description: state the single change first (front-loaded), instruct the model to preserve the parent's wording, re-describe nothing else.
- Subtract an inherited descriptor to change it. Lighting example: the room would not darken while "glowing wall sconces / amber accents" stayed in the inherited prose; removing the wall light sources (rather than adding "dark") let the room read dim.
- Heavy, repeated, front-loaded wording is a deliberate lever for a change that repeatedly won't take (e.g. orientation, crowd density) — distinct from default terseness, which applies to everything not being changed.
- Subject-orientation language ("rear view," "from behind," "facing the stage") beats camera-position language for directing attention; prefer "image perspective" over "camera." (Grounds: course prompt-craft docs — front-loaded words carry the most weight; specificity trade-off means over-describing crowds out the change.)
- Full backs-to-viewer sidesteps the button-eye dropout entirely (no faces to resolve).

**Section: Confirmed regressions / failure modes**

- Over-verbose redraft instructions that re-describe locked attributes cause those attributes to drift or drop (narrator's skin rendered pale; Celeste's hair drifted to dreadlocks) — because the model re-authors the whole prose.
- Button-eye dropout on small/profile/background faces is a depth/size model limit; prompting improves odds but does not reliably beat it. Fix: masked eye-inpaint at the edit stage.
- A claim banked without a source is a confabulation risk — the "Z-Image frame-filling bias" hypothesis was NOT confirmed (the wide shot landed) and was correctly not banked. Note this as a discipline: bank a lesson only on confirmed, repeated evidence, worded as observation not mechanism.

**Section: Per-character locked descriptors (celeste-you-dangerous)**

- Celeste: shoulder-length black yarn hair (NOT dreadlocks), bare light felt face, glossy black stitched sewing-button eyes.
- The narrator: deep caramel-brown felt skin, long black yarn dreadlocks to mid-back, clean-shaven, glossy black stitched sewing-button eyes, white hoodie (flat front), red/white Air Jordan 1-style high-tops.
- Note these are *reference, not contract*: preserve only confirmed-wanted attributes; everything else stays open to experiment.

Keep it concise and scannable. Preserve a short pointer to the raw dialogue extract if you rename, or fold the few still-relevant verbatim examples in as short quotes — don't keep the whole transcript.

## Output

Plan first: file paths confirmed, per-task list of what's already present vs. what you'll add/transform, and the proposed learnings-doc structure (and rename, if any). Wait for approval before writing.
