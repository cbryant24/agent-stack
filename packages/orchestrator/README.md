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

**Phase 2 — first build slice.** Chat + knowledge retrieval + live code/doc access + two
seed sub-agents (tutorial-research, music-curation) as tools. Deferred: vector-DB
diagnostics, the other three agents as tools, MCP, additional surfaces, Haiku utility, a
per-session hard ceiling, the schema-migration runner.

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
  space per call, with the 1.25× `user_knowledge` boost); `read_file` + `grep` over the repo
  (also how the orchestrator answers system-introspection questions); and in-process
  sub-agent tools: `tutorial_retrieve` / `research_tutorials` and `music_recall` /
  `music_generate`.
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
`search_knowledge` (user-knowledge boost + graceful degradation), and the checkpointer (two
turns on one thread resume accumulated state, surviving across saver instances).
