# edit-brief

Translates the approved `script.md` plus the discovered creative artifacts (voiceover
takes, music, generated assets, director footage) and retrieved technique knowledge into
a **director-owned, time-ordered `edit-brief.md`** — an execution checklist for a DaVinci
Resolve **free** session. The director does the editing; this agent prepares the briefing.

Tier 1 only: **no DaVinci API, no automated editing, no delegation** (v1). The agent's one
competence is **assembly and time-translation** — section timestamps from VO durations,
beat-aligned cut proposals from BPM, retrieved findings placed against the computed grids.
All timing is computed in code, never by the LLM. All knowledge is retrieved, never
gathered; gaps are flagged naming the upstream agent, never invented.

## CLI

```bash
edit-brief draft SCRIPT.md [--footage DIR] [--music FILE] [--bpm N] [--gap SECONDS] \
    [-o brief.md] [--project-id ID] [--max-cost N] [--dry-run]
```

- **Required:** the script, positional. Everything else is discovered by `project_id`
  (default: the script's filename stem) or supplied as an override.
- **`--dry-run`** is the one free op: discovery + the computed grids only — prints what was
  found and what is missing per input, no LLM call, no file written.
- **`--music FILE`** supplies the track (ffprobed for duration; `music_curation_memory`
  logs no file). **BPM** comes from `--bpm`, else a best-effort *proposal* matched from
  `music_curation_memory` (the matched track title is surfaced), else the beat grid is
  omitted with a notation.

## The three layers

1. **Timeline skeleton** — section start/end timestamps from ffprobe-read VO durations plus
   `--gap`; word-count estimates (marked as estimates) where a section has no VO take.
2. **Beat grid** — `beat = 60/BPM`, bar = 4 beats; nearest-beat *proposals* at each section
   boundary. Pure arithmetic, never LLM-estimated.
3. **Per-section ordered steps** — `- [ ]` checkbox items executable in Resolve free, in
   order, grounded in the retrieved `editing_toolset` + `technique_research_outputs`
   (toolset-fit and paid/Studio upgrade flags carried through verbatim).

## Memory model

Stateless — owns no collection. Reads `editing_toolset` (always loaded) and stated director
preferences from `user_knowledge` on every run. Learning-from-feedback belongs to the
Feedback & Iteration agent.

## Design

Phase 1 design: `docs/handoffs/edit-brief-phase1-handoff.md`. Deferred items:
`docs/v2-refinements/edit-brief-v2-refinements.md`.

## FAQ

Common questions and knowledge gaps. Add entries as they come up.

### How does edit-brief find my assets?
By `project_id` (default: the script's filename stem). VO takes, music + BPM, and generated stills are auto-discovered from the collections by that id — so thread the same id used by `voiceover-direction --project-id` and `visual-generation --project`.

### Should I pass generated stills via `--footage`?
No. `--footage DIR` is only for director-shot video clips. Generated stills auto-discover by `project_id`; the selected music track is passed via `--music`.

### Where do this agent's files go?
`-o` outputs are director-owned working files — put them in your per-project folder (`~/agent-projects/<project-slug>/`). Machine-managed outputs (sources, audio, stills, qdrant) go under `~/agent-data/`, and run reports auto-write to `~/obsidian/agent-reports/`. Canonical, single-source-of-truth detail: [File organization](../../README.md#where-should-project-files-live) in the repo root README.
