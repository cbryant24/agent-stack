# Handoff: voiceover-direction agent — Phase 1

**Status:** Not yet started. Phase 1 (design and discovery), no code.
**Predecessor work:** music-curation agent (complete). agent-runtime foundation (complete). tutorial-research agent (complete).
**Date:** 2026-06-02

---

## Read this first

We're at the beginning of a new agent build. The next chat will execute **Phase 1** of the `voiceover-direction` agent build — design and discovery. The phased-build methodology that scopes this work is documented in `docs/ai-director-agent-system.md` under `## Build methodology`. Read that section before proceeding; this handoff is specific to voiceover-direction but inherits the general framework from there.

The most important constraint for Phase 1 is the same one that made the music-curation build work:

**Don't write any code. Start by working through the design questions as a real design conversation.** No premature schemas, no premature architecture, no jumping to a build prompt. The shape of this agent is genuinely undetermined right now — its memory model, its workflow primitives, its CLI surface, its relationship to existing collections, and even what "good" looks like for its outputs are all open questions. Phase 1 opens those questions and works through them deliberately.

What worked for music-curation that should work here:

- One central design question opened first, fully explored, before secondary questions
- Each decision recorded with its reasoning, not just its conclusion
- No batteries of small clarifying questions — one targeted question at a time when genuine forks emerge
- Explicit recognition when the user is the only person who can answer something, vs. when the design has a defensible answer Claude should propose

## Phase 1 scope and end condition

Per the `## Build methodology` section, Phase 1's scope is: architecture, technology choices, memory model, workflow shape, CLI surface, and any other design questions specific to this agent. No code is written.

Phase 1 ends when:

1. All design questions are resolved with documented reasoning
2. Phase 2's first build session has a concrete scope proposal
3. All research signals (if any gaps were identified in `tutorial_research` or `user_knowledge`) have been produced — as Claude Code prompts for `tutorial-research` invocations and/or as lists of URLs/topics for manual ingestion
4. The Phase 2 handoff document is drafted

The user then performs the between-phase research gathering (if any signals were produced) as their own activity. Phase 2 opens with a fresh chat against a knowledge base that already has the identified gaps closed.

## What's already known about this agent

The agent is described in `docs/ai-director-agent-system.md` under the "Voiceover Direction Agent" section. Read it. Brief summary of what's anchored there:

- **Purpose framing:** "Same shape as Music Curation but for voice. Reference-driven, iterative, knows the user's voice library. Generates ElevenLabs-ready scripts with emotion direction."
- **Outputs:** Per-section text with ElevenLabs emotion tags, recommended voice profile, direction notes, generated audio.
- **Tools available:** Claude, the runtime memory layer (with a planned `voiceover_direction_memory` collection), ElevenLabs API, and delegation to `tutorial-research`.
- **Cost constraint:** Operates against the ElevenLabs free plan. Design must accommodate this — naive generate-then-iterate burns the monthly character budget fast.

That's it. The system spec deliberately leaves the rest undetermined.

## What's NOT known (and should not be assumed)

