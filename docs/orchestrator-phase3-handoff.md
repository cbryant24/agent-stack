---
title: Orchestrator Agent — Phase 3 Handoff
date: 2026-06-10
type: phase-3-handoff
agent: orchestrator
project: agent-stack
status: active
---

# Orchestrator Agent — Phase 3 Handoff

This document **closes Phase 2 (Implementation)** for the Orchestrator agent (`orchestrator`) and **opens Phase 3 (Refinement)**. It captures everything deferred from Phase 2 so Phase 3 can begin without re-deriving it. Per the methodology (`ai-director-agent-system.md` → "Build Methodology"), Phase 3 opens with a **handoff-verification turn**: read this fresh, confirm it still reflects your understanding, and reconcile any drift in chat before the first refinement prompt is sent.

Phase 3 is deliberately **smaller-touch** than Phase 2 — it polishes a working agent, not redesigns one. Scope is limited to non-major architecture changes, weighed on cost, necessity, and scope-appropriateness, in the "Group A" style: focused changes grouped by surface area, each smoke-verified. Items that prove larger than that bar move to `docs/v2-refinements-orchestrator.md` with documented reasoning rather than being forced into Phase 3.

## System state at handoff

What Phase 2 shipped (first slice), verified working:

- **`packages/orchestrator`** — uv workspace member. A hand-rolled ReAct LangGraph loop (Sonnet via `MODEL_ORCHESTRATOR`, defined in `orchestrator/constants.py`): an `agent` node (`bind_tools`) + a custom `tools` node wrapping `ToolNode`; conditional edge loops on tool calls, ends otherwise.
- **Per-turn budget guard + tracing** — a `BudgetEnvelope` check runs before each tool step and short-circuits to a partial answer when exhausted; `record_tool_call` and `record_delegation_decision` fire per step. Sub-agent tools derive child budgets via `BudgetEnvelope.derive_child`.
- **Checkpointer** — thread-keyed `AsyncSqliteSaver` at `~/agent-data/agent-stack.db`, resumable, `.setup()` at startup (the library managing its own tables — independent of the still-unbuilt migration runner).
- **Tools (v1 set)** — `search_knowledge(query, domain)` over a domain registry (`tutorial_research`, `music_curation_memory`, `langgraph_mechanics`), one embedding space per call, 1.25× `user_knowledge` boost + cap, graceful degradation; `read_file` + `grep` scoped to the repo (also serve system-introspection); and four in-process sub-agent tools — `tutorial_retrieve` / `research_tutorials`, `music_recall` / `music_generate`.
- **CLI** — `orchestrator chat [--thread <id>]`, checkpointed/resumable, with a soft per-session cost tally.
- **Tests** — 14 orchestrator tests (graph loop, budget guard, `search_knowledge` boost/degrade, checkpointer resume). All-up workspace total is 845 with infrastructure up.
- **Docs** — `README.md`, `docs/architecture.md`, `docs/ai-director-agent-system.md`, and `packages/orchestrator/README.md` updated to the post-Phase-2 state.

The smoke test passed: a real-use `orchestrator chat` answered a question about the agents via the read/grep introspection path.

`docs/v2-refinements-orchestrator.md` **does not exist yet** — Phase 3 creates it as the durable record of captured-but-not-built items, and finalizes it at Phase 3's end.

## Deferred items (from Phase 2)

Grouped by surface area, with a recommended order. No timelines — order only, grouped for cohesion. Each item is tagged **[Phase 3]** (within the smaller-touch bar) or **[v2-refinements]** (larger/architectural; likely belongs in the durable refinements file rather than Phase 3 — final call at the Phase 3 opening).

### Group A — Sub-agent surface (recommended first)

1. **The other three agents as tools — [Phase 3]. ✅ Done.** Added `voiceover-direction`, `concept-script`, and `visual-generation` as orchestrator tools, mirroring the `tutorial-research` / `music-curation` wrapping. Each via its existing library entry point, with a derived child budget and `record_delegation_decision`. **Only FREE / non-side-effecting ops are wrapped** — `voiceover_direct` (free LLM direction over a `script.md`) + `voiceover_recall`; `concept_draft` + `concept_shape` (stateless); `visual_draft` (free prompt-craft) + `visual_recall`. The costly paid ops (visual-generation `generate` = GPU/RunPod, voiceover-direction TTS = ElevenLabs money) are deliberately NOT exposed, so the autonomous loop can never trigger paid generation. The `search_knowledge` domain registry gained `voiceover_direction_memory` and `visual_generation_memory` (standard 1.25× boost + cap + graceful degrade); `concept-script` is stateless so it has no domain. Exercised the existing seam with no new architecture.

