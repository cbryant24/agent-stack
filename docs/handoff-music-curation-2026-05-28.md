---
title: "agent-stack Handoff — Music Curation Agent"
date: 2026-05-28
type: handoff
project: agent-stack
status: active
purpose: resume-context-for-music-curation-build
phase_completed: tutorial-research-agent
phase_next: music-curation-agent
tags:
  - handoff
  - agent-stack
  - music-curation
  - context-transfer
---

# agent-stack Handoff — Music Curation Agent

This document is the load-bearing context for building the **music-curation** agent in a fresh conversation. It is paired with three authoritative reference documents that should be loaded alongside it:

- `docs/ai-director-agent-system.md` — the system-level spec for the whole agent ecosystem (this is the source of truth for *what music-curation is for*)
- `docs/architecture.md` — the runtime and package design / API reference
- `README.md` — workspace overview

Read this handoff first, then those three. This handoff does not re-derive the reasoning behind settled decisions; it conveys what's done, what's decided, what's genuinely open, and where to start.

A note on how to use this document: it is deliberately front-loaded with the open design questions, because the central work of the next session is **design, not implementation**. Do not write code until the memory model is worked through (see "The central open question"). The prior tutorial-research build went well precisely because the design conversation happened before any code; repeat that.

---

## Who the user is, and how he works

A programmer with 8+ years of experience. He is the **director** of this agent system — he makes creative decisions, provides taste, approves outputs. The agents handle research, generation, organization.

Working environment: iTerm2 with zsh on an M1 MacBook. He uses Claude Code for development, this chat interface for research/design/decisions, and Cowork for scaffolding.

How he wants to be worked with (this matters — it shaped the successful tutorial-research build):

- **Decisions with reasoning, not menus of clarifying questions.** He finds an interrogation of many small questions overwhelming. Make a decision, explain why, and invite pushback. When something is genuinely a fork that depends on his preference (not on information you can infer), ask *that one thing* clearly.
- **No timelines, no week-by-week breakdowns.** Order work by dependency and what's efficient to build together, never by calendar.
- **He is not a beginner.** Give him what works best, not what's easiest. Don't over-explain fundamentals.
- **Terminal-first.** Prefer CLI/script solutions. When more context would help a chat answer, suggest a command he can run to gather it.
- **Claude Code prompts** should include: a brief goal/expected-outcome, whether to start in plan mode or go straight to implementation, relevant file references (`@` syntax), and the prompt itself in a code block.
- **Real-world testing surfaces real bugs.** The tutorial-research build was validated by running it against live APIs, which caught four bugs that the mocked test suite couldn't. Expect the same here; budget for a smoke-testing pass after the build.
- **Single-version-of-inputs rule.** Anything the user will paste, copy, type, or act on
elsewhere appears exactly once in the chat, in its final form. Refinements, improvements,
alternate phrasings, or "actually, better:" versions of the same input do NOT appear in
the same message as the original — by the time the refinement arrives, the user may have
already acted on the first version, making the refinement either wasted or actively
disruptive.

  If a better version occurs while composing: use it directly, don't show the worse one.
If a better version occurs after sending: send a separate, clearly-marked follow-up
message ("Use this instead of what I sent above:") before the user has acted.

  This rule applies to: Claude Code prompts, CLI commands the user will run, edited text
