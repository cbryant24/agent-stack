---
title: Technique Research Agent — v2 Refinements (deferred from Phase 2)
date: 2026-06-12
agent: technique-research
status: open
---

# Technique Research — Deferred Items

The durable record of everything captured-but-not-built for `technique-research`.
Phase 2 built the Mode A turn to MVP (identify → ground → check → gate → delegate →
curate → outputs; recall; orchestrator tools). Items below were deliberately left out
as non-MVP-blocking. This file stays current.

## Parked by the Phase 1 handoff (revisit list)

- **Mode B — footage-based diagnosis (V2).** YouTube URL + start/stop timestamps or a
  local file → ffmpeg interval frames → multi-frame Claude-vision technique diagnosis →
  search/match on the diagnosis. The V1 provision is already in place: the chain's input
  model is `text + zero-or-more images + optional context` (`IdentificationInput.images`),
  so Mode B is *more frames into the same list* plus an extraction front-end + interval
  logic — an extension, not a redesign. All primitives (ffmpeg in yt-intelligence-pipeline,
  multimodal throughout) already exist.
- **Findings carrying reference images** (multimodal storage). Would force a
  `voyage-multimodal-3` embedding-space decision; findings are deliberately text-only
  (`voyage-3-large`) for now. A finding carrying its reference image is a deliberate
  revisit, not a default.
- **A reaction loop on findings** (`report --reaction` / revisit list). Findings have no
  reaction loop in V1.
- **visual-generation retrieval querying `technique_research_outputs` directly.** A change
  to a built agent; not needed for the V1 loop — the knowledge channel (delegated material
  landing in `tutorial_research`, which visual-generation already queries) already makes
  generation-technique research land where visual-generation looks.
- **concept-script → technique-research delegation** (already on concept-script's V2 list).
- **MCP exposure** (system-wide deferral).

## Noticed during the Phase 2 build (non-blocking)

- **Finding→domain source-ref precision.** `_build_findings` attaches the *union* of all
  delegated `tutorial-research run <id>` refs to every curated finding, rather than tying
  each finding to the specific domain whose delegation produced it. Correct fix: thread a
  per-domain run-id through curation (e.g. curate per-domain, or have the model echo the
  domain key) so `source_refs` and "where to learn more" are precise.
- **Curation is a single call over all domains.** Fine for the typical 3–6 domains; for a
  large/heterogeneous domain set a per-domain (or batched) curation call would keep the
  findings sharper and the source-ref mapping exact (see above).
- **Check thresholds are unvalidated starting values** (`CHECK_*_THRESHOLD` in
  `constants.py`: 0.70 / 0.65 / 0.70). Tune from the `delegation_decision` trace events
  (`local_max_score` vs `threshold` vs the decision that followed) once real runs
  accumulate — the music-curation tuning pattern.
- **`--plan-only` stdout is terse.** The preview's KNOWN/GAP distinction is written to the
  report file's "Gaps & Delegations" section but not echoed inline to the terminal (the
  inline KNOWN/GAP tags only render in the interactive gate, which plan-only skips). A
  short gap summary to stdout on `--plan-only` would save opening the file.
- **`editing_toolset` query is the goal text.** `read_editing_toolset` queries with the
  raw goal once at run level. A per-domain toolset re-query (or a goal+domain composite)
  could surface more targeted toolset facts for how-to-apply grounding.
- **`config._ensure_directories` doesn't pre-create the `technique-research` vault
  subdir** (cosmetic — `render_run_report` mkdirs it on first write). Add it for parity
  with the other agents if touching config.
- **Console script not on PATH.** Like the other workspace agents, invoke via
  `uv run --package technique-research technique-research …` or `python -m
  technique_research.cli` — the bare `technique-research` console script isn't exposed by
  `uv run` in this workspace (same for `music-curation`).
