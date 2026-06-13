---
title: Concept & Script Agent — Phase 3 Handoff
date: 2026-06-07
type: phase-3-handoff
agent: concept-script
project: agent-stack
status: active
---

# Concept & Script Agent — Phase 3 Handoff

Phase 2 (Build to MVP) is complete. Both input modes work and were verified by real-input smoke testing, and the post-MVP polish that surfaced on first contact has landed. This document opens **Phase 3 (Refinement)** and carries forward the Phase-2-deferred items as Phase 3's candidate work — with the honest accounting that none of their adoption conditions are currently met.

## Post-Phase-2 state (built; not Phase 3 work)

Recorded so Phase 3 does not redo it.

- **Two verbs, one artifact.** `draft` (generative — seeds file/inline, optional `--ref` prior script) and `shape` (curation — verbatim dictation transcript) both emit a single editable `script.md` that `voiceover-direction direct` consumes unchanged.
- **Stateless v1.** No Qdrant collection, no stores, no delegation (`max_depth=0`). Runtime wiring (BudgetTracker, tracing, report rendering, run-complete notify, AsyncAnthropic) mirrors music-curation minus the stateful parts.
- **Output contract verified against the real consumer.** Every section is an H1; emotion direction is inline `[tag]` syntax in the prose; the logline, optional `Music:` hint, and the cut trailer live in the pre-heading preamble the voiceover parser skips. Confirmed parsing through `voiceover_direction.parser` with nothing leaking into narration.
- **Refinement pass already landed (2026-06-07)**, recorded in `docs/v2-refinements/concept-script-v2-refinements.md` under "Addressed in a refinement pass." Two `shape` defects found in real-input testing were *fixed*, not deferred:
  - Self-correction handling is now configurable, **preserve-by-default**; the shape-only `--clean` flag opts into resolving corrections into final prose. The flag affects only self-corrections — disfluency stripping, `director note` execution, and sectioning are identical in both modes.
  - The cut trailer is now reliable for every executed `director note` (any form — deletion, global/repeated change, replacement, reorder; a global change is one summarizing entry), with a deterministic safety-net warning when the wake phrase is present but no cut was recorded.
- **Test baseline:** 45 package tests, 669 workspace, ruff clean. End-to-end smoke verified both modes and the `voiceover-direction direct` boundary on real input.

These corrections were small follow-up changes (a flag, a prompt fix), not Phase 3 scope. They are done.

## Phase 3 candidate items (all currently dormant)

The durable, authoritative record is `docs/v2-refinements/concept-script-v2-refinements.md`. This handoff summarizes each item with its adoption signal and current trigger status; it does not restate the full reasoning. **No adoption condition below is currently met, so there is no triggered Phase 3 work.** Each item activates only when its signal fires, and when one does it is a small focused session, not a full phase.

1. **Knowledge-base reads (`user_knowledge` / `tutorial_research`).** Signal: a draft comes out demonstrably under-grounded *despite adequate seeds*, and the improvement from a read is attributable. Status: not observed. Backfill cost: none — a thin read-only `retrieval.py` mirroring the existing music-curation / tutorial-research pattern; the agent stays stateless. Treat together with Technique-Research delegation.
2. **Chat / conversational mode.** Signal: the file loop demonstrably fails to let you steer — repeated `draft` re-runs because you can't direct the output without a conversation. Status: not observed. Pulls forward the deferred runtime chat work.
3. **`concept_script_memory` collection.** Signal: corpus scale makes manual `--ref` file reference impractical, or a feedback signal emerges worth learning from. Status: not observed. Backfill cost: none — a batch ingest of existing `script.md` files.
4. **Technique Research delegation.** Signal: Technique Research is built *and* a brief needs technique grounding you haven't supplied. Status: TR not built.

## Research signals

**None.** Unchanged from Phase 2 — concept-script reasons with Claude plus the existing knowledge bases and introduces no new third-party API or knowledge domain requiring ingestion. There is no between-phase ingestion blocker.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines). Not restated here.

## Phase 3 scope discipline and end condition

**Scope.** Address only deferred items whose adoption conditions have fired, scoped to non-major, smaller-touch changes. Do not pull untriggered items forward to get ahead — the adoption conditions exist precisely because building these without their signal means building mechanisms that can't yet be validated. Documentation-only updates and single small follow-up changes are not Phase 3; they are single sessions.

**End condition.** All Phase-3-scoped items either landed or remain in `docs/v2-refinements/concept-script-v2-refinements.md` with documented reasoning for the defer; that file stays current; all documentation reflects the post-Phase-3 state; a handoff is produced for the next agent, tool, or application.

**Current practical reading.** Because no adoption condition is met, concept-script has no triggered Phase 3 work right now. Phase 3 stays open but dormant for this agent until a signal fires; the next concrete build in the stack is a separate agent's Phase 1, not concept-script refinement.
