---
title: Concept & Script Agent — Phase 2 Handoff
date: 2026-06-05
type: phase-2-handoff
agent: concept-script
project: agent-stack
status: active
---

# Concept & Script Agent — Phase 2 Handoff

Phase 1 (Design and discovery) is complete. All design questions necessary for the build are resolved with documented reasoning; no research signals were surfaced. This document opens **Phase 2 (Build to MVP)** and carries forward everything Phase 2 needs to begin without re-deriving Phase 1's conclusions.

## What `concept-script` is (resolved)

A **structural/craft scriptwriting collaborator, not a creative automator.** It proposes craft scaffolding — section breakdown, pacing, emotional arc, candidate per-section emotion direction — and **surfaces, never decides** the creative core (theme, message, which references matter). The user owns every decision by editing the output. This framing is load-bearing and anchors every build decision.

The single load-bearing claim from Phase 1: **v1's output is the Voiceover-Direction-ready script, not an abstract brief the user adapts later.** If the primary output isn't the artifact the next agent ingests, the agent has produced homework, not input.

## The output artifact (resolved)

The agent emits a single editable `script.md` consumed directly by `voiceover-direction direct script.md`. The lean `VideoBrief` is:

- **Logline** — one line; keeps the agent and the user aligned on intent.
- **Per-section script with emotion direction** — markdown-with-headings, each heading a section. This *is* the pacing/structure made concrete. The per-section emotion direction is the voice direction; there is **no separate voice-direction field**.
- **Optional music-hint block** — style hints for Music Curation.

The exact per-section emotion-direction syntax must match what `voiceover-direction direct` actually parses. **Reading that consumer's input contract is Phase 2's first concrete task** (see build order). It is an implementation read of an existing package, not a new design question.

## Two input modes → one editable `script.md` (resolved)

- **Generative** — sparse seeds (theme/topic, mood descriptors, target duration or a musical reference implying duration, stylistic references, project type), plus an optional `@prior-script.md` reference input. The agent *proposes* structure. More inventing.
- **Curation** — a dictated voice-to-text transcript. The agent *extracts* the structure latent in the stream-of-consciousness. Less inventing, more shaping.

Both converge on the same editable, Voiceover-Direction-ready file.

## Curation command channel (resolved)

The dictation tool's only job is faithful verbatim capture. The agent receives the full transcript and resolves an in-band channel inside it:

- **Verbatim content is preserved.**
- **Disfluencies stripped** — uh, um, dead-air repetition, false starts.
- **Natural stumbles and self-corrections are kept as content** (e.g. "you know what, I'm wrong about that…"). These are authentic texture, not errors. The agent does nothing with them.
- **`director note` is the wake phrase** — the one deliberate edit signal. `director note, delete that last portion` → the agent executes the deletion and removes the phrase plus its instruction from the script. It is the *only* thing the agent acts on as a real content deletion.
- **Sectioning + per-section emotion direction applied** on top.
- **Output carries a trailer** listing the executed `director note` cuts, so the user can verify them.

Provenance note: the wake-phrase commands are legitimate instructions because they originate from the user's own dictation (his direct input), not third-party content.

Downstream consequence (intended): kept corrections get **narrated** by Voiceover Direction — the VO will speak "you know what, I'm wrong about that." This authentic effect is the point.

## Memory model (resolved)

**v1 is stateless. No `concept_script_memory` collection.**

The feedback loop that earns a memory collection for `music-curation` and `voiceover-direction` (a `report --reaction` signal accumulating into taste/direction lessons) does not exist here — brief quality only surfaces many steps downstream and attribution back is muddy. A collection with no learning mechanism is just stored data.

The real value memory could serve — prior work as reference material — is covered in v1 by **file reference** (`@prior-script.md`), since outputs are files. The agent may still *read* `user_knowledge` and `tutorial_research` to fill a gap; it simply owns no write-memory collection.

## Interaction surface (resolved)

**Single-shot, file-based, both modes. No chat mode.**

The conversational creative surface already exists upstream in the user's workflow (Claude Chat for ideation; Claude Code for development). `concept-script` is the tool that turns decided inputs — seeds or a transcript — into the artifact; building chat into it duplicates Claude Chat. Curation is inherently a file transform; generative refinement is the file loop the whole stack uses (`generate → edit script.md or adjust seeds → re-run`). The user steers by editing the file he owns, which is the collaborator-not-automator ownership model.

## CLI shape (resolved; verb names are an implementation detail)

Two front doors, mirroring the stack's verb pattern, both emitting `script.md`:

- a **generative** verb — seeds, plus optional `@prior-script.md` reference.
- a **curation** verb — transcript file.

## Integration targets

- **Voiceover Direction** (built) — consumes `script.md` directly. Tightest coupling; the emotion-direction format must align with its parser.
- **Music Curation** (built) — consumes the optional music-hint block.
- **Edit Brief** (not built) — will consume an approved `VideoBrief` downstream.
- **Technique Research** (not built) — upstream enhancement. **v1 stands alone** on Claude plus user-provided references; TR delegation is a later enhancement, not a v1 dependency.

## First build session scope (concrete)

Build order, grouped for efficient sequencing (not scheduled):

1. **Foundation.** Read the `voiceover-direction direct` input contract and nail the exact per-section emotion-direction format. Define the `VideoBrief` data model and its serialization to markdown-with-headings (logline + per-section script-with-emotion + optional music-hint block + cut trailer). Wire into `agent-runtime`: `BudgetEnvelope`, tracing, Markdown reporting, Claude client. Everything else emits this artifact, so it comes first.
2. **Generative mode.** Seeds (+ optional `@prior-script.md` reference) → Claude → `script.md`. Proves the artifact shape and generation prompt patterns end to end.
3. **Curation mode.** Transcript → command-channel processing (disfluency stripping, stumble/correction preservation, `director note` detection → execute → remove, sectioning, emotion direction, cut trailer) → `script.md`. The heavier logic; build after the artifact shape and prompt patterns are proven in generative.
4. **Integration verification.** Confirm `script.md` is consumed by `voiceover-direction direct` unchanged, with the emotion-direction format aligned.

## Deferred items (adoption conditions, not rejections)

Destined for `docs/v2-refinements/v2-refinements-concept-script.md`:

- **Chat / conversational mode** — adoption: the file loop demonstrably fails to let the user steer (repeated `generate` re-runs because he can't direct it without a conversation). Pulls forward the deferred runtime chat work.
- **`concept_script_memory` collection** — adoption: corpus scale makes manual file reference impractical, or a feedback signal emerges worth learning from. Backfill is a batch ingest of existing `script.md` files (the `music-curation seed ingest` pattern), so deferring carries no penalty.
- **Technique Research delegation** — adoption: TR is built and a brief needs technique grounding the user hasn't supplied.

## Research signals

**None.** `concept-script` reasons with Claude plus the existing knowledge bases; it introduces no new third-party API or external knowledge domain requiring ingestion between phases. There is no between-phase ingestion blocker.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines). Not restated here.

## Phase 2 scope discipline and end condition

**Scope:** build to MVP per the build order above. Resist adjacent additions ("while we're at it…"); they go to the deferred list, not into Phase 2.

**End condition:** both input modes produce a `script.md` that `voiceover-direction direct` consumes unchanged; the curation command channel behaves as specified (verbatim preservation, disfluency stripping, stumble preservation, `director note` execution + removal, cut trailer); runtime wiring (budget, tracing, reporting) is in place; the test suite passes; a successful end-to-end smoke test is recorded. At that point Phase 2 is MVP-complete and deferred items are written to `docs/v2-refinements/v2-refinements-concept-script.md`.
