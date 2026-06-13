---
title: Edit Brief Agent — Phase 2 Handoff
date: 2026-06-12
type: phase-2-handoff
agent: edit-brief
project: agent-stack
status: active
---

# Edit Brief Agent — Phase 2 Handoff

Phase 2 (Build to MVP) is complete. `draft` runs end to end producing the
three-layer brief, the time engine is fully unit-tested, and the orchestrator now
wraps both ops. This document hands off to **Phase 3 (Refinement)** and carries
forward the post-Phase-2 state plus every captured-but-not-built item. Phase 1
design rationale lives in `docs/handoffs/edit-brief-phase1-handoff.md`; the durable
deferred-item record is `docs/v2-refinements/v2-refinements-edit-brief.md`.

## What shipped (MVP)

`packages/edit-brief/` — the full `draft` turn (parse → discover by `project_id`
→ compute timeline + beat grid in code → retrieve toolset/findings/`user_knowledge`
→ one Sonnet synthesis call placing findings against the computed grids → render
`edit-brief.md` next to the script → standard run report) plus `--dry-run` (the
free discovery + computed grids, no LLM, no file). All timing is arithmetic — the
LLM never produces a number. No DaVinci API, no delegation (read-only v1).

**Orchestrator integration (this session — the second build session):** wrapped in
`orchestrator.tools` per the `technique_identify` / `technique_recall` precedent.

- **`edit_brief_draft`** — child-budgeted sub-agent tool. Calls
  `edit_brief.draft(script_path, budget=_child_budget())`. It spends only Claude
  (one synthesis call), touches no external money and no DaVinci API, so it
  qualifies for wrapping (the `research_tutorials` / `technique_identify`
  precedent — Claude-only spend is wrappable). Returns status, cost, the brief
  path, and the missing-input notations.
- **`edit_brief_discover`** — the free op. Calls
  `edit_brief.draft(script_path, dry_run=True)` (no budget — the dry-run path
  spends nothing): discovery + the pure time engine, no LLM, no file. Returns the
  degradation picture (what was found per input + the notations). Records the
  delegation at cost `0.0`, the `*_recall` precedent.
- **No `search_knowledge` registry entry.** edit-brief is stateless and owns no
  collection — it reads `user_knowledge` and the foreign collections generically
  (the orchestrator cross-collection-reader pattern), so there is nothing to
  register as a knowledge domain. Both tools record their delegation under the
  `edit_brief` label (the stateless `concept_script` precedent for a label that
  isn't a real collection).

Conventions matched: in-process library entry point called with a derived child
budget (budget parent/child, tracing, and the shared client propagate naturally);
graceful degrade — every tool returns a message string on failure, never raises
into the loop; `_record_delegation` on the active tracker; a shared
`_render_discovery` helper feeding both tools. `edit-brief` added to the
orchestrator's `pyproject.toml` dependencies + `[tool.uv.sources]` workspace
entries (mirrors the six sibling agents), `uv sync` re-locked.

## Verification (recorded)

- **Package suite:** `50 passed` (unchanged from Build Session 1 — the time engine,
  discovery, retrieval, chains, CLI, and both package-level smoke fixtures).
- **Orchestrator suite:** `44 passed, 1 skipped` (the skip is the
  `requires_qdrant` guard). The 3 new tests live in `test_subagent_tools.py`
  alongside the sibling-tool tests:
  - `edit_brief_discover` is free (asserts the entry point is called with
    `{"dry_run": True}` and NO budget) and records the delegation under
    `edit_brief`.
  - `edit_brief_draft` passes a **derived child budget** (the shared
    `_assert_child_budget` helper) and records under `edit_brief`.
  - failure returns a message string, does not raise.
- **Ruff:** clean on `packages/orchestrator`.
- **Orchestrator-path smoke (degradation, recorded):** invoked both tools through
  the orchestrator's actual tool-execution path (a tool `.ainvoke` inside an active
  parent `BudgetTracker`) against the real `script-draft.md`:
  - `edit_brief_discover` — free, spent `$0.0000`, recorded 1 delegation, surfaced
    the four missing-input notations (no VO / no music / no BPM → no beat grid / no
    assets). 7 sections, `beat_grid=no`.
  - `edit_brief_draft` — `completed`, `$0.0884`, child-budgeted, wrote
    `script-draft.edit-brief.md`, recorded the 2nd delegation. Degradation path
    exercised: estimated timestamps, omitted beat grid, and the toolset-grounded
    notations (locked Film Grain / RGB-Shift → Fusion, the Topaz-on-M1 / `-vsync
    vfr` quirk, the Studio-only upgrade flags) all carried through verbatim.

This complements the two package-level smoke runs recorded in Build Session 1
(degradation on `script-draft.md`; the synthetic VO-backed 2-section fixture
proving computed-from-VO timestamps + a 120-BPM beat grid).

## Deferred to Phase 3 / V2 (full list in `docs/v2-refinements/v2-refinements-edit-brief.md`)

Carried from Phase 1: beat detection for unlogged BPM (librosa/aubio); a real
`project_id` + chosen-track file/duration on `music_curation_memory` (removing the
semantic BPM match); mid-run delegation to technique/tutorial-research (v1 is
read-only); a reaction loop on briefs (F&I owns learning-from-feedback); F&I's
brief-versioning mechanics; VO-grid/music-structure reconciliation beyond
nearest-beat proposals.

Surfaced during the build: deterministic generated-asset → section pre-mapping
(currently LLM-mediated; note the `voyage-multimodal-3` embedding space); a shared
read-only "collection contracts" module so readers don't duplicate foreign payload
facts; `get_config()` validating the Anthropic key even for the free `--dry-run`;
step-quality prompt polish.

Surfaced this session (orchestrator integration): the tool surface wraps the
positional script only — the `--footage`/`--music`/`--bpm` overrides are not
threaded through (no autonomous source for a music path); and the orchestrator
wraps but does not yet **chain** `technique-research → edit-brief` (or
`voiceover-direction → edit-brief`) to fill a gap before drafting — each tool is
invoked independently, the model composes turn-by-turn. The designed chain is the
natural next integration step and the same read-only-vs-delegation line Phase 1
drew.

## Phase 3 scope discipline

Phase 3 is smaller-touch: polish a working agent, don't redesign it. Group items by
surface area, each with explicit smoke verification. Anything that lands stays in
the docs; anything not done moves to `docs/v2-refinements/v2-refinements-edit-brief.md` with
reasoning. The highest-value candidates are the deterministic asset→section
pre-map (moves a decision the handoff put in code back out of the LLM) and the
real music↔project link (removes the only fuzzy step in discovery).
