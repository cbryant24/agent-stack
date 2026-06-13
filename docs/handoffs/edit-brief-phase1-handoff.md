---
title: Edit Brief Agent — Phase 1 Handoff
date: 2026-06-12
type: phase-1-handoff
agent: edit-brief
project: agent-stack
status: active
---

# Edit Brief Agent — Phase 1 Handoff

Phase 1 (Design and discovery) is complete. All design questions necessary for the build are resolved with documented reasoning. This document hands off to **Phase 2 (Build to MVP)** and supersedes the version that opened Phase 1; it carries forward everything Phase 2 needs without re-deriving Phase 1's conclusions.

## What `edit-brief` is (resolved)

Translates the creative artifacts (the approved `script.md`, the selected music, voiceover takes, available footage and generated assets, technique findings) into a **director-owned, time-ordered execution checklist** for the director's DaVinci Resolve free session. The director does the editing; this agent prepares the briefing. **Critical caveat unchanged and load-bearing:** no DaVinci API, no automated editing — Tier 1, knowledge consultant only.

**The central design question (confirmed):** the artifact is **timeline-first, not topic-first**, in three layers:

1. **Timeline skeleton** — the script's H1 sections become rows with start/end timestamps computed from actual VO file durations plus breathing gaps, each row naming its VO file and candidate footage/assets.
2. **Beat grid** — cut points computed arithmetically from BPM + music duration. Pure math, never LLM-estimated.
3. **Per-section ordered steps** — checkbox items (`- [ ]`) executable in Resolve free without leaving the document: which file, which timestamp, which Resolve page/tool, grounded in retrieved technique findings with toolset fit and upgrade flags carried through verbatim.

**The actionability test for every item:** the director mid-edit can execute it as written, in order, against Resolve free's documented constraints (`editing_toolset`).

**Decide vs. surface (confirmed):**

- **Decides (owns):** all time arithmetic (section timestamps, beat grid); the ordering of work; which retrieved technique findings apply to which section/moment; the mapping of VO files and assets to script sections. Deterministic computation or assembly judgment — the agent's one distinct competence.
- **Surfaces (never decides):** creative selection among viable footage for a moment (proposes ranked candidates, director picks); reconciliation between the VO-driven section grid and the music's structure (computes both grids, proposes nearest-beat alignments, marks them as proposals); any technique or toolset claim not groundable in `technique_research_outputs` / `tutorial_research` / `editing_toolset` — gaps are flagged as gaps naming the upstream agent, never filled by invention.

**The redundancy test:** no technique discovery, no gathering, no hardcoded toolset facts. Everything knowledge-shaped is retrieved; what this agent adds is exclusively the assembly and the time-translation. The moment material needs gathering, that is an upstream agent's job and the brief says so.

## Input contract and assembly (resolved)

**Positional script + collection discovery + flags as overrides.** No project manifest — the Project Organizer was scrapped as redundant with Cowork, so a manifest would be a one-agent convention that Feedback & Iteration then inherits. The linking key is `project_id`, defaulting to the script filename stem (the voiceover-direction convention).

