---
title: "agent-stack Handoff — Pre Tutorial-Research"
date: 2026-05-26
type: handoff
project: agent-stack
status: active
purpose: resume-context-after-compact
phase_completed: runtime-and-yt-pipeline
phase_next: tutorial-research-agent
tags:
  - handoff
  - agent-stack
  - context-transfer
---

# agent-stack Handoff

This document is the load-bearing context for resuming work on the agent-stack project after a context compaction or in a new conversation. It is paired with `docs/architecture.md` and the workspace `README.md`, both of which contain the authoritative current state of the code. Read this document first, then those two.

The goal of this handoff is to convey **what's done, what's decided, what's deliberately deferred, and what the next deliverable is**, without re-deriving the reasoning that led to current decisions.

---

## Project elevator pitch

A personal toolkit of reusable, standalone AI agents — each specialized for a domain (research, music curation, eventually color grading, etc.) — built on a shared runtime that provides budgets, delegation, tracing, vector memory, and reporting. The first project that exercises multiple agents together will be an anime mashup video pipeline, but the agents are designed to be independently useful for video game reviews, travel content, and other future projects.

The user is a programmer with 8+ years experience. He uses Claude Desktop for conversational work, Claude Code for development, and Cowork for scaffolding. He works from iTerm2 with zsh on an M1 MacBook. He dislikes timelines, week-based work breakdowns, and excessive clarifying questions. He prefers decisions made with reasoning explained, and pushback if he wants something different.

---

## Architectural principles (settled, don't re-debate)

These were worked out at length earlier and are not up for renegotiation unless something concrete forces revisiting them.

**Agents are standalone, not features of an application.** Each agent is genuinely independent — has its own invocation surface, its own state where applicable, and can be called without other agents being present. The anime mashup project uses several agents together, but the agents are not "part of" the anime mashup project.

**Clean separation between user material and agent material.** The user's Obsidian vault (`~/obsidian/obsidian-vault-personal/`) is his alone — agents do not write to it. Agent-generated reports go to a separate vault (`~/obsidian/agent-reports/`). Agent knowledge bases live in Qdrant, not in any vault. Source documents agents work from live on disk under `~/agent-data/sources/`. This separation is enforced architecturally, not just by convention.

**Vector database is the right tool for agent knowledge bases.** Decision: Qdrant (local, Docker), 1024-dimensional vectors, Voyage AI embeddings (`voyage-3-large` for text, `voyage-multimodal-3` for image+caption). Single collection per domain, mixed text and multimodal points within. Image bytes stored on disk; vectors and metadata stored in Qdrant; payloads carry paths to the disk files.

**Budget governance is built into the runtime from day one.** Every agent invocation has a `BudgetEnvelope`. Delegated calls derive child budgets that cap against parent values. Hard caps on items, cost, depth, and wall time. The user reloads $25 of Anthropic credits manually, so cost runaway protection matters less than for someone on auto-reload, but the scaffolding exists for future use.

**Reporting is well-balanced (actions and problems, not just problems).** Every agent run produces a structured JSONL trace plus a Markdown report rendered to the agent-reports vault. macOS notifications fire on completion and on threshold events. The user reads the Markdown; the JSONL is for diagnostic dig-ins.

**Monorepo with uv workspace, not separate repos.** Three packages currently (`agent-runtime`, `yt-intelligence-pipeline`, `tutorial-research`, `music-curation` — the last two are skeletons). They share a `.venv`, import each other as workspace members, and version together for now. Could extract individual packages later if any reaches independent maturity.

**The YouTube pipeline is the canonical YouTube ingestion capability.** It has two output modes (human-readable Obsidian notes; agent-consumable Qdrant ingestion) that can run together or independently. Agents that need YouTube tutorial knowledge call `process_video()` as a library function — they do not reimplement YouTube fetching.

---

## What's done

### `agent-runtime` (167 tests passing)

Complete and stable. Public API surface as documented in `architecture.md`. Worth knowing for the next agent:

- **`get_config()`** is the singleton accessor — reset for tests via `reset_config()`
- **`BudgetTracker`** is the async context manager every agent run wraps itself in
- **`@traced`** decorator on agent functions; `record_*` helpers for explicit instrumentation
- **`delegate()`** for agent-to-agent calls — handles budget derivation, depth enforcement, parent debiting automatically
- **`MemoryStore`** has both text (`upsert_points`, `search`) and multimodal (`upsert_multimodal_points`, `search_multimodal`) methods plus `upsert_mixed` for both-at-once when failure semantics tolerate it
- **`render_run_report()`** is called at the end of agent runs to produce the Markdown report
- **`notify*`** helpers fire macOS notifications

