---
title: Concept & Script Agent — Phase 1 Handoff
date: 2026-06-05
type: phase-1-handoff
agent: concept-script
project: agent-stack
status: active
---

# Concept & Script Agent — Phase 1 Handoff

This document opens **Phase 1 (Design and discovery)** for the Concept & Script agent (`concept-script`). The prior agent, `voiceover-direction`, is at Phase 2 complete (MVP) with its deferred items recorded in `docs/v2-refinements-voiceover-direction.md`; its Phase 3 is treated as empty (no deferred item earned a build pass). Per the build methodology, Phase 1 is a design conversation — **no code is written** — and it opens against this handoff rather than a build prompt.

## System state at handoff

What `concept-script` can rely on as already built and queryable:

- **`agent-runtime`** — shared base: `BudgetEnvelope`, delegation, tracing, `MemoryStore`, `UserKnowledgeStore`, Markdown reporting. New agents inherit budget governance, tracing, and the memory layer for free.
- **`tutorial-research`** — research/retrieve agent over the `tutorial_research` collection; delegatable for knowledge gaps. Concept & Script is a candidate delegator (style references involving techniques), but **Technique Research — its natural upstream — is not built yet** (`#5` in the build order, parallel/non-blocking).
- **`music-curation`** — consumes optional brief/style hints; reads `music_curation_memory`.
- **`voiceover-direction`** — consumes a **markdown-with-headings script** (each heading a section) with per-section emotion direction. This is the most concrete downstream integration target.
- **Collections:** `user_knowledge` (runtime-owned verified facts), `tutorial_research`, `music_curation_memory`, `voiceover_direction_memory`. The storage table in `ai-director-agent-system.md` assigns **no collection to `concept-script`** — whether it needs persistent memory is an open Phase 1 question (below).

## What Concept & Script is (from the system spec)

A **creative brief generator** — but the spec is emphatic about the framing: *"start simple here — this isn't a forced workflow, it's a scriptwriting collaborator. Initial implementation should focus on producing a brief the user actually wants to use as input to other agents, not on automating creative decisions."* That directive is load-bearing and should anchor every Phase 1 decision.

Starting points from the spec (explicitly **not** final — the user wants Phase 1 to surface inputs he hasn't thought of):

- **Inputs:** theme/topic, mood descriptors, target duration (or a musical reference implying duration), stylistic references (artists, films, prior work), project type.
- **Outputs:** a structured `VideoBrief` — logline, pacing/structure plan, **per-section voiceover script with emotion direction**, and cross-references to other agents (music-style hints for Music Curation, voice direction for Voiceover Direction). Optional Obsidian note for human review.
- **Tools:** Claude for generation, the runtime memory layer for retrieving reference material from prior projects, possible delegation to Tutorial Research. Not a closed list.

## Integration constraints (load-bearing)

The brief is consumed, not terminal. The shapes it must serve:

- **Voiceover Direction** takes markdown-with-headings, per-section, with emotion direction. The `VideoBrief`'s per-section VO script should line up with that input — this is the tightest coupling and the clearest design anchor.
- **Music Curation** takes optional style hints / a brief.
- **Edit Brief** (not built) will take an approved `VideoBrief` downstream.
- **Technique Research** (not built) is upstream — it would *inform* what techniques the brief calls for. Concept & Script v1 must work **without** it; TR delegation is a later enhancement, not a v1 dependency.

## The central design question (the Phase 1 gate)

> **What is the minimal, genuinely-useful shape of the brief — and the collaboration that produces it — such that the user actually wants to use its output as input to the downstream agents (Voiceover Direction first), given that this is a scriptwriting *collaborator*, not a creative *automator*?**

Concretely: what does the agent *decide* versus *surface for the user to decide*, and what does the `VideoBrief` actually contain? This question is the gate. Per the methodology, secondary questions are worked only after this is settled with explicit confirmation.

## Secondary design questions (dependency order, after the gate)

1. **Brief → voiceover coupling.** Does `concept-script` emit the markdown-with-headings script that `voiceover-direction direct` consumes *directly* (clean, tight handoff), or a more abstract brief the user adapts? The spec's "per-section voiceover script" leans toward the former; confirm and define the exact artifact boundary.
2. **Memory model.** Stateless (each brief fresh) or a `concept_script_memory` collection (prior briefs/projects retrievable as reference material)? The spec mentions "retrieving reference material from prior projects," but assigns no collection. Decide whether memory earns its place in v1.
3. **Interaction surface.** Single-shot CLI (like `direct`'s first pass) or conversational? A scriptwriting *collaborator* is the agent most likely to want the conversational chat mode that's currently deferred in `v2-refinements-agent-runtime.md`. Phase 1 should decide whether v1 is single-shot (and chat mode is a later adoption) or whether this agent justifies pulling that runtime work forward.
4. **Input discovery.** The user explicitly wants the design to surface useful inputs beyond the obvious list. Treat the spec's inputs as a seed and actively probe for others (emotional arc, structural intentions, reference-to-own-prior-work, etc.).
5. **Technique Research delegation.** Confirm v1 operates standalone with user-provided references/techniques, with TR delegation specified as a later enhancement.

## Research signals

**None required.** `concept-script` reasons with Claude plus the runtime memory layer and the existing knowledge bases — it introduces no new third-party API or external knowledge domain that must be ingested before Phase 2 (unlike `voiceover-direction`, which needed ElevenLabs docs seeded between phases). Phase 1 → Phase 2 has no between-phase ingestion blocker. If a gap surfaces during the design conversation, Phase 1 produces the signal (a `tutorial-research` prompt or a list of URLs to ingest) — but none is anticipated.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines, etc.). Not restated here.

## Phase 1 scope discipline and end condition

**Scope:** architecture, memory model, workflow shape, CLI surface, and the design questions above. No code. The central question is the gate; resist opening adjacent design questions ("while we're at it…") — they go on a revisit list, not into Phase 1.

**End condition (from the methodology):** all design questions necessary for Phase 2 resolved with documented reasoning; the first build session's scope concretely proposed; research signals identified (expected: none); and an updated handoff produced that hands off to Phase 2 with everything Phase 2 needs to begin without re-deriving Phase 1's conclusions.
