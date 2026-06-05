# Handoff: voiceover-direction agent — Phase 2

**Status:** Phase 1 (design and discovery) complete. No code written. Ready for Phase 2 (implementation).
**Predecessor work:** music-curation (complete), agent-runtime (complete), tutorial-research (complete), yt-intelligence-pipeline (complete).
**Date:** 2026-06-03

---

## Read this first

Phase 1 resolved the agent's design through a worked design conversation. This document carries every conclusion forward so Phase 2 can begin without re-deriving them. Phase 2 opens against a knowledge base that the between-phase research gathering has populated (see the research-signals artifact); if that gathering wasn't done, the agent still runs but with thinner first-use knowledge.

The design questions are settled. Phase 2's job is to build, in the order below.

---

## The central decision (everything hangs off this)

ElevenLabs **inverts** music-curation's cost structure. In music-curation, emitting the prompt was free and the scarce/external step was running it in Suno. Here it's reversed:

- **Direction** (choosing text, emotion tags, voice, pacing) is LLM-only — cheap, infinitely iterable.
- **Generation** (the ElevenLabs call) burns the monthly character budget — scarce.

So a "turn" is **direct freely until the direction is settled, then spend characters on generation as a deliberate commitment.** Iteration lives in direction, never in generation. Generating-to-explore is the waste mode the budget rules out.