The runtime has been exercised end-to-end through the YT pipeline. No known design issues.

### `yt-intelligence-pipeline` (39 tests passing)

Complete. Two modes; library + CLI. The library entry point is `process_video()` (async) or `process_video_sync()` (sync wrapper). Agents will use the async version.

**Critical thing for the next agent to know:** when called from inside an agent's `BudgetTracker` context, `process_video()` automatically picks up the agent's run_id from the contextvar, so processed_in_run on the resulting MemoryPoints is correct. The agent does not need to pass run_id explicitly.

### Infrastructure

- Qdrant on `localhost:6333` via `docker compose -f infrastructure/docker-compose.yml up -d`
- Jaeger UI on `localhost:16686`
- Both auto-start with the user's docker setup

### What's tested vs. what's smoke-tested

The runtime is unit-tested comprehensively (167 tests across both packages). End-to-end smoke testing has been done where Voyage/Anthropic credentials were available. The user has noted that his Anthropic balance ran low during Phase 3 verification — Gate 1 hit a credit error on real video processing, but the same error happened in his standalone pipeline, confirming behavior parity. The runtime's mocked test paths fully exercise the code; real-LLM integration testing happens organically as agents are built.

---

## Decided but not yet implemented (deferred deliberately)

These were flagged during runtime construction as "revisit when building the first agent." Do not implement them speculatively — they're listed so the next agent author knows they exist and can decide if any apply.

- **TracePersister contextvar pattern**: Phase 2.1 added a `_current_persister` contextvar so the `record_*` helpers in tracing/decorators.py write to both OTel and the JSONL persister. This works. If a future use case wants more sophisticated nested-persister semantics (e.g., separate per-delegation JSONL files), that's where to extend.

- **MCP server layer**: Agents are built as Python CLIs first. Once tutorial-research is stable, an MCP server layer will expose agents as tools to Claude Desktop. This is the right end state but not the right first build.

- **Music curation memory ingestion**: When music-curation is built, it'll need a way to ingest the user's existing Suno prompt notes and reference material into Qdrant. The pattern from yt-pipeline (chunk → embed → upsert with rich metadata) applies. The user has 9 existing Suno prompt summary files in his personal vault that are exploratory notes — they may be ingested as initial reference material, but the user wants to provide them deliberately as context, not have agents auto-discover from his vault.

- **Domain ontology / tag vocabulary**: Currently `domain_tags` and `topic_tags` in MemoryPoint payloads come from the YT pipeline's LLM-generated tags. These work but lack consistency across sources. A controlled vocabulary may eventually be needed for cross-source agent retrieval. Out of scope for tutorial-research v1.

- **Re-embed CLI flag for yt-pipeline**: `--reembed` would re-chunk and re-embed from the persisted `transcript.txt` without re-fetching video. Useful for embedding model upgrades or chunking strategy changes. Not yet built.

- **Audit / archival**: No system yet for long-term retention of trace JSONLs or for pruning old ones. They accumulate under `~/agent-data/runs/`. Manual cleanup until volume warrants automation.

---

## What's explicitly out of scope right now

- **DaVinci Resolve agent**: discussed at length, deferred. Knowledge-consultant tier (Tier 1) will be feasible once color-grading content is in Qdrant. Execution tier (Tier 3, autonomous color grading) is a research project, not a near-term deliverable.

- **Multi-agent orchestration UI**: no plans for a dashboard, web UI, or n8n integration for the agents themselves. CLI invocation now; MCP server layer eventually.

- **Hosted deployment**: everything runs locally on the user's M1. Not migrating to cloud anytime soon.

- **Suno API integration**: Suno has no public API. Music-curation generates prompts; the user runs them in Suno manually. Not changing.

- **Refactoring the existing standalone YT pipeline repo**: the monorepo copy is the canonical one. The original at `~/projects/yt-intelligence-pipeline/` is untouched and may be archived later.

---

## What comes next: tutorial-research agent

This is the next deliverable. Design goals:

**Inputs (the kinds of requests it should handle):**
- "Research [topic]" — high-level, the agent figures out what to ingest
- "Process this specific YouTube playlist" — directed ingestion
- "Find existing content in the knowledge base about [topic]" — pure retrieval, no new ingestion

**Tools the agent will need:**
- `yt-intelligence-pipeline.process_video()` for ingestion
- Tavily web search for discovering candidate tutorials when given an open topic
- `MemoryStore.search()` for querying existing knowledge in the `tutorial_research` collection
- Possibly a candidate-scoring LLM call (score tutorial URLs against the topic before processing)

