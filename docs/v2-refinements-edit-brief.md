---
title: Edit Brief Agent — v2 Refinements (deferred)
date: 2026-06-12
type: deferred-list
agent: edit-brief
project: agent-stack
status: active
---

# Edit Brief Agent — v2 Refinements

Adjacent additions surfaced during the Phase 2 (Build Session 1) MVP build,
parked here rather than worked. MVP is complete: `draft` runs end-to-end, the
time engine is fully unit-tested, the suite is green (50 passed), and both smoke
runs are recorded (degradation on `script-draft.md`; a synthetic VO-backed
fixture proving computed-from-VO timestamps + a 120-BPM beat grid).

## Carried from the Phase 1 revisit list

- **Beat detection for unlogged BPM** (librosa/aubio). Today: `--bpm`, else a
  best-effort proposal matched from `music_curation_memory`, else the beat grid is
  omitted with a notation. The "no BPM → no beat grid" notation is the trigger to
  revisit if it bites.
- **Mid-run delegation to technique/tutorial-research.** v1 is read-only — a
  knowledge gap becomes a named notation. Orchestrator chaining
  (`technique-research → edit-brief`) is the first answer if gap-friction proves
  real.
- **A reaction loop on briefs** — Feedback & Iteration owns learning-from-feedback.
- **F&I's versioning mechanics for the brief** (in-place bump vs. new file) — F&I's
  Phase 1 question.
- **VO-grid / music-structure reconciliation beyond nearest-beat proposals.**

## Surfaced during this build

- **Music↔collection linkage is loose by construction.** `music_curation_memory`
  has no `project_id`, no logged audio file, and no duration (Suno is manual). So
  music discovery is `--music FILE` (file + ffprobe duration) plus a *semantic*
  BPM proposal matched on the script's `Music:` hint — not a real project link. A
  durable fix would add a `project_id` (and optionally a chosen-track file path)
  to the music generation record so edit-brief can discover the actual selected
  track by project, not by fuzzy hint match. This is the cleanest resolution of
  the Phase 1 "discover music by project_id" intent against the real schema.

- **Decoupling vs. shared foreign-schema constants.** edit-brief reads three
  foreign collections generically (the orchestrator reader precedent) and
  duplicates a few payload facts locally — `POSITIVE_VO_REACTIONS`, the
  `memory_type`/field names. If these drift in the owning agents, edit-brief's
  reads silently narrow. A shared, read-only "collection contracts" module in
  `agent-runtime` (payload field names + reaction vocabularies) would let readers
  depend on a contract without importing the writer package.

- **`get_config()` is required even for `--dry-run`.** The free discovery op still
  constructs `RuntimeConfig`, which validates the Anthropic key. Discovery only
  needs Qdrant + Voyage. A lazy/partial config (or a discovery path that never
  touches the Anthropic field) would make the free op truly key-light. Stack-wide
  config concern, not edit-brief-specific.

- **Generated-asset → section mapping is LLM-mediated, not computed.** The handoff
  framed generated assets (rich `prompt`/`caption` metadata) as *decided* mapping.
  v1 hands the asset list to the synthesis prompt and lets the model map by intent.
  A deterministic pre-map (embed each section's body, match against asset captions
  in `visual_generation_memory`, attach as `TimelineRow.candidate_assets`) would
  move that decision back into code where the handoff put it — note that
  `visual_generation_memory` is `voyage-multimodal-3` space, so the match must
  embed in that space, not `voyage-3-large`.

- **`--footage` description sidecars are minimal.** v1 reads `<file>.txt` sidecars
  for director-authored descriptions. Richer enrichment (per-clip in/out points, a
  manifest file, shot tags) is deferred.

- **Step quality polish.** The synthesis sometimes numbers steps inside the
  checkbox (`- [ ] 1. …`) and occasionally routes a section-specific note to the
  brief-level `overall_notations`. Cosmetic; tighten the prompt if it grates.

- **Orchestrator-tool input is script-only.** `edit_brief_draft` /
  `edit_brief_discover` wrap `draft` on the positional script alone — the
  `--footage`/`--music`/`--bpm` director overrides are not threaded through the
  tool surface (the orchestrator has no natural place to source a music file path
  autonomously). If a director-mediated orchestrator flow needs the beat grid, add
  optional `music`/`bpm` tool params. Mirrors the precedent's single-arg tools
  (`technique_identify(goal)`, `voiceover_direct(script_path)`).

- **Mid-run chaining, not just wrapping.** The orchestrator can now call both
  edit-brief tools, but it does not yet chain `technique-research → edit-brief` (or
  `voiceover-direction → edit-brief`) to fill a discovered gap before drafting.
  Each tool is invoked independently; the model composes them turn-by-turn. A
  designed chain (or the orchestrator auto-running discovery, seeing the gap
  notations, and offering the upstream run) is the next integration step — this is
  the same read-only-vs-delegation line drawn in Phase 1.

## Phase 2 close — orchestrator wrapping (shipped)

Wrapped in `orchestrator.tools` per the `technique_identify` / `technique_recall`
precedent: `edit_brief_draft` (child-budgeted sub-agent tool — one Claude
synthesis call, no external money, no DaVinci API) and `edit_brief_discover` (the
free op — `--dry-run` discovery + the pure time engine, no LLM, no file). NO
`search_knowledge` registry entry: edit-brief is stateless and owns no collection
(it reads `user_knowledge` + the foreign collections generically). Both record the
delegation on the active tracker under the `edit_brief` label. Closes Phase 2 —
see `docs/edit-brief-phase2-handoff.md`.
