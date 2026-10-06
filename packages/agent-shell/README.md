# agent-shell

A provider-neutral chat shell that any agent can opt in to. It owns the tool contract, the approval gate, the audit log, saved sessions and the terminal screen. It contains **no LLM SDK**: an engine adapter (Phase 2) plugs a real model in behind a small protocol. Until then a scripted `FakeEngine` drives everything, so the whole shell is tested offline with fake keys.

It is a sibling of `agent-runtime`, not a module of it, so the runtime's dependency set stays free of agent SDKs. `agent_shell` imports `agent_runtime` and nothing from any agent package (enforced, see below).

## What it solves

1. **Agents are one command at a time** — exploring means re-stating context every call.
2. **The one chat agent (`orchestrator`) is tied to one vendor** and has no approval step inside its loop.
3. **Nothing stops a tool from spending GPU money or writing memory silently.**

## Try it

```bash
uv run agent-shell demo              # scripted fake engine, no keys, no spend
uv run agent-shell demo --dry-run    # gated tools describe what they would do
uv run agent-shell demo --resume <session-id>
```

Say anything for turn 1 (a read tool, no prompt), turn 2 (memory write: `y/n/e/d`), turn 3 (GPU spend: `y/n`). `/exit` then walks the proposed writes. Input: Enter sends, Esc-Enter adds a line, Ctrl-C interrupts the turn. Slash commands never call a model:

`/help /exit /cost /budget /dry-run [on|off] /tools /audit /session list|resume <id>|rename <title> /provider [name] /model [name]`

## How it fits together

```
tools/registry.py   ToolSpec, EffectClass, ToolResult, Registry
tools/executor.py   validate -> gate -> dry-run -> call -> ToolResult -> audit
guard/gate.py       confirm policy, Confirmer protocol, three session budgets
audit/log.py        audit.jsonl beside the runtime trace
session/store.py    SQLite: neutral transcript + per-provider native handle
session/api.py      Session: start / send / confirm / interrupt / close  (no terminal code)
engine/base.py      Engine protocol, five events
engine/fake.py      scripted engine for tests and the demo
proposals.py        end-of-session proposals, y/n/edit/defer
repl/               prompt_toolkit input + Rich output (one front end)
mcp_export.py       stub (see below)
testing.py          small helpers for tool tests
```

### Gate

| Effect | Behavior |
|---|---|
| `none`, `read`, `external_read` | run, no prompt |
| `llm_spend` | counted against the tool budget; prompts only if the estimate would exceed what is left |
| `gpu_spend`, `destructive_local` | always y/n, with arguments and the tool's preview |
| `memory_write` | y/n/edit/defer; defer writes `~/agent-data/drafts/<agent>/<id>.json` (same id → same file) |

`/dry-run on` turns every gated tool into "here is what I would do" with nothing run and no prompt. Budgets are three separate ones (REPL LLM, tool LLM as a child envelope, GPU), matching the repo's "two budgets stay orthogonal" rule.

Tool errors are results, not crashes: a handler exception becomes `ToolResult(is_error=True, text="<ExcType>: <message>")` and is audited.

### What an agent supplies

```python
ChatConfig(agent_name=..., system_prompt=..., tool_pack=lambda: [ToolSpec(...)],
           default_budget=BudgetEnvelope(max_cost_usd=...), on_session_end=...)
```

Handlers take the validated `input_model` and return a `ToolResult`. Put the real cost in `result.data["cost_usd"]`; the executor charges it to the right budget. Optional `estimate_cost` and `preview` feed the gate.

### Data it writes

- `~/agent-data/agent-stack.db`, tables prefixed `agent_shell_` (created at startup; LangGraph's tables are untouched).
- `~/agent-data/runs/<date>/<agent>/<session_id>/audit.jsonl` — same root `scripts/agent_costs.py` reads.
- `~/agent-data/drafts/<agent>/` — deferred writes.
- `~/agent-data/shell-history/<agent>` — prompt history.

## Decisions worth knowing

- **Reuse from agent-runtime:** `BudgetEnvelope` (and `derive_child`), `agent_runtime.tracing.span`. Not reused: `BudgetTracker`, because it opens its own trace file and span per instance, and it prices unknown models at $0.00 (`budget.py:105`). The shell charges the cost the engine reports. Fixing that pricing table is a Phase 2 item.
- **Confirm helpers not reused:** the existing y/n/edit/defer prompts live in `music-curation` (an agent package, off limits) and in `agent-runtime` docs ingestion (private, typed to doc sections). The shell has its own generic `Confirmer`.
- **`mcp_export.py` is a stub.** The `mcp` package is not a runtime dependency and this phase adds none. When built, MCP calls must go through `Executor.run` so the gate still applies.
- **Engines run tools through bound handlers** (`Executor.bind`), so a model's tool call hits the same gate, dry-run and audit as anything else.

## Tests and checks

```bash
uv run pytest packages/agent-shell -v
uv run ruff check packages/agent-shell
uv run mypy --config-file packages/agent-shell/pyproject.toml packages/agent-shell/src packages/agent-shell/tests
(cd packages/agent-shell && ../../.venv/bin/lint-imports)
```

mypy needs the package's own config: `agent-runtime` ships no `py.typed`, so the config silences those imports.

**Import contract** (`[tool.importlinter]` in `pyproject.toml`, run by a test): `agent_shell` may not import `anthropic`, `openai`, `langchain*`, `langgraph*`, `claude_agent_sdk`, `agents`, or any agent package. A second test plants a violation to prove the contract is not checking nothing.