Don't assume the music-curation patterns transfer wholesale. Some likely will (the runtime composition pattern, the curated-write principle, the BudgetTracker integration). Some likely won't (the seed-ingestion-first build pattern doesn't apply — there's no seed data; the async-Suno reaction loop doesn't apply — ElevenLabs is synchronous-ish). Some are open.

Specifically: Phase 1 should **not** open with "music-curation had four memory types so voiceover-direction will have four memory types," or "music-curation had X CLI subcommand so voiceover-direction will have the equivalent," or any other transfer-by-assumption. Inherit patterns where they fit by reasoning, not by template.

## Inputs to the build

### No seed data

Unlike music-curation, there is no equivalent of session-summary files to ingest. The user has not used ElevenLabs before; this build starts cold from a memory-data perspective. This is a real constraint that shapes the first-use experience — the agent must be useful from the very first generate call, with memory accumulating from there rather than being bootstrapped.

The first work item for the Phase 1 chat is **not** seed ingestion. It is the design conversation described below.

### Domain context

The voiceovers are for YouTube videos the user is producing — separate from music-curation's domain. There is no expected overlap with Suno, music generation, or the `music_curation_memory` collection. The voiceover-direction agent is its own domain with its own memory.

### ElevenLabs as first-time tool

The user has not yet used ElevenLabs. This means:

- The agent's understanding of ElevenLabs mechanics (voice IDs, emotion tags, model selection, generation parameters, voice cloning, character limits, etc.) will not start from user-verified knowledge. It will start from whatever can be retrieved via `tutorial-research` and `user_knowledge` ingestion.
- The free-plan constraint is real and will shape design choices. Whatever the agent does with the API needs to be character-budget-aware.
- The agent itself may help the user *learn* ElevenLabs through use, the way music-curation was supposed to help with Suno mechanics.

**This is the primary source of research signals Phase 1 will likely produce.** Closing the ElevenLabs-mechanics knowledge gap before Phase 2 begins lets the implementation work against a populated `user_knowledge` collection rather than a cold one.

## The central design question

This is the one to open first, fully explore, before anything else:

**What does a "turn" look like for this agent, and what memory does the user actually need persisted across turns?**

For music-curation, a turn was: user describes musical intent → agent emits a Suno-ready prompt → user runs in Suno externally → user reports reaction → memory accumulates. The async gap between emit-and-react was a primary design constraint.

For voiceover-direction, what's the equivalent shape? Some possibilities, none committed:

- Is a turn one section of script → one generated take?
- Is a turn a full script → multiple takes with direction variations?
- Is the API synchronous enough that "generate, listen, react" happens in one flow rather than asynchronously?
- What counts as a "good" output that the user wants to remember — a voice profile? A specific take? A direction style that worked? A character-emotion mapping?
- How does the free-plan budget constraint shape what gets stored vs. what gets regenerated?

This is the question whose answer determines almost everything downstream: the memory model, the CLI surface, the retrieval pattern, the curated-write boundaries. It deserves its own focused design conversation before any schema gets drafted.

## Secondary questions (do not open until the central one is settled)

These follow from the central question's answer and should be worked through deliberately after, not in parallel:

1. **Memory types in `voiceover_direction_memory`.** What's the analog of music-curation's generation/template/taste/sound_reference? Likely candidates that should be evaluated, not assumed: voice profiles, takes (analogous to generations), direction notes (analogous to taste lessons), character/persona definitions, project/episode groupings. Some of these may not warrant being a memory type at all; some may need to combine.

2. **Relationship to `user_knowledge`.** ElevenLabs mechanics facts go to `user_knowledge` with `domain="elevenlabs_mechanics"` (following the established pattern). What's the seed strategy when there's no user-verified data to start? Ingest from ElevenLabs docs directly (the Suno-docs-ingestion spec in `docs/v2-refinements/music-curation-v2-refinements.md` would apply equivalently)? Rely on tutorial-research delegations to YouTube ElevenLabs tutorials? Both? Whichever choice gets made here likely produces research signals for the between-phase gathering activity.

3. **The free-plan budget constraint as design driver.** ElevenLabs free tier has a monthly character limit. The agent's workflow needs to make this visible to the user (per-turn character cost), avoid waste (don't generate a full script as exploration when a single section would suffice for direction-testing), and possibly track cumulative monthly spend in trace events.

4. **Synchronous-ish API workflow.** Unlike Suno (no API, async-by-necessity), ElevenLabs generation completes within a request. This means the user can listen to a take immediately and react. The async reaction loop from music-curation may not be the right shape — reactions might happen in the same CLI invocation, or the workflow may be section-by-section approval rather than emit-then-react.

5. **Delegation to tutorial-research.** When does voiceover-direction delegate? The three triggers from music-curation (named feature with no local high-confidence hit, "why does X work" with no local theory hit, unfamiliar artist/reference) may not all apply. What are the equivalent triggers for this domain?

6. **CLI subcommand surface.** Don't start by listing subcommands. The CLI shape should fall out of the workflow shape, which falls out of the central design question.

7. **Output format.** What does the agent return? Just the ElevenLabs-bound API request? A locally-saved audio file? Both? A structured `VoiceoverResult` analogous to `MusicResult`? Open.

8. **Voice library bootstrapping.** ElevenLabs has both stock voices (pre-existing) and the ability to clone the user's own. The agent's "voice library" memory needs to accommodate both. How the user populates this — interactive voice-add command? Auto-imported from ElevenLabs API? — is an open question.

## Research signals expected from Phase 1

Because ElevenLabs is a first-time tool with no user-verified knowledge in `user_knowledge`, Phase 1 is highly likely to produce research signals. Anticipated categories (Phase 1 will confirm and refine these based on the design decisions made):

- **ElevenLabs mechanics knowledge** — official docs (help/api.elevenlabs.io), feature explanations, voice library mechanics, emotion-tag syntax, model differences, character-budget rules. Likely a mix of doc-ingestion (URLs Phase 1 will list) and YouTube-tutorial ingestion (Claude Code prompts for `tutorial-research`).
- **Voiceover direction theory** — direction techniques, voice acting fundamentals, character-voice mapping, emotional pacing. Domain knowledge that the agent will draw on. Likely YouTube-tutorial ingestion via `tutorial-research`.
- **Script-to-take workflow patterns** — if applicable based on the workflow shape decided in Phase 1.