### Group B — Runtime hygiene (small, independent)

2. **`_maybe_notify_threshold` zero-guard — [Phase 3], runtime. ✅ Done.** `agent_runtime/budget.py`: `_maybe_notify_threshold` now short-circuits when a `max_*` ceiling is falsy/`<= 0` instead of dividing `current / maximum`, so a `BudgetEnvelope` with any dimension set to `0` no longer raises `ZeroDivisionError` inside `check_budget()` (a `0` ceiling reads as "no headroom"; the hard checks still raise `BudgetExhaustedError`). Covered by `max_items=0` / `max_cost_usd=0` regression tests. (This was the **single** genuine runtime follow-up; the `record_tool_call` → `add_tool_call` bridge is **not** a deferred item — it predates this build, commit `8e9945c`, and is already documented at `architecture.md` Layer 2.)

3. **Per-session ceiling — [v2-refinements]. ⏸ Deferred.** Moved to `docs/v2-refinements-orchestrator.md`. Low-value polish: the soft per-session cost tally already gives visibility, and if ever built it must stay warn-only (a checkpointed thread resumes across sessions, so a cumulative hard cap would brick a useful thread or govern nothing).

### Group C — Diagnostics (larger; scope carefully)

4. **Vector-DB diagnostics (diagnose-only) + remediation delegation — [Phase 3 / v2-refinements]. ✅ Diagnose-only done; remediation split to v2 (as anticipated).** Built per the settled design: read-only Qdrant inspection (`MemoryStore.get_collection_info` / `count_points` / `sample_points`), live code access (existing `read_file` / `grep`), and a behavioral probe — surfaced as the `inspect_collection`, `probe_collection`, and `write_diagnostic_report` tools (`orchestrator/diagnostics.py`); reports land in `~/obsidian/agent-reports/diagnostics/` with status `open → delegated → fixed`. The **delegation seam** (`RemediationHandler` protocol + registry + `delegate_remediation`) is built and stub-tested, but ships with an **empty registry** — the hard dependency (a **remediation entry point on each owning agent**, which performs the actual write) was split off as anticipated: per-agent remediation paths are recorded in `docs/v2-refinements-orchestrator.md`. Until an agent registers a handler, each report is a manual work order. The orchestrator never writes to Qdrant.

### Larger / architectural — likely `v2-refinements-orchestrator.md`

5. **MCP — [v2-refinements].** Both wrapping the sub-agents as MCP servers and exposing the orchestrator itself as an MCP server. The library-API-in-process path is v1; MCP swaps only tool *implementations* without touching the graph (the extensibility seam), but it's a meaningful workstream beyond a polish pass.

6. **Additional surfaces — [v2-refinements].** Telegram / voice / web / scheduled triggers over the existing library API / CLI seam.

7. **Haiku utility — [v2-refinements].** Tool-output compression and long-thread summarization, wired in only when context pressure is observed. It has not been observed yet; `MODEL_UTILITY` is reserved/unwired.

8. **Schema-migration runner — [v2-refinements / separate runtime workstream].** The runtime-owned migration runner + ledger (`migrate status | up | stamp`) remains unbuilt. The orchestrator's checkpointer uses LangGraph's own `.setup()` and is independent of it. This is a cross-cutting runtime workstream, not orchestrator-specific refinement — scope it on its own.

## Phase 3 end condition (from the methodology)

All Phase-3-scoped items either landed or moved to `docs/v2-refinements-orchestrator.md` with documented reasoning for the defer; that file is current and is the durable record of captured-but-not-built items. All documentation (`README.md`, `docs/architecture.md`, `docs/ai-director-agent-system.md`, `packages/orchestrator/README.md`) reflects the post-Phase-3 state. A handoff document is produced for the next agent, tool, or application to be built — Phase 3's end is that next build's Phase 1 starting point.

## Working-relationship rules

Unchanged and in force — see the "Working-relationship rules" section of `ai-director-agent-system.md`. Not restated here.
