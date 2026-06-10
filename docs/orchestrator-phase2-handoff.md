---
title: Orchestrator Agent — Phase 2 Handoff
date: 2026-06-09
type: phase-2-handoff
agent: orchestrator
project: agent-stack
status: active
---

# Orchestrator Agent — Phase 2 Handoff

This document **closes Phase 1 (Design and discovery)** for the Orchestrator agent (`orchestrator`) and **opens Phase 2 (Implementation)**. Phase 1 was conducted as a design conversation; this handoff records its resolved conclusions so Phase 2 can begin without re-deriving them. Per the methodology, Phase 2 opens with a **handoff-verification turn** — read this fresh, confirm it still reflects your understanding (especially after the between-phase LangGraph ingestion below), and reconcile any drift in chat before the first build prompt is sent.

The Orchestrator supersedes the previously-planned "Project Organizer Agent" slot; the file-scaffolding scope that slot once held stays with Cowork. Full system-level spec: the "Orchestrator Agent" section of `ai-director-agent-system.md`.

## System state at handoff

What `orchestrator` can rely on as already built and queryable:

- **`agent-runtime`** — shared base: `BudgetEnvelope` (items, cost, depth, wall-time) with parent→child derivation for delegated calls, tracing (including `record_tool_call` and `record_delegation_decision`), `MemoryStore` (wraps `AsyncQdrantClient`), `UserKnowledgeStore`, the shared `docs_ingest` mechanism, and Markdown run-reporting.
- **Five built agents, each with a tested library API + CLI and a Qdrant collection:** `tutorial-research`, `music-curation`, `voiceover-direction`, `concept-script` (stateless), `visual-generation`. These are the sub-agents the Orchestrator wraps as tools.
- **Collections:** `user_knowledge` (runtime-owned, authoritative), `tutorial_research` (text + `voyage-multimodal-3` points), `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`, `technique_research_outputs` (owner not built yet), `project_archive` (planned, low priority). Embeddings: `voyage-3-large` (text, 1024-dim) and `voyage-multimodal-3` (multimodal, 1024-dim), cosine.
- **Reserved constant:** `MODEL_ORCHESTRATOR` (= `claude-sonnet-4-6`) is already reserved in the runtime.
- **New in the spec, not yet built:** the Orchestrator section and the "Schema migrations (planned)" section of `ai-director-agent-system.md`, plus `architecture.md` "Layer 6 — Schema migrations". SQLite enters the stack with the Orchestrator's checkpointer.

## The central design question (the Phase 1 gate) — RESOLVED

> **What is the orchestration control-flow graph, and where does each kind of state live?**

Both halves are resolved (control-flow + state placement), recorded below.

## Resolved design decisions (with reasoning)

1. **Framework — LangGraph, over the Claude Agent SDK.** Chosen for explicit control over the orchestration graph (nodes, branching, looping, tool routing, checkpointer wiring) and provider portability. The Agent SDK would hand session persistence, live file access, and MCP support over for free; that convenience was traded away for control. Accepted cost: the code-access tools, checkpointer wiring, and retrieval plumbing are built here. Consistent with the stack, which already reasons through `langchain-anthropic`.

2. **Control-flow — hand-rolled minimal ReAct loop.** One `agent` node (Sonnet, all tools bound) + one `tools` node (`ToolNode`), joined by a conditional edge: tool calls → `tools` → loop back to `agent`; no tool calls → END. Hand-rolled (not the prebuilt `create_react_agent`) so the runtime hooks are explicit insertion points: a `BudgetEnvelope` check **before each tool execution** that short-circuits to a partial answer when exhausted, plus `record_tool_call` / delegation tracing per step. Not an elaborate multi-node graph — the LLM does the routing via tool calls; bespoke plan/retrieve/route nodes are premature and reserved for a concrete future need.

3. **State separation.** Conversation continuity = a LangGraph checkpointer (SQLite locally, thread-keyed, resumable), **never** the vector DB. Long-term knowledge = the existing Qdrant collections. Raw chat turns are never embedded for continuity.

4. **Budget model — per-turn hard envelope + per-session soft tally.** One turn = one top-level invocation governed by a `BudgetEnvelope`, exactly analogous to the single-invocation agents; the four existing dimensions map cleanly (per-turn USD, tool-call count, delegation depth, wall-time). The turn envelope is the **parent** for any in-turn sub-agent delegation, reusing the existing child-budget derivation. A per-session cumulative cost tally is tracking / soft-inform only — **not** a hard brick — because a checkpointed thread is meant to resume across sessions and a cumulative hard cap would either brick a useful thread or govern nothing. Enforced at the loop guard from decision 2.

5. **Model routing — Sonnet only for v1, Haiku reserved.** `claude-sonnet-4-6` (the reserved `MODEL_ORCHESTRATOR`) is the single reasoning/tool-calling model; its core competency is exactly multi-step reasoning + reliable tool-calling. A separate cheap router would split the routing the LLM already does via tool calls. Haiku's natural roles here (compressing large tool outputs, summarizing old turns for context management) are optimizations, wired in only when context pressure appears.