**The reasoning loop (rough shape):**
1. Receive request + budget envelope
2. Decide: is this a retrieval-only question, or does it require ingestion?
3. If ingestion: identify candidates (Tavily or provided list), score them, select within budget, process each via the pipeline
4. If retrieval: query Qdrant with the topic, return ranked chunks
5. Optionally: synthesize a research summary using retrieved chunks as context for a Claude call
6. Produce a run report

**Invocation surface:**
- CLI: `uv run tutorial-research "color grading for AMVs"` — basic mode
- Library: `from tutorial_research import research; await research(topic, budget=...)`
- MCP exposure later

**Budget profile defaults:**
- Default `BudgetEnvelope` for tutorial-research: `max_items=5, max_depth=0, max_cost_usd=2.00, max_wall_time_sec=900`
- Override via CLI flags or library arguments
- The agent will be one of the first things called by other agents (e.g., music-curation will delegate to it for music-theory tutorials), so its budget defaults should be conservative

**Open design questions for tutorial-research that the next session should resolve:**
1. How to score candidate tutorials before processing? (Title + description via LLM, view count + recency heuristic, both?)
2. Should the agent always produce a synthesis (Claude call summarizing retrieved chunks), or only when asked? Synthesis costs LLM tokens.
3. Where does the "ingestion plan" live before execution? (Just in the trace, or a structured pre-flight that the user could review?)

These are real questions; they need answers but they don't have obvious right ones yet.

---

## How to start the next conversation

The user will open a fresh chat in Claude Desktop and provide this handoff document plus `docs/architecture.md` and the workspace `README.md` as project knowledge. The opening prompt should be along the lines of:

> We're picking up agent-stack work from this handoff. Read the handoff, the architecture doc, and the README. Confirm your understanding of the current state and what's next. The next deliverable is the tutorial-research agent. Don't write any code yet — start by working through the open design questions in the "What comes next" section.

The new Claude should:
1. Read all three documents
2. Confirm the current state matches the user's expectation
3. Work through the three open design questions in the "What comes next" section
4. Only then propose a Claude Code prompt for building tutorial-research

The new Claude should NOT:
- Re-litigate settled architectural decisions
- Suggest building things listed as out of scope
- Ask many clarifying questions (the user has stated he finds this overwhelming and prefers decisions-with-reasoning)
- Treat the user as a beginner (he's 8+ years experience and wants what works best, not what's easiest)

---

## State of credentials and accounts

- **Anthropic**: user reloads $25 manually; balance may be low at handoff time. Top-up before running real LLM-using agents.
- **Voyage AI**: free tier was hitting rate limits during yt-pipeline testing. User has been advised to add a payment method to unlock standard limits (200M free tokens still apply). Status unconfirmed at handoff.
- **Tavily**: free tier; sign-up status unconfirmed. Will be needed for tutorial-research's web discovery.
- **Suno**: paid Pro account; not relevant until music-curation.
- **ElevenLabs**: free tier; not relevant until voiceover-direction agent (not yet planned in detail).

---

## File paths to know

| Path | What's there |
|---|---|
| `~/projects/agent-stack/` | The workspace |
| `~/projects/agent-stack/.env` | Real credentials (gitignored) |
| `~/projects/agent-stack/.env.example` | Template |
| `~/projects/agent-stack/docs/architecture.md` | Authoritative architecture |
| `~/projects/agent-stack/README.md` | Workspace overview |
| `~/agent-data/` | Runtime data (sources, runs, Qdrant volume) |
| `~/obsidian/agent-reports/` | Agent-written Markdown reports |
| `~/obsidian/obsidian-vault-personal/` | User's personal vault — agents must not touch |

---

## One concrete thing the user can do right now

Independent of agent development, the YT pipeline is production-ready and the user can start populating the `tutorial_research` Qdrant collection manually. Running:

```bash
cd ~/projects/agent-stack
uv run yt-pipeline "<tutorial-url>" --output both
```

…on color grading tutorials, music theory tutorials, or whatever else he expects future agents to want as reference material. The knowledge base accumulates in parallel with agent development. By the time tutorial-research is built, the collection will already have meaningful content for it to query.

The AkashKRavi color grading playlist (12 of 25 already processed in his standalone pipeline, per the documents he uploaded early in the project) is a natural candidate. Re-processing through the monorepo version would put them in Qdrant for the first time.

---

End of handoff.