Phase 1 should produce the specific signals as concrete artifacts the user can act on between phases:

- For YouTube tutorials: a Claude Code prompt that runs `tutorial-research <topic>` for each identified topic. The user reviews the prompt and runs it.
- For docs/URLs: a list of specific URLs or domains the user retrieves manually, saves as markdown locally, and ingests via the docs-ingestion path. (If the Suno-docs-ingestion CLI subcommand from `docs/v2-refinements/music-curation-v2-refinements.md` is not yet implemented, Phase 1 should note this and propose either implementing it as a small standalone task before voiceover-direction Phase 2, or building the equivalent for voiceover-direction's needs directly.)

If Phase 1 concludes that no research signals are needed (unlikely given the cold-start condition, but possible), it states this explicitly in the Phase 2 handoff and Phase 2 begins immediately.

## What Phase 1 should NOT do

- Propose a memory schema before the central design question is settled
- Lift CLI subcommands from music-curation without justifying each
- Write code
- Assume the workflow shape transfers from music-curation (it likely does not)
- Treat the user as needing background on ElevenLabs — the user knows they haven't used it yet and will learn alongside the agent
- Begin actual research ingestion (that's the between-phase activity, not Phase 1's job)

## What Phase 1 SHOULD produce, in order

1. A worked design conversation on the central question, ending with a stated answer the user has confirmed
2. A worked design conversation on each secondary question, in order, with each answer building on the previous
3. A concrete proposal for Phase 2's first build session — what specifically lands first, what its dependencies are, what's deferred
4. Research signals (Claude Code prompts and/or URL lists) for any knowledge gaps identified — as downloadable artifacts the user can act on between phases
5. A Phase 2 handoff document — downloadable artifact — containing everything Phase 2 needs to begin without re-deriving Phase 1's conclusions. This includes the design decisions reached, the agreed memory model, the agreed workflow shape, the agreed CLI surface (at least at sketch level), the proposed Phase 2 build sequence, and any constraints carried forward.

## Foundation state to inherit

Phase 1 begins on top of:

- **agent-runtime** complete, 158 tests. Provides `MemoryStore`, `UserKnowledgeStore`, `BudgetTracker`, `BudgetEnvelope`, delegation primitives, tracing, reporting. Public API documented in `packages/agent-runtime/README.md`.
- **tutorial-research** complete, 50 tests. Reads from `user_knowledge` and `tutorial_research` collections. Available for delegation and for between-phase research ingestion.
- **music-curation** complete, 213 tests. Establishes patterns for memory ownership, curated writes, retrieval composition, pending-state lifecycle. Reference but do not copy.
- **yt-intelligence-pipeline** complete, 40 tests.
- **Standing rules** in `docs/ai-director-agent-system.md` under "Working-relationship rules". These apply to Phase 1.
- **Build methodology** in `docs/ai-director-agent-system.md` under "Build methodology". This is the phased pattern Phase 1 is the first phase of.

Full workspace: 461 tests passing across four packages.

## Reference documents

These should be loaded as context at the start of Phase 1:

- `docs/ai-director-agent-system.md` — system spec, including the voiceover-direction agent section, the working-relationship rules, and the build methodology
- `docs/architecture.md` — full agent-stack architecture
- `packages/agent-runtime/README.md` — what the runtime provides
- `packages/music-curation/README.md` — the most recently built agent, as a reference for patterns to consider (not copy)
- `docs/v2-refinements/agent-runtime-v2-refinements.md` — including the conversational chat mode spec, which may eventually apply here
- `docs/v2-refinements/music-curation-v2-refinements.md` — including the Suno-docs-ingestion spec which may apply analogously to ElevenLabs-docs-ingestion
- This handoff document

## One open question for the user before opening Phase 1's design conversation

There is one thing the user should answer in their first message to the Phase 1 chat, because it shapes the very first turn of the central design conversation:

**What's the immediate use case? A specific YouTube video the user is producing now, or a more general "I want to use ElevenLabs for upcoming videos"?**

If specific: the design conversation can ground itself in a real script, a real voice need, a real production context. That makes the design questions concrete instead of abstract.

If general: the design conversation has to work at the level of "what does any voiceover project look like" without a concrete anchor. Still doable, but the design choices will be more speculative until the first real project surfaces them.

Either is a valid starting point. Both shape the conversation differently.
