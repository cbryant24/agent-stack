---
title: Feedback & Iteration Agent — Phase 1 Handoff
date: 2026-06-12
type: phase-1-handoff
agent: feedback-iteration
project: agent-stack
status: active
---

# Feedback & Iteration Agent — Phase 1 Handoff

Phase 1 (Design and discovery) is complete. All design questions necessary for
the build are resolved with documented reasoning. This document hands off to
**Phase 2 (Build to MVP)** and supersedes the version that opened Phase 1; it
carries forward everything Phase 2 needs without re-deriving Phase 1's
conclusions.

## What `feedback-iteration` is (resolved — the central answer)

**Revision is the spine; learning hangs off it.** After the director produces a
draft edit, the agent takes natural-language feedback ("the drop feels too
slow," "voiceover is competing with the music in the bridge") and runs one
pipeline: **feedback → moment mapping → diagnosis → (always) a targeted,
anchor-addressed revision of the live brief with a version log entry → (when
the diagnosis generalizes) a proposed durable lesson through propose→confirm.**
Learning is a tap on the diagnosis, not a second engine.

What it distinctly owns — the redundancy test against a fresh edit-brief run
(~$0.09, stateless):

1. **Interpretation.** A fresh run takes no feedback input. Perceptual-reaction
   → diagnosed-change translation exists nowhere else in the stack.
2. **State-preserving targeted revision.** Regeneration destroys the director's
   checked boxes, hand-edited timestamps, and deleted steps. Only revision
   against the anchors changes section 4 while leaving the director's live
   state elsewhere untouched. This is the concrete reason "re-run edit-brief"
   is not a substitute.
3. **The version trail.** A fresh run is always `version: 1` with no memory of
   why anything changed. F&I's next run consumes the trail — the first agent
   whose primary inputs include its own prior output.
4. **Lesson distillation.** Storage (`UserKnowledgeStore` propose→confirm) and
   consumption (edit-brief reads `user_knowledge` every run) exist; nothing
   *produces* feedback-derived lessons. Distillation is a byproduct of
   diagnosis, so it lives here.

Why revision is the spine and not learning: learning has no standalone surface
(distillation's input *is* the diagnosis — revision can exist without learning,
not vice versa); revision is the obligate output of every run while a lesson is
occasional; the spec's stated purpose is revision-shaped ("translates feedback
into specific actionable changes"); and F&I's learning contribution is only the
distillation step where its revision contribution is the entire pipeline.

Tier 1 verbatim: no DaVinci API, no automated editing. Every recommended action
executable in Resolve free per `editing_toolset` (retrieved, never hardcoded),
with the upgrade-flag convention.

## Versioning mechanics (resolved — the question edit-brief deferred here)

**In-place patch + snapshot archive + version log inside the brief.**

- The live brief stays at its canonical path, revised by targeted patch;
  `version` bumps in frontmatter. One live file — single-version-of-inputs.
- Before patching, F&I snapshots the current file to a **`versions/` subdir
  next to the brief** (`versions/edit-brief.v{N}.md`). Snapshots are F&I's
  prior-version inputs; the director never works in them.
- The version log is a `## Version log` section in the live brief: per entry —
  version, date, feedback verbatim, anchors touched, summary of changes,
  mapping resolutions, and any checked steps the revision invalidated.
  Director-visible, travels with the document.
- New-file-per-revision was **rejected**: it forks the director's working
  document and breaks single-version-of-inputs.

## Feedback input contract (resolved)

- **Arrival:** inline text or file — `revise BRIEF.md "feedback"` for quick
  items, `--feedback FILE` for session notes; combinable. No interactive mode
  in v1 (the orchestrator is the conversational layer).
- **Batch, one run = one version bump.** Several notes processed together yield
  one coherent revision and one log entry, not N micro-versions.
- **Mapping:** the LLM resolves perceptual references ("the drop," "the
  bridge") against the brief's section names, timestamps, beat grid, and script
  content. **Ambiguity surfaces, never guesses** — unmappable items are listed
  as unresolved and left unapplied (the stack's no-silent-guess rule). Mapped
  items state their resolution in the log ("'the drop' → `#what-you-get-back`
  @ 01:13.700") so wrong mappings are visible and correctable.

## Revision scope and mechanics (resolved)

- **Patch anchored sections, never re-render.** Re-rendering from a model
  cannot know the director's hand edits. F&I parses the live brief by its
  structure (frontmatter, timeline table, anchors, checkbox steps, version
  log) and surgically edits only touched sections/rows.
- **The LLM never produces a number** (edit-brief's rule, inherited). Timing
  shifts are recomputed in code — a small time-shift engine recomputes affected
  timeline rows and downstream boundaries. The LLM rewrites step text and
  produces the diagnosis only.
- **Director state within a touched section:** untouched steps keep their
  checked state; modified or new steps land unchecked (changed step = new
  work); the log names any checked steps the revision invalidated.
- **Dependency rule: no edit-brief import.** F&I imports only `agent-runtime`
  and treats the brief as a foreign artifact, parsing the markdown by its
  anchors — the same decoupling treatment edit-brief got. The brief's format is
  the contract. The duplicated-format-facts risk feeds the existing shared
  "collection contracts" module idea on edit-brief's v2 list (revisit list, not
  Phase 1/2 scope).

## Learning mechanism (resolved)

- **Stored unit:** a declarative preference lesson ("VO should duck under music
  in every mix") with provenance — source project, feedback verbatim, date.
- **Write path: `user_knowledge` via propose→confirm, domain
  `editing_preference`. No owned collection.** The concept-script test passes
  only this way: the named retrieval consumers already exist (edit-brief reads
  `user_knowledge` every run; F&I reads it when diagnosing). An owned
  collection would have no reader without new integration work.
- **Scoped vs. durable boundary:** a statement referencing this project's
  content ("the bridge," "section 3") is a project-scoped fix — revision only,
  never stored. A craft/taste rule that would hold for the next project is a
  lesson candidate. Propose→confirm is the backstop: the director gates every
  write, so over-generalization dies at the gate.
- **Cadence:** lesson proposals are emitted at the end of a `revise` run — no
  separate verb; distillation taps the diagnosis the run already produced.

## Knowledge grounding (resolved): edit-brief's line, verbatim

Retrieval composes `technique_research_outputs`, `tutorial_research`, and
`user_knowledge` with the established 1.25× `user_knowledge` boost;
`editing_toolset` always loaded — every recommended action checked against
Resolve free with upgrade flags. Query construction is **feedback-driven**: the
diagnosis ("VO competing with music") drives retrieval (ducking/sidechain
findings, Fairlight steps), not the section text. **Read-only v1, no mid-run
delegation** — a knowledge gap becomes a named notation ("run
technique-research on X, then re-revise"); orchestrator chaining is the first
answer if gap-friction proves real (already on the stack's radar).

## CLI surface and budget (resolved)

```
feedback-iteration revise BRIEF.md "feedback text" [--feedback FILE] [--max-cost N] [--dry-run]
```

- **One generative verb, `revise`** — brief path positional; prior versions and
  the log discovered from it. Feedback inline and/or `--feedback FILE`.
- **`--dry-run` is the free op:** parse + validate the brief (anchors,
  frontmatter, version state, snapshot plan) and echo the parsed feedback items
  — no LLM, no writes (mirrors `edit_brief_discover`'s no-LLM rule).
- **Budget:** child-budgeted `--max-cost`; expected cost in edit-brief's range
  (~$0.10) — diagnosis/mapping and step rewriting are the only LLM work; all
  arithmetic is code.
- **Orchestrator wrapping (Build Session 2, per the edit-brief precedent):**
  `feedback_revise` child-budgeted, `feedback_inspect` free (the dry-run).
  Claude-only spend → wrappable. **No `search_knowledge` registry entry** — F&I
  owns no collection (lessons live in `user_knowledge`); the stateless-label
  precedent applies for delegation recording.

## Research signals

**None.** Confirmed — the agent reasons over an existing artifact and existing
collections; no new third-party API. Nothing surfaced during the design
conversation.

## Revisit list (adjacent, not Phase 2 scope)

- Shared read-only "collection/artifact contracts" module in `agent-runtime`
  (already on `docs/v2-refinements/v2-refinements-edit-brief.md`) — F&I's brief parser adds a
  second consumer of duplicated format facts, strengthening the case.

## First build session scope (Build Session 1 of Phase 2)

1. `packages/feedback-iteration/` scaffold — imports only `agent-runtime`.
2. Brief parser (the foreign-artifact reader): frontmatter, timeline table,
   anchors, checkbox steps, version log.
3. Time-shift engine — pure code, fully unit-tested (the edit-brief
   time-engine precedent).
4. Snapshot + version mechanics: `versions/` subdir, frontmatter bump, log
   entry.
5. The `revise` turn end-to-end: feedback parse → LLM mapping/diagnosis →
   targeted patch → lesson proposals via propose→confirm → standard run report.
6. `--dry-run` free op.
7. Smoke: revise the real `script-draft.edit-brief.md` with sample feedback,
   including one deliberately ambiguous item to exercise surface-don't-guess.

Build Session 2: orchestrator wrapping (`feedback_revise` / `feedback_inspect`)
per the `edit_brief_draft` / `edit_brief_discover` precedent.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of
`ai-director-agent-system.md` (single-version-of-inputs, treat as senior
programmer, terminal-first, decisions-with-reasoning, no timelines). Not
restated here.

## Phase 2 scope discipline and end condition

Build to MVP exactly as scoped above — no redesign, no scope additions;
adjacent ideas go to a `docs/v2-refinements/v2-refinements-feedback-iteration.md` deferred
list with reasoning. End condition: the `revise` turn runs end to end against a
real brief with the smoke recorded, the time-shift engine and brief parser are
unit-tested, the suite is green, and a Phase 2 handoff documents what shipped,
verification, and deferred items.