6. **Sub-agent invocation — in-process library API.** Tools call the agents' existing tested library entry points in the same process, so budget parent/child, tracing, and the shared Qdrant client propagate naturally. Expose each agent's **primary operations** as discrete, well-described tools (better tool-selection than one free-form mega-tool); exact granularity tuned during build. Accepted tradeoff: the orchestrator package depends on the union of all wrapped agents' dependencies, and a heavy agent runs in-process. MCP later swaps only the tool *implementations* (library call → MCP tool) without touching the graph — the extensibility seam.

7. **Knowledge retrieval — a single domain-scoped tool.** `search_knowledge(query, domain)` where `domain` is an enum mapping to the right collection **and** the correct query-embedding model internally, always co-querying `user_knowledge` with the established 1.25× authority boost. Agentic (the LLM calls it when needed, not a mandatory pre-step). Cross-model-safe by construction: each call targets one embedding space, so scores are never merged across spaces.

8. **Live codebase + docs access.** Read + grep tools over the `agent-stack` packages and `docs/`, the way Claude Code works. Actively-developed code is read live, never summarized-and-embedded. This is also how the Orchestrator answers questions about agents' capabilities, implementation, status, and usage.

9. **Conversation surface — CLI REPL over the library API.** `orchestrator chat [--thread <id>]`: read input → run the graph for that thread → print → loop; new thread per launch unless `--thread` resumes a checkpointed one. The library API is the seam; MCP-server / Telegram / voice / web / scheduled surfaces layer on later without changing the graph.

## First build slice (Phase 2 scope proposal)

Concrete, minimal, and provable end-to-end:

- **Scaffold** `packages/orchestrator` as a uv workspace member, depending on `agent-runtime` plus the two seed agents `tutorial-research` and `music-curation` (both built, both Qdrant-backed).
- **Graph:** the hand-rolled ReAct `StateGraph` — `MessagesState`-style state + budget consumption, Sonnet agent node, `ToolNode`, conditional edge + loop-back, the per-turn `BudgetEnvelope` guard and tracing hooks wired into the loop, LangGraph `SqliteSaver` checkpointer (`~/agent-data/agent-stack.db` or a dedicated checkpointer DB; `.setup()` at startup — this is the library managing its own tables, **not** the migration runner).
- **Tools (v1 set):** `search_knowledge(query, domain)` with the `user_knowledge` boost; `read_file` + `grep` over the repo; sub-agent tools for `tutorial-research` (retrieve + research) and `music-curation` (recall + generate) via in-process library API. System-introspection ("what does agent X do / how is it built / how do I use it") is served by the read/grep tools + reading `ai-director-agent-system.md`.
- **CLI REPL:** `orchestrator chat`, checkpointed/resumable, with the per-session cost tally surfaced.
- **Tests** following the per-agent test pattern in the repo.

**Explicitly out of the first slice (deferred, see below).**

## Deferred items

- **Vector-DB diagnostics + per-agent remediation delegation.** The diagnose-only design is settled (see the Orchestrator section), but building it is deferred — first slice ships chat + retrieval + sub-agent invocation. Remediation entry points on the owning agents are the dependency this will surface.
- **The other three agents as tools** (`voiceover-direction`, `concept-script`, `visual-generation`) — add after the contract is proven on the two seed agents.
- **MCP** — both wrapping agents as MCP servers and exposing the Orchestrator itself as an MCP server. Library-API-in-process is the v1 path.
- **Additional surfaces** — Telegram / voice / web / scheduled triggers.
- **Haiku utility** — tool-output compression and long-thread summarization, until context pressure is observed.
- **Per-session soft ceiling** — v1 is a tally only.
- **The schema-migration runner** — a separate runtime workstream; the Orchestrator's checkpointer uses LangGraph's own `.setup()`, independent of it.

## Research signals (between Phase 1 and Phase 2)

**One gap to close before Phase 2**, mirroring the established pattern (voiceover-direction needed ElevenLabs docs seeded between phases): LangGraph is new to this stack — every built agent is plain sequential LangChain. Before implementation, ingest LangGraph knowledge so Phase 2 builds against a closed gap.

Topics to cover (for a `tutorial-research` run into `tutorial_research`, preferred; and/or `docs_ingest` into `user_knowledge` with `domain=langgraph_mechanics`):

- LangGraph `StateGraph` and tool-calling agents (`ToolNode`, conditional edges, the agent/tools loop)
- LangGraph persistence / checkpointers, specifically `SqliteSaver` (thread-keyed, resume)
- Binding tools to `ChatAnthropic` (`langchain-anthropic`) and reading tool calls back
- Reference docs: `langchain-ai.github.io/langgraph` (persistence, tool-calling, ToolNode, how-tos)

The runnable `tutorial-research` Claude Code prompt for this ingestion can be produced on request when you're ready to do the between-phase run.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md` (single-version-of-inputs, treat as senior programmer, terminal-first, decisions-with-reasoning, no timelines). Not restated here.

## Phase 2 end condition (from the methodology)

The agent works as designed, verified by user smoke testing against a real use case, with immediate post-smoke-test friction addressed; all documentation (`README.md`, `docs/architecture.md`, `docs/ai-director-agent-system.md`, `packages/orchestrator/README.md`) updated to the post-Phase-2 state; and a Phase 3 handoff produced capturing all deferred items.