- **Required:** the script, positional (`edit-brief draft SCRIPT.md`). Nothing else.
- **VO** — discovered from voiceover-direction's records by `project_id`; durations read from the audio files on disk via ffprobe, not trusted from metadata. Take selection where multiple takes exist per section: the positively-reacted take wins, else latest — stated rule, ambiguity noted in the brief.
- **Music** — *(amended at the Phase 2 handoff-verification turn: `music_curation_memory` holds no `project_id`, file, or duration — Suno is manual; only bpm, title, and prompt are logged, so discovery-by-project_id can't work as written.)* The track file + ffprobe'd duration come from `--music FILE`. BPM precedence: `--bpm N` flag > best-effort semantic match of the script's music-hint line against `music_curation_memory`, surfaced as a labeled proposal (matched title shown, director overrides) > none → beat grid omitted with notation.
- **Generated assets** — discovered from visual-generation's records; the generation record (intent, prompt, lineage) gives rich section mapping. Two provenance types in one asset list: director footage (thin metadata — surfaced, not decided) vs. generated assets (rich metadata — mapped precisely).
- **Director footage** — the one input with no record anywhere, so the one real flag: `--footage DIR` scans and ffprobes for filename + duration; descriptions are optional director-authored enrichment.
- **Technique findings** — retrieved, never passed.

**Graceful degradation by layer, each absence a visible "missing input" notation, never a failure or silent guess:** script alone → skeleton with estimated timestamps explicitly marked as estimates; +VO → computed timestamps; +BPM → beat grid; +findings → grounded recommendations; no findings → steps grounded only in `editing_toolset`, gaps named ("no findings on X — run technique-research").

## Output shape and ownership (resolved)

A director-owned **`edit-brief.md` written next to the script** (`-o`/`--output` overrides), per the evolved artifact convention — this supersedes the spec's "checklist written to the agent-reports vault." The vault gets only the standard run report as a side-effect.

- Frontmatter carries `project_id`, `version: 1`, and the inputs actually discovered (provenance).
- Sections keep stable anchors derived from the script's H1s so Feedback & Iteration can reference and revise specific parts.
- How F&I versions the brief (in-place bump vs. new file) is **F&I's Phase 1 question**, deliberately not pre-decided here.

## Time-structure mechanics (resolved)

**All timing is computed in code, never by the LLM.** The LLM places recommendations *against* the computed grids and never invents numbers.

- Section timestamps: cumulative offsets from ffprobe-read VO durations plus a configurable inter-section gap (`--gap`).
- Beat grid: beat = 60/BPM, bars at 4 beats, from track start; nearest-beat candidates proposed at each section boundary (proposal, not decision — the director chooses where boundaries land musically).
- Fallback: no VO → word-count estimates at a configurable rate, marked as estimates in the brief.

Immediate adjustment is two-level: the gap and estimate rate are flags, and the brief is the director's editable file.

## Memory model (resolved): stateless

Passes the concept-script test — no learning loop of its own, so no collection. It **reads `user_knowledge` on every run**: timing/editing preferences the director states ("gaps too long, use 0.5s") land there via the existing propose→confirm path and ground every future brief. The reaction loop — discovering those lessons from feedback after an edit session rather than the director stating them — is exactly Feedback & Iteration's purpose; **F&I owns learning-from-feedback.**

## Knowledge grounding and delegation (resolved): read-only v1

Retrieval composes `technique_research_outputs`, `tutorial_research`, and `user_knowledge` per the established pattern, with `editing_toolset` always loaded so every Resolve instruction is groundable in the documented free-version constraints; the upgrade-flag convention carries through verbatim. **No delegation in v1:** a knowledge gap becomes a named notation in the brief, because spawning a research run mid-assembly is the wrong moment and gathering belongs upstream. The orchestrator can chain technique-research → edit-brief later if that friction proves real.

## CLI surface and budget (resolved)

```bash
edit-brief draft SCRIPT.md [--footage DIR] [--music FILE] [--bpm N] [--gap SECONDS] \
    [-o brief.md] [--project-id ID] [--max-cost N] [--dry-run]
```

- **`--dry-run` is the one free op:** discovery only — prints what was found and what's missing per input (the degradation picture) before anything is spent. No recall verb; the agent is stateless.
- Budget: standard per-run `BudgetEnvelope`; synthesis is one or two Claude calls, no external spend, no delegation. Starting values, unvalidated: `max_cost_usd=2.00, max_wall_time_sec=600, max_depth=0`.
- **Orchestrator wrapping (stack convention):** `draft` as a child-budgeted sub-agent tool; the dry-run discovery as the free op.

## First build session scope (concrete)

1. **Foundation.** Package scaffold per stack conventions; data models (the three-layer brief, discovered-inputs provenance); runtime wiring (`BudgetEnvelope`, tracing, reporting, Claude client via `get_config()`).
2. **Discovery layer.** Collection queries by `project_id` (VO takes with the take-selection rule, music record, visual-gen assets); `--footage` scan with ffprobe.
3. **Time engine.** Section timestamps + word-count estimate fallback; beat-grid arithmetic. Pure, fully unit-tested code.
4. **Retrieval composition.** Three collections, `editing_toolset` always loaded.
5. **Synthesis chain.** Emits the brief with frontmatter, stable section anchors, checkboxes, missing-input notations; writes `edit-brief.md` next to the script; standard vault run report.
6. **CLI.** `draft` + `--dry-run`.
7. **Tests throughout**; two recorded smoke runs *(amended at handoff-verification: `script-draft.md` has no VO/music/asset records logged)* — (a) the degradation run on `script-draft.md` as-is (estimated timestamps + missing-input notations), and (b) a synthetic VO-backed 2-section fixture against real audio exercising the full computed-from-VO-duration + beat-grid path live.

Orchestrator wrapping completes Phase 2 per the stack convention — second session if the first runs long.

## Research signals (between-phase; nothing gathered in Phase 1)

One, **flagged only, not v1 work:** beat detection for tracks without logged BPM (librosa/aubio territory). The brief's "no BPM → no beat grid" notation is the trigger to revisit if it bites in practice.

## Revisit list (parked, not worked)

- Beat detection for unlogged BPM (the research signal above).
- Richer music↔collection linkage — a real `project_id` (and file/duration) on `music_curation_memory`, removing the semantic-match step.
- Mid-run delegation to technique-research/tutorial-research (v1 is read-only; orchestrator chaining is the first answer if gap-friction is real).
- A reaction loop on briefs — F&I owns learning-from-feedback.
- F&I's versioning mechanics for the brief (its Phase 1).
- VO-grid/music-structure reconciliation beyond nearest-beat proposals.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines). Not restated here.

## Phase 2 scope discipline and end condition

**Scope:** build to MVP per the build order above. Adjacent additions go to the deferred list, not into Phase 2. Phase 2 opens with the handoff-verification turn: the director re-reads this document fresh and confirms or flags drift before any build prompt is sent.

**End condition:** `draft` runs end-to-end on real project data producing an `edit-brief.md` with all three layers and missing-input notations as the inputs dictate; `--dry-run` prints the discovery picture; the time engine is fully unit-tested; the test suite passes; both smoke runs (degradation + VO-backed fixture) are recorded. At that point Phase 2 is MVP-complete and deferred items are written to `docs/v2-refinements/v2-refinements-edit-brief.md`.
