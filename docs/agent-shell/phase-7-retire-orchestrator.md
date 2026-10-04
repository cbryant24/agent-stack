# Phase 7 — Retire the orchestrator

**Goal:** remove the LangGraph orchestrator and its dependencies without losing the parts that work.

**Depends on:** the replacement covering what you actually use. Steps 1-2 can happen right after Phase 0; removal waits for Phase 6.

## Step 1 — freeze (after Phase 0)

- Add `packages/orchestrator/DEPRECATED.md` pointing to `docs/agent-shell/` and `docs/adr/0001-agent-shell.md`.
- Mark it deprecated in the root README table and `CLAUDE.md`.
- No new tools or features.
- One permitted fix: update `SYSTEM_PROMPT` in `graph.py` so it names all eight wrapped agents. This is a one-line content fix that makes the frozen tool usable while you build.

## Step 2 — decide what to keep

| Component | Verdict | Destination |
|---|---|---|
| Vector-DB diagnostics (`inspect_collection`, `probe_collection`, `write_diagnostic_report`) | Keep | A `diagnostics` tool pack (READ, plus a file write for the report) used by `stack` or any agent app |
| Remediation seam (`RemediationHandler`, registry, `delegate_remediation`) and `remediate` CLI | Keep | Shared types already live in `agent_runtime.diagnostics`. Move the registry and the CLI command next to them or into the diagnostics pack. It fits the new model: owner writes, explicit confirm. |
| `search_knowledge` with the `user_knowledge` boost (`retrieval.py`) | Keep | A READ tool in the diagnostics or `stack` pack |
| Per-turn budget guard, child budget derivation | Keep the idea | Already reimplemented in the `agent-shell` executor on `BudgetTracker` |
| `_reconcile_tool_messages` | Drop | The SDK engines manage their own transcripts |
| Hand-rolled graph, `ToolNode`, LangChain message types, `AsyncSqliteSaver` | Drop | — |
| `read_file`, `grep` | Drop | Replaced by a README-section READ tool |
| Per-agent wrapper tools | Drop | Replaced by per-agent tool packs |
| LangGraph checkpointer tables in `~/agent-data/agent-stack.db` | Leave in place | The file is the shared relational store (shell sessions now, the migration ledger later). Old threads stay as a read-only archive; drop the tables only through the migration runner once it exists. |
| `langgraph_mechanics` knowledge domain | Keep the data | It is knowledge-base content, not a code dependency. |

## Step 3 — remove

1. Move the kept components and their tests.
2. Remove `packages/orchestrator` from the workspace members.
3. Remove `langgraph` and `langgraph-checkpoint-sqlite` if the Phase 0 usage map shows no other member imports them. Keep `langchain-anthropic` and `langchain-core`: the design docs state every agent's chains run on them, and `yt-intelligence-pipeline` also needs LangSmith.
4. Remove `ORCHESTRATOR_ANTHROPIC_API_KEY` from config and `.env.example` once nothing reads it, or rename it for the REPL apps.
5. Update the root README, `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md` and `docs/ai-director-agent-system.md`: the orchestrator sections, the "Technology — LangGraph (chosen over the Claude Agent SDK)" paragraph, the tech-stack and build-order tables, and the "Deferred but open" LangGraph entry. Fix the "8 of 9 / 8 of 10" and "42 / 59 tests" drift while there.
6. Mark "Conversational query mode" in `agent-runtime-v2-refinements.md` as landed, pointing to `agent-shell`, as that item asks.
7. Move `docs/v2-refinements/orchestrator-v2-refinements.md` items: the re-embed remediation and other agents' handlers go to the diagnostics pack backlog; the per-session ceiling item is closed (the shell has session budgets).

## Acceptance

- `uv sync --all-packages && uv run pytest -v` passes with the package removed.
- `orchestrator remediate` behavior is available at its new location with its tests.
- Diagnostics tools work from a REPL app.
- No workspace member imports `orchestrator`.
- Docs no longer describe the orchestrator as current.

## Risks

- **Hidden consumers.** Grep for `from orchestrator` and `orchestrator.` across the workspace before removal. music-curation's remediation handler is registered from `orchestrator/tools.py`; that registration must move first.
- **Removing shared LangChain dependencies.** Only LangGraph is orchestrator-only. Verify with the usage map before removing anything.
- **MCP plans.** The orchestrator spec deferred "MCP (wrapping agents and exposing the orchestrator)". `agent_shell.mcp_export` replaces that item; note it in the docs update.

## Claude Code prompt

1. **Goal:** freeze now; remove later.
2. **Mode:** plan mode for both; direct only after you approve the plan.
3. **Files:** `@docs/agent-shell/phase-7-retire-orchestrator.md @packages/orchestrator/ @packages/agent-runtime/src/agent_runtime/ @pyproject.toml @README.md @CLAUDE.md`
4. **Prompt (freeze):**

```
Apply Step 1 of docs/agent-shell/phase-7-retire-orchestrator.md: add DEPRECATED.md, mark the
orchestrator deprecated in README.md and CLAUDE.md, and update SYSTEM_PROMPT in graph.py so
it names all eight wrapped agents' tools. Change nothing else in the package. Run its tests.
```

**Prompt (remove, after Phase 6):**

```
Plan Steps 2-3 of docs/agent-shell/phase-7-retire-orchestrator.md. First report every import
of the orchestrator package across the workspace, every member that imports langgraph or
langchain-*, and every reader and writer of ~/agent-data/agent-stack.db. Do not drop any
table in that file.
Then propose the move of diagnostics, the remediation seam and search_knowledge with their
tests, and the exact dependency removals. Do not execute until I approve the plan.
```