**Lifecycle is split:** `generate` produces audio + a take record and exits; the reaction is recorded later by a separate command. (The *API* is synchronous, but the human listening step isn't — you generate, go listen, then react.)

**Persisted value:** the direction decisions that worked, and the takes themselves.

---

## Design decisions (with reasoning)

| # | Question | Decision | Reasoning |
|---|---|---|---|
| Central | What is a turn / what persists | Direct (free, iterative) → generate (paid, deliberate) → react (separate command). Persist takes + direction lessons. | Budget inversion vs. music-curation. |
| 1 | Memory types | **Two vector types** (`take`, `direction_lesson`) + a **voice registry** (not a vector type). `project_id` + `domain` are payload fields, not types. **No `persona` type.** | Single narrator across many topics ≠ multi-character. Voices are a bounded enumerable set you pick from, not semantically retrieved; the "which voice for what" intelligence emerges from takes/lessons. |
| 2 | `user_knowledge` + cold start | Seed from **vendor docs** → `user_knowledge` (`domain="elevenlabs_mechanics"`, `source_type="documentation"`, `confidence=high`) **and** **tutorial-research** → `tutorial_research`. Retrieval mirrors music-curation (three collections in parallel, `user_knowledge` score-boosted). | Docs are authoritative for mechanics; tutorials carry direction judgment. Cold start makes both live. |
| 3 | Character budget | **Two orthogonal budgets.** Per-run Claude cost stays in `BudgetEnvelope`; the **monthly ElevenLabs character budget never goes in `BudgetEnvelope`.** Source of truth = **vendor, queried** (not a local counter). **Soft-inform** at the pre-generation moment (cost + remaining, `--yes` to skip). Characters consumed recorded as a span attribute. | A monthly vendor quota is not a per-run cost envelope. Local counts drift because you also generate in the ElevenLabs UI. ElevenLabs already hard-enforces the limit, so the agent informs rather than gatekeeps. |
| 4 | Workflow shape | **Direction is whole-script; generation is section-scoped.** A `take` carries `section_id`, `project_id`, `parent_take_id` (section-scoped lineage — music-curation's chain concept reshaped per section). Loop: generate section → listen → react → if needed re-direct + regenerate (new take under same section) → advance. Bulk "generate all" exists for trusted direction. | Pacing/arc are script-level; budget discipline is section-level. |
| 4b | Input format | **Markdown with headings.** Each heading is a section; body is that section's prose; section identity comes from the heading. The agent consumes this whether a human or the (planned) scriptwriting agent produced it. | Matches the stack; usable cold; lines the two agents up later without depending on an agent that doesn't exist yet. |
| 5 | Delegation to tutorial-research | **No in-agent `research` command in this build.** Direction/generation **never** trigger research inline (it would break the fast free loop); at most they flag thin knowledge. The agent reads `tutorial_research` (populated externally); you run tutorial-research directly if needed. | Cold-start gap is closed between phases, not at runtime. Music-curation shipped v1 this way. Reduces scope. Reference-to-voice-style research is deferred (music-curation's structured-references analog). |
| 6 | CLI surface | Falls out of the workflow (sketch below). Fixing a bad section = **option B**: note the problem on `report`; the next `generate` folds in re-direction and shows the revised markup + cost at the approval gate before spending. | One combined step, still gated by soft-inform; nothing pays blind. |
| 7 | Output format | `direct` writes a **real, editable directed-script file** (markdown, headings preserved, tags inline, small per-section metadata). `generate` produces: audio file + a **`take` record** (`status="pending"` until reacted to) + an on-screen result (take id, audio path, character cost, remaining budget). | Editable file fits the file/markdown workflow and pairs with option B (you can hand-tweak a tag). History lives in the take chain, so the directed file can be overwritten as you go. |
| 8 | Voice library | Catalog **synced from ElevenLabs** via `voice sync` (stock + cloned voices, with their labels/description). No hand-entry, no separate voice-annotation command (a `lesson add` with the voice attached covers "this voice is good for X"). **Voice cloning is out of scope** — done in ElevenLabs; `voice sync` picks clones up once they exist. | Vendor is source of truth (same as the budget). Agent is a director, not a voice creator (parallels authorship being out of scope). |

---

## Memory model

All in the `voiceover_direction_memory` Qdrant collection, discriminated by `memory_type`:

| Type | Embedded text | Key payload fields |
|---|---|---|
| `take` | the section text sent to ElevenLabs | voice_id, model, generation params, emotion tags, character_count, audio_path, reaction, rating, status, section_id, project_id, domain, parent_take_id, chain_root_id |
| `direction_lesson` | the statement | valence, scope (e.g. voice / pacing / tone), confirmed |

**Voice registry** — structured records, **not** a vector type: voice_id, name, category (stock/cloned), labels, description. Synced from the ElevenLabs voices endpoint.

**ElevenLabs mechanics facts** live in `user_knowledge` (`domain="elevenlabs_mechanics"`), runtime-owned, unchanged from the established pattern.

---

## CLI surface (sketch)

Working a script:
- `voiceover-direction direct <script.md>` — whole-script markup → editable directed-script file. Free, re-runnable.
- `voiceover-direction generate --section <id>` / `--all` — section audio. Soft-inform cost gate. Folds in re-direction when the section's last take carries a `report` note (option B). Writes audio + pending take + result.
- `voiceover-direction report <take_id> --reaction <X> [--rating N] [--notes ...] [--context ...]` — record reaction; flip pending → complete.
- `voiceover-direction review-pending` — takes awaiting a reaction.
- `voiceover-direction recall "<query>"` — search prior takes + direction lessons.

Direct writes:
- `voiceover-direction lesson add "<statement>" [--valence ...] [--scope ...]`
- `voiceover-direction fact add "<statement>" --domain elevenlabs_mechanics`

Knowledge + voices:
- `voiceover-direction knowledge ingest-docs <folder>` — ElevenLabs docs → `user_knowledge` (thin surface over `UserKnowledgeStore.bulk_load_verified`; same pattern as music-curation's spec).
- `voiceover-direction voice sync` — pull available voices into the registry.

Reaction vocabulary: adapt music-curation's, keeping the `disliked` (aesthetic — weigh against the direction) vs. a tag/render-failure distinction (the direction was fine, the render wasn't — surface the prior as structure to learn from). Settle the exact set during the `report` build.

---

## Phase 2 build sequence

Ordered and grouped for efficient implementation; no schedule implied.

**1 — Foundation (everything depends on this).**
- `VoiceoverDirectionStore` wrapper over `MemoryStore`, owning `voiceover_direction_memory` (the two types) and the voice registry.
- Pydantic models: `Take`, `DirectionLesson`, `VoiceProfile`, `VoiceoverResult`, the directed-script representation.
- Markdown section parser (heading-based; regex + section heuristics, same approach as seed/docs ingest — no LLM extraction).
- ElevenLabs client wrapper — read-only first: list voices, subscription/usage query. (TTS call lands with generation.)

**2 — Direction (the free loop, first user-facing capability, no API cost to test).**
- Retrieval composition across `voiceover_direction_memory`, `user_knowledge` (boosted), `tutorial_research`.
- `direct` command + the directed-script file read/write format.

**3 — Generation (the paid step).**
- TTS call on the ElevenLabs client.
- `generate`: section-scoped, soft-inform cost display (local char count + vendor remaining), option-B re-direction fold-in, writes audio + pending take + result. Characters-consumed span attribute.

**4 — React + inspect.**
- `report` (reaction vocabulary, notes/context, pending → complete), `review-pending`, `recall`.

**5 — Direct writes + knowledge + voices.**
- `lesson add`, `fact add`.
- `knowledge ingest-docs` (depends on docs being collected — between-phase signal A).
- `voice sync` (depends on the ElevenLabs client from step 1).

**First build session lands step 1** — the foundation is testable in isolation and unblocks everything. Step 2 (`direct`) is the natural second slice: first user-facing capability and free to exercise. Generation follows.

---

## Constraints carried forward

- Two orthogonal budgets; the ElevenLabs character budget never enters `BudgetEnvelope`.
- Vendor is source of truth for both character usage and the voice catalog — query, don't cache-and-drift.
- Direction never triggers research inline.
- Single narrator; `persona` is out.
- Prose is an input; authorship belongs to the planned scriptwriting agent.
- Cold start: the agent must be useful from the first `generate`; knowledge accumulates from there.
- `eleven_v3` is the expressive, audio-tag-capable model; per ElevenLabs' own docs, PVC clones were not fully optimized for v3 at design time — relevant to voice-selection guidance, and a fact the docs ingestion should capture.
- TTS is billed one credit per character, monthly reset, rollover up to two months — this is the shape of the "monthly budget" the soft-inform reflects.

---

## Deferred (not Phase 2 — open later if the need is real)

- In-agent `research` command + reference-to-voice-style research (music-curation's structured-references analog).
- `persona` memory type (only if multi-character work ever starts).
- Conversational chat mode (agent-runtime v2 capability; would apply here eventually).
- Any non-interactive `--decisions`-style batch confirmation for ingestion.

---

## Reference documents to load at the start of Phase 2

- `docs/ai-director-agent-system.md` — system spec (voiceover-direction section, working-relationship rules, build methodology).
- `docs/architecture.md` — full agent-stack architecture.
- `packages/agent-runtime/README.md` — runtime public API (`MemoryStore`, `UserKnowledgeStore`, `BudgetTracker`, delegation, tracing, reporting).
- `packages/music-curation/README.md` — nearest reference for store/retrieval/curated-write/pending-lifecycle patterns (reference, not copy).
- `docs/v2-refinements-music-curation.md` — the Suno-docs-ingestion spec, applied analogously to `knowledge ingest-docs`.
- `docs/v2-refinements-agent-runtime.md` — conversational chat mode (deferred here).
- This handoff + the Phase 1 research-signals artifact.

---

## Foundation state to inherit

- **agent-runtime** complete, 158 tests — `MemoryStore`, `UserKnowledgeStore`, `BudgetTracker`, `BudgetEnvelope`, delegation, tracing, reporting.
- **tutorial-research** complete, 50 tests — reads `user_knowledge` + `tutorial_research`; available for between-phase ingestion.
- **music-curation** complete, 213 tests — pattern reference.
- **yt-intelligence-pipeline** complete, 40 tests.
- Workspace: 461 tests passing across four packages.
