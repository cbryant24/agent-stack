# orchestrator

The conversational meta-agent over the whole `agent-stack` system — the "director's
console." It knows what every agent does, answers questions about the system, retrieves
from the shared knowledge bases, reads the live codebase and docs, remembers the
conversation across sessions, and invokes the other agents as tools on the user's behalf.

Built on **LangGraph** (hand-rolled ReAct loop) over `langchain-anthropic`, with a
thread-keyed SQLite checkpointer for resumable conversations. See the "Orchestrator Agent"
section of `docs/ai-director-agent-system.md` for the system-level spec and
`docs/orchestrator-phase2-handoff.md` for the resolved design.

## Status

**Phase 2 first build slice + Phase 3 sub-agent surface + diagnose-only diagnostics.** Chat +
knowledge retrieval + live code/doc access + all five built agents wrapped as tools
(tutorial-research, music-curation, voiceover-direction, concept-script, visual-generation) —
free / non-side-effecting ops only, so the autonomous loop never triggers paid generation —
plus read-only vector-DB diagnostics that diagnose and write a report but never write to
Qdrant. Deferred: per-agent remediation entry points (the diagnostics delegation seam is built
but its registry is empty — see `docs/v2-refinements-orchestrator.md`), MCP, additional
surfaces, Haiku utility, a per-session hard ceiling, the schema-migration runner.

## Usage

```bash
# Start a new checkpointed chat (a new thread per launch)
uv run orchestrator chat

# Resume a prior thread by id
uv run orchestrator chat --thread <thread-id>
```

The REPL surfaces the per-session cumulative cost as a **soft tally** (informational, not a
hard cap — a checkpointed thread is meant to resume across sessions). Requires a running
Qdrant (for `search_knowledge` / sub-agent retrieval) and the runtime's API keys.

### Library

```python
from orchestrator import build_app, run_turn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async with AsyncSqliteSaver.from_conn_string("agent-stack.db") as saver:
    await saver.setup()
    graph = build_app(saver)
    result = await run_turn(graph, "what does the music-curation agent do?", thread_id="t1")
    print(result.response, result.status, result.consumption.cost_usd)
```

## Design

- **Graph (`graph.py`)** — one `agent` node (Sonnet, all tools bound) + one `tools` node
  (wraps `ToolNode`), joined by a conditional edge: tool calls → `tools` → loop back to
  `agent`; no tool calls → `END`. Hand-rolled (not `create_react_agent`) so the runtime
  hooks are explicit insertion points.
- **Budget** — a per-turn `BudgetEnvelope` (the parent for in-turn sub-agent delegations via
  `derive_child`). A guard runs **before each tool step** and short-circuits to a partial
  answer when exhausted; `max_items` is the per-turn tool-call ceiling. `record_tool_call`
  and `record_delegation_decision` trace each step.
- **Tools (`tools.py`)** — `search_knowledge(query, domain)` (domain-scoped, one embedding
  space per call, with the 1.25× `user_knowledge` boost; domains: `tutorial_research`,
  `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`,
  `langgraph_mechanics`); `read_file` + `grep` over the repo (also how the orchestrator
  answers system-introspection questions); and in-process sub-agent tools wrapping all five
  built agents — each with a derived child budget, recorded delegation, and output
  truncation. Only **FREE / non-side-effecting** ops are wrapped; the costly paid ops
  (visual-generation `generate` = GPU/RunPod spend, voiceover-direction TTS = ElevenLabs
  money) are deliberately kept out of the autonomous tool set:
  `tutorial_retrieve` / `research_tutorials`, `music_recall` / `music_generate`,
  `voiceover_direct` / `voiceover_recall`, `concept_draft` / `concept_shape` (stateless),
  and `visual_draft` / `visual_recall`.
- **Vector-DB diagnostics (`diagnostics.py`, diagnose-only)** — `inspect_collection`
  (read-only structural metadata via `MemoryStore.get_collection_info` / `count_points` /
  `sample_points`), `probe_collection` (behavioral probe that catches cross-model
  embedding-space mismatches), and `write_diagnostic_report` (a report to
  `~/obsidian/agent-reports/diagnostics/`, status `open → delegated → fixed`). The orchestrator
  **never writes to Qdrant**: the remediation delegation seam (`RemediationHandler` + registry +
  `delegate_remediation`) is built but ships with an empty registry, so reports are manual work
  orders until an owning agent registers a handler (deferred — `docs/v2-refinements-orchestrator.md`).
- **Model** — Sonnet only (`MODEL_ORCHESTRATOR`, defined here per the per-package
  convention). `MODEL_UTILITY` (Haiku) is reserved, not wired in.
- **Checkpointer** — LangGraph `AsyncSqliteSaver` at `~/agent-data/agent-stack.db`,
  thread-keyed and resumable; `.setup()` at startup (the library managing its own tables —
  not the schema-migration runner).

## Tests

```bash
uv run pytest packages/orchestrator -q
```

Covers the graph loop (tool call routes to `tools` and loops back; no tool call ends the
turn), the budget guard (an exhausted envelope short-circuits before the next tool runs),
`search_knowledge` (user-knowledge boost + graceful degradation, including the
voiceover-direction and visual-generation domains), the in-process sub-agent tools (each
calls its agent's entry point with a derived child budget and records the delegation), the
diagnostics (report round-trip, structural inspection, behavioral-probe shaping incl. the
cross-model-mismatch flag, and the remediation seam's `open → delegated → fixed` transition
via a stub handler — with one live-Qdrant probe test that auto-skips when Qdrant is down),
and the checkpointer (two turns on one thread resume accumulated state, surviving across
saver instances).