for confirmation flows, message drafts, configuration values, scripts, file contents,
or anything else the user will transfer out of chat. It does NOT apply to:
explanations, reasoning, or analysis the user reads but doesn't act on — those can
be revised in-message normally.

  Genuine forks where the call depends on user preference (e.g., "interactive vs.
scripted") are not refinements; presenting both with their tradeoffs is correct.
Refinements of the same recommendation are not forks and should not be presented as
options.

---

## What music-curation is (from the director spec — settled, do not re-debate)

Music-curation is **a music-theory expert and creative partner with persistent memory, helping craft Suno prompts grounded in real musical understanding.** It is reusable across video projects, podcasts, and standalone music exploration — not anime-mashup-specific.

The concrete problem it solves (the user has made 100+ tracks with Claude + Suno):

1. **No continuity between sessions** — every fresh Claude conversation started from zero; prompts that produced loved music weren't retained, so good sounds couldn't be reliably reproduced or iterated on.
2. **Inconsistent output from drifting prompts** — without a record of which prompt produced which result, new prompts couldn't match previous wins.
3. **Misunderstandings about Suno itself** — Claude conversations sometimes got Suno's interface, features, and prompt syntax wrong.

Persistent memory targets (1) and (2); accurate Suno knowledge (kept fresh via tutorial-research delegations) targets (3).

What it must be good at:
- Persistent memory of the user's taste and what he's generated, across sessions
- Genuine music-theory reasoning — *why* a sound works and how to push it
- Accurate, current Suno prompt vocabulary, tags, and features
- Translating references (songs, artists, films, scenes) into Suno prompts targeting the right musical territory
- A prompt → result → reaction record so good directions are reproducible

**Hard external constraint:** Suno has no public API. The agent generates prompts; the user runs them in Suno manually and reports back the result and his reaction. This is not a design choice and not subject to change.

**Settled architectural decisions** (inherited from the director spec and the runtime, all proven by tutorial-research):
- Standalone, independently invokable agent (CLI + library now, MCP later). Not part of any project workflow.
- Built on `agent-runtime` — uses `BudgetTracker`, `TracePersister`, `MemoryStore`, `render_run_report`, delegation. Does not reimplement runtime concerns.
- Owns the `music_curation_memory` Qdrant collection. Can read other collections (notably `tutorial_research`).
- Delegates to **tutorial-research** via `delegate()` for music-theory and Suno-feature knowledge gaps.
- **Memory is curated, not auto-harvested.** The agent asks before storing, or stores explicit user inputs. It does NOT vacuum the user's personal vault. This is a privacy boundary, enforced by design.
- Claude (Sonnet 4.6) for reasoning/generation; Claude (Haiku 4.5) for any cheap scoring. Voyage embeddings, Qdrant, OTel/Jaeger — same stack as everywhere.

---

## THE CENTRAL OPEN QUESTION: the memory model

This is the heart of the build and the reason the design conversation must happen before code. **Do not propose a schema and start building. Work it through with the user first**, the way tutorial-research's scoring/synthesis/plan questions were worked through at the start of that build.

The user has provided seed material: structured markdown "session summary" files, each documenting a complete Suno session he ran with Claude's help. These files are **far richer than "old prompts"** — and that richness is what makes the memory model a real design problem rather than a trivial ingest.

### What the seed files actually contain

Reviewing representative files (lo-fi EDM, hip-hop/phonk, Junya-Nakano-style JRPG), each file contains **at least four distinct kinds of information** that very likely do not belong in the same memory shape:

1. **Generation entries.** Individual prompts, each with a Suno *style-of-music field* (the long comma-separated descriptor string) and usually a separate *lyrics field* (with `[bracket]` structure tags). Many carry an explicit reaction. This is the prior-generation log the director spec anticipated.

2. **Reactions — richer than expected.** Not a 3-value vocabulary. Observed: loved (✅ "USER LOVED THIS"), approved/liked, liked-but-wanted-changes (⚠️), disliked (❌), and *copyright-blocked* (an outcome, not a taste judgment — a short phrase tripped Suno's copyright filter). Reactions attach to individual prompts.

3. **Suno-mechanics facts.** Hand-learned, firsthand-verified knowledge about how Suno behaves: short phrases can trip the copyright filter; ellipses/repeated-letters force syllable elongation; the style field has a ~1000-character limit; language specifiers (`french lyrics`) go in the *style* field; `(parentheses)` are for ad-libs/backing vocals; surrounding `[Hook]` with `[Instrumental]` creates sparse vocals; "NEVER use artist names — translate qualities instead." **This overlaps with what `tutorial_research` already holds from YouTube ingestion**, but it's more authoritative because the user verified it directly.

4. **Reusable templates.** Parameterized base prompts with explicit swap variables (`[BPM]`, `[vocal descriptor]`, `[language if needed]`). Neither taste nor mechanics — reusable scaffolds.

And, threaded through the files, a fifth thing worth treating distinctly:

5. **Durable taste lessons.** Session-level "what worked vs. didn't" aggregations — e.g., the phonk file's explicit record that the user *loved* heavy-bass / Memphis-cowbell / raw-underground and *disliked* polished-orchestral / Metro-Boomin-cinematic / Asian-melodic-instruments. This is standing cross-session preference, not tied to one generation — arguably the single most valuable signal for giving the agent continuity.

### Why this is a design problem, not an ingest script

The director spec's memory model (its "Memory model" section) only anticipated category 1 plus loose taste/reference commentary. Categories 2–5 are all present in the real seed data. The open questions:

- **How many memory shapes / collections?** Do generation entries, taste lessons, Suno-mechanics facts, and templates share one `music_curation_memory` collection (differentiated by a `memory_type` payload field and filtered on retrieval), or split across collections? One-collection-with-tags was the right call for tutorial-research; whether it holds here is genuinely open.
- **Where do the Suno-mechanics facts (category 3) live?** Three candidates: (a) `music_curation_memory` as a `memory_type="suno_fact"`; (b) folded into `tutorial_research` alongside the video-derived Suno knowledge (but they're user-authored, not tutorial-derived, and more authoritative — does that distinction matter?); (c) a dedicated collection. This decision interacts with the delegation question below — if mechanics facts live where tutorial-research can see them, the line between "ask my memory" and "delegate to tutorial-research" shifts.
- **What gets embedded vs. stored as structured payload?** For a generation entry, the style-field text is the natural thing to embed (so "find prompts like this" works). But BPM, language, reaction, and the what-changed delta are structured fields better stored as payload and filtered, not embedded. Getting this split right determines whether retrieval is actually useful.
- **How are the evolution chains preserved?** The files contain iteration paths (V1 → refined → slowed → multilingual, with *why* each step changed and what it produced). This is the reproducibility data. Is a chain a first-class structure (linked entries with parent references), or is it flattened into independent entries that happen to share a session ID? Reproducibility — the user's #2 pain point — depends on this.
- **Granularity of reactions vs. taste.** Reactions attach per-prompt (category 2); taste lessons aggregate per-session (category 5). Two different granularities. Does the agent store both, derive one from the other, or ask the user to confirm aggregated taste explicitly?

### Suggested shape of the design conversation (not the answer)

Work these in roughly this order with the user: (1) enumerate the memory types and agree which are first-class; (2) decide collection topology (one vs. several); (3) for each type, decide embed-target vs. structured-payload fields; (4) decide how evolution chains are represented; (5) only then design the seed-ingestion parser that turns these structured markdown files into memory points. The seed-ingestion design is *downstream* of the schema, not the thing that drives it.

A reasonable default to react against (the user explicitly does NOT want this committed in the handoff — it's a starting point for discussion): single `music_curation_memory` collection, `memory_type` payload field discriminating {generation, taste, suno_fact, template}, style-field text embedded for generation/template types, taste and suno_fact embedded on their statement text, structured payload for BPM/language/reaction/reference/chain-parent. But the whole point of the next session is to interrogate whether that's right given the real data.

---

## The other open design questions

These are secondary to the memory model but need answers during the build. None has an obvious right answer.

**Output shape.** The director spec says outputs are: Suno prompts with style-tag breakdowns, music-theory reasoning explaining the choices, cross-references to similar prior generations, and a logged generation entry once the user reports back. Open: the prompt output should mirror Suno's actual two-field structure (style field + lyrics field) since every seed file does. How structured should the `MusicResult` model be? Does it return one prompt or several variants (the seed files routinely explored multilingual / multi-BPM variants of one idea)?

**Input-discovery mechanism.** The director spec is explicit and unusual here: the user does *not* yet know the full set of inputs that would serve this agent best, and **wants the agent (and its design) to actively surface inputs he hasn't thought of.** Known starting points: mood/vibe, reference tracks/artists/films, optional brief from Concept & Script. Candidates to discover: key/tempo preferences, structural intentions, instrumentation wishes, emotional arc, references to his own prior tracks. The design question: how does the agent elicit and suggest useful inputs without becoming an interrogation (which the user dislikes)? This is a genuine UX design problem, not just a field list.

**Curated-write flow.** Memory is curated-not-harvested — the agent asks before storing. What's the actual mechanic? After a generation is logged, does the agent propose a memory entry and ask for confirmation? Does the user explicitly invoke a "remember this" command? How does the prompt→result→reaction loop get closed in a CLI/library context where the user runs Suno *between* turns (he generates the prompt, leaves to run Suno, comes back later to report the result)? The asynchronous nature of the Suno step is a real interaction-design constraint.

**Delegation-trigger logic.** When does music-curation decide it has a knowledge gap worth a tutorial-research delegation, versus answering from its own music-theory reasoning + existing collection? Over-delegating wastes budget and time; under-delegating reproduces the "Claude gets Suno wrong" problem. This interacts directly with where the Suno-mechanics facts live (see central question). Worth defining concrete trigger conditions rather than leaving it to model judgment alone.

**Invocation surface.** CLI + library to start (MCP later, per system-wide pattern). But the interaction model is less of a one-shot than tutorial-research — music-curation is conversational and iterative by nature (refine this prompt, try a slower version, now in French). Does the CLI support a session/REPL mode, or is each invocation one-shot with memory providing continuity? This affects the whole agent shape.

**Budget profile.** tutorial-research defaulted to `max_items=5, max_depth=0, max_cost_usd=2.00, max_wall_time_sec=900`. music-curation's cost profile is different — it's Sonnet reasoning + occasional Haiku + possible delegation, not video ingestion. Set defaults appropriate to its actual work. It will also be *delegated to* less than tutorial-research but *delegates out* to tutorial-research, so `max_depth` needs to be > 0 (unlike tutorial-research's 0).

---

## What's done in the broader system (current state)

### agent-runtime — complete, 133 tests passing

Stable, the shared foundation. Public API as documented in `architecture.md`. The pieces music-curation will use directly:
- `get_config()` / `reset_config()` — config singleton
- `BudgetTracker` — async context manager every run wraps itself in; now correctly counts tool calls (see bug-fix note below)
- `@traced`, `record_*` helpers, `TracePersister` — tracing; custom domain events emitted as `event_type="info"` with a `metadata.event_subtype` discriminator (this is the established pattern — music-curation should follow it)
- `MemoryStore` — text (`upsert_points`, `search`) and multimodal methods, plus filter helpers (`filter_by_source_type`, `filter_by_domain_tags`, `filter_after`)
- `delegate()` — derives child budget, enforces depth, debits parent automatically; this is how music-curation calls tutorial-research
- `render_run_report()` — renders the Obsidian Markdown run report; now raises `FileNotFoundError` on a missing trace rather than silently returning a bogus path (bug-fix note below)

**Runtime bug-fixes that landed during the tutorial-research build** (relevant because music-curation depends on the same runtime, and because the architecture doc's "no known design issues" claim predated these):

1. **Path expansion** — `RuntimeConfig` now expands `~` in path fields (`agent_data_dir`, `agent_reports_vault`) via a field validator. Previously stored the literal `~/...` string, which broke trace persistence silently. If you set path env vars with tildes, they now work.
2. **Renderer failure mode** — `render_run_report` raises `FileNotFoundError` (with the checked path) when the trace doesn't exist, instead of returning a success-looking path for a file it never wrote.
3. **Tool-call counting** — `record_tool_call` now bridges to the active `BudgetTracker` via the contextvar, so `consumption.tool_calls` increments correctly. Previously the run-end summary reported `tool_calls: 0` while the trace clearly showed tool calls.
4. **Partial-status logic** (tutorial-research level) — a run is `completed` if no item-processing exception fired, regardless of items-vs-budget; `partial` only when an attempted item fails or budget is exhausted mid-run. Worth mirroring this explicit logic in music-curation rather than re-inventing.

A latent runtime item worth knowing (not yet fixed, deliberately deferred): `notify_budget_threshold` does not auto-fire from `BudgetTracker.check_budget` — tutorial-research calls it explicitly with a `TODO(agent-runtime)` marker. The clean fix is to move the threshold notification into `BudgetTracker` so every agent gets it for free. **If music-curation wants threshold notifications, this is the moment to consider doing that runtime fix properly** (it's now the second agent that would benefit, which is the bar for justifying the change). Coordinate with the user before touching the runtime.

**Day-one gotcha — Anthropic (and other SDK) client construction.** This will trip up music-curation's very first LLM call if not known up front. `pydantic-settings` loads `.env` into `RuntimeConfig` fields but does **not** inject values into `os.environ`. The Anthropic SDK's `AsyncAnthropic()` reads `os.environ` directly, so constructing it with no arguments fails to authenticate even when the key is correctly set in `.env`. Always construct as:

```python
from agent_runtime.config import get_config
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=get_config().anthropic_api_key)
```

The same applies to any SDK that reads credentials from the environment (Tavily, Voyage AI, etc.) — pass the key explicitly from `get_config()` rather than relying on env-var injection. This is documented in `architecture.md` under tutorial-research's "Known runtime gaps," but it's a workspace-wide rule, not a tutorial-research quirk.

### yt-intelligence-pipeline — complete, 40 tests passing

The canonical YouTube ingestion capability. music-curation does not call it directly — it delegates to tutorial-research, which calls the pipeline. No direct interaction expected.

### tutorial-research — complete, 41 tests passing

The agent built in the prior chat. music-curation **delegates to this** for music-theory and Suno-feature knowledge gaps. What you need to know to delegate well:

- Library entry: `from tutorial_research import research, research_sync` → returns a `ResearchResult` (fields: `request_type`, `status`, `plan`, `ingested`, `retrieved`, `synthesis`, `report_path`, `cost_usd`, `items_processed`).
- Modes: `research` (discover + ingest + synthesize), `ingest` (directed URLs), `retrieve` (query existing knowledge, no ingestion). For a knowledge-gap delegation, `retrieve` mode against the existing collection is usually what you want first — it's near-free (embedding-only) and may already have the answer before you spend on ingestion.
- It owns `tutorial_research`. music-curation can also query that collection *directly* via `MemoryStore.search` without delegating, when it just needs retrieval rather than the full research loop. Deciding between "direct retrieve" and "delegate to tutorial-research" is part of the delegation-trigger design question above.

### The tutorial_research knowledge base — already seeded for you

This is a significant head start. The collection has **564 points** across ~30 videos, spanning exactly what music-curation needs:

- **Suno mechanics**: features, tags, syntax, song structure, audio uploads, stems, cover art, remix tools, v5/v5.5 capabilities, custom voices
- **Music theory**: chord progressions and Roman-numeral harmony, song structure (verse/chorus/bridge), genre conventions and instrumentation, rhythm/groove/tempo, melody and hook construction, mixing/mastering fundamentals
- **Cross-cutting production** knowledge connecting the two

The music-theory layer was seeded specifically so music-curation can delegate for "why does this sound work" reasoning from day one. The collection behaves as one connected corpus — syntheses already cross-reference Suno-mechanics videos and music-theory videos together. When music-curation retrieves against `tutorial_research`, this is what it gets.

### Infrastructure

- Qdrant on `localhost:6333`, Jaeger on `localhost:16686`, both via `docker compose -f infrastructure/docker-compose.yml up -d`. Auto-start with the user's docker setup.
- Verify Qdrant before any run that writes/reads memory: `curl -s http://localhost:6333/collections/tutorial_research | jq '.result | {status, points_count}'` (note: collection data is nested under `.result` — query it, not the top level).

---

## Seed data: the prompt files

The user has multiple structured markdown session-summary files (he mentioned ~9; three representative ones reviewed: lo-fi EDM, hip-hop/phonk, Junya-Nakano JRPG). Format characteristics that the seed-ingestion design must handle:

- **Each file = one creative session = multiple prompts.** Ingestion must split a file into individual prompt entries, not treat one file as one memory point.
- **Already structured** (consistent sections: goal, prompts with style/lyrics, reactions, evolution log, learnings, templates) — a parser can rely on structure rather than LLM-extracting from prose, though some LLM extraction may still help normalize.
- **Reactions present on most prompts, absent on some** — reaction is optional per entry.
- **No link to the actual Suno output audio** — the files have prompt + reaction, not a reference to the resulting track. So the "result" dimension starts as the user's textual reaction only; richer result-linking (if ever wanted) is a future concern.
- **Multilingual is pervasive** — same musical idea in English/French/Japanese is a recurring pattern, with notes on which languages' phonetics suit which vocal effects. Language is a first-class dimension.

These files seed `music_curation_memory` (and possibly other collections per the schema decision). They should be ingested **deliberately, as the user provides them** — not auto-discovered from his vault. The user controls what becomes memory.

Practical note for the build: get the *real* file paths from the user at ingestion time. Do not assume a location. He will provide them.

---

## What's explicitly out of scope

- **Suno API integration** — no public API exists. Hard constraint. Agent generates prompts; user runs Suno manually.
- **Auto-harvesting the user's personal vault** — privacy boundary. Memory is curated and user-provided only.
- **Audio analysis of tracks** (BPM/key detection from audio files, etc.) — listed in the director spec as a *possible future tool* ("may be added if it would genuinely improve the agent"), not a v1 deliverable. If it comes up, it's a discovery, not a requirement.
- **MCP exposure** — planned system-wide but after the agent is stable in CLI/library form. Not the first build.
- **Generating the actual music** — the agent produces prompts and reasoning; Suno (run by the user) makes audio.

---

## Standing instruction: keep the system spec current

`docs/ai-director-agent-system.md` is the system-level source of truth, and it drifted stale during the tutorial-research build (it still listed tutorial-research at "38 tests" and had no record of the runtime bug-fixes). **As the music-curation build proceeds, update that document** to reflect:
- music-curation status as it moves from skeleton → under development → complete (with real test count)
- any new collections it creates
- any runtime changes made during the build
- any decisions that change the system-level picture

A patch-list correcting the *current* staleness in that document (and in the READMEs and v2-refinements) accompanies this handoff — apply it before or early in the build so the next chat starts from accurate docs.

---

## Build shape (dependency order, not a timeline)

Same shape every agent follows: scaffold the package, **design the data models (the memory schema is the gate here)**, build the chains, build the invocation surface, integrate the runtime, write tests, document, then smoke-test against live APIs and seed data.

The hard ordering constraint: **the memory-model design conversation must complete before any code.** Everything downstream (seed-ingestion parser, output model, retrieval, delegation logic) depends on it. After the schema is agreed, a reasonable build order is: memory models → seed-ingestion (parse the real files into the collection) → retrieval + delegation → generation/reasoning chains → curated-write flow → CLI/library → tests → smoke test on real seed data and a real prompt-generation request.

---

## State of credentials and accounts

- **Anthropic**: paid, $25 manual reload. Cost-conscious design appropriate. The user reloads manually, so a runaway is unlikely but budget caps still matter. Top up before a heavy smoke-test session.
- **Voyage AI**: payment method added, standard rate limits (the free-tier 3-RPM limit that bit during early pipeline testing is gone). 200M free tokens still apply. Embedding is effectively free at this scale.
- **Tavily**: free tier; only relevant via tutorial-research delegations.
- **Suno**: paid Pro account. Manual workflow.
- **Qdrant / Jaeger**: local Docker, no accounts.

---

## File paths to know

| Path | What's there |
|---|---|
| `~/projects/agent-stack/` | The workspace |
| `~/projects/agent-stack/packages/music-curation/` | The skeleton to build out |
| `~/projects/agent-stack/.env` | Real credentials (gitignored) |
| `~/projects/agent-stack/docs/ai-director-agent-system.md` | System-level spec (keep current) |
| `~/projects/agent-stack/docs/architecture.md` | Runtime/package architecture |
| `~/agent-data/` | Runtime data (sources, runs, Qdrant volume) — `~` now expands correctly post-bugfix |
| `~/obsidian/agent-reports/` | Agent-written Markdown reports |
| `~/obsidian/obsidian-vault-personal/` | User's personal vault — agents must NOT touch |
| (user-provided at build time) | The Suno session-summary markdown files to ingest as seed |

---

## How to open the next conversation

Load this handoff plus `docs/ai-director-agent-system.md`, `docs/architecture.md`, and `README.md` as project knowledge. A good opening prompt:

> We're building the music-curation agent. Read this handoff, the director system spec, the architecture doc, and the README. Confirm your understanding of what music-curation is and the current state of the system. Don't write any code yet — start by working through the central open question (the memory model) and the other open design questions in the handoff. The seed data (my Suno session files) is the key input to the memory design; I'll provide the files when we get to ingestion.

The next chat should: (1) confirm current state, (2) work through the memory model as a real design conversation — enumerate the memory types, decide collection topology, decide embed-vs-payload, decide how evolution chains are represented — (3) work through the secondary open questions, (4) only then propose a Claude Code prompt to begin the build. It should NOT lump the four+ memory types together without discussion, propose a schema and start coding, treat the user as a beginner, or interrogate him with many small clarifying questions.

---

End of handoff.
