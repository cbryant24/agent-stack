# agent-shell

A provider-neutral chat shell that any agent can opt in to. It owns the tool contract, the approval gate, the audit log, saved sessions and the terminal screen. The core contains **no LLM SDK**: a model plugs in behind a small `Engine` protocol. There are two engines: a scripted `FakeEngine` (tests, demo) and the **LangGraph engine**, which runs on Claude or OpenAI models and lives in the optional extra `agent-shell[langgraph]`. Decision record: `docs/adr/0001-agent-shell.md`.

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

# a real model (needs keys: run under op run)
op run --env-file=.env -- uv run agent-shell demo --provider claude
op run --env-file=.env -- uv run agent-shell demo --provider openai --model gpt-5-mini
```

Say anything for turn 1 (a read tool, no prompt), turn 2 (memory write: `y/n/e/d`), turn 3 (GPU spend: `y/n`). `/exit` then walks the proposed writes. Input: Enter sends, Esc-Enter adds a line, Ctrl-C interrupts the turn. Slash commands never call a model:

`/help /exit /cost /budget /dry-run [on|off] /tools /audit /session list|resume <id>|rename <title> /provider [name] [model] /model [name]`

`/provider` and `/model` switch engines mid-session and keep the whole conversation (see "Engines").

## How it fits together

```
tools/registry.py   ToolSpec, EffectClass, ToolResult, Registry
tools/executor.py   validate -> gate -> dry-run -> call -> ToolResult -> audit
guard/gate.py       confirm policy, Confirmer protocol, three session budgets
audit/log.py        audit.jsonl beside the runtime trace
audit/trace.py      agent-runtime-format trace per session segment (for agent_costs.py)
session/store.py    SQLite: structured neutral transcript + per-provider native handle
session/recorder.py folds a turn's events into that transcript, in order
session/api.py      Session: start / send / confirm / interrupt / close  (no terminal code)
engine/base.py      Engine protocol, five events
engine/fake.py      scripted engine for tests and the demo
engine/langgraph_engine.py  the real engine (Claude / OpenAI); the only module that imports LangGraph
engine/factory.py   make_engine(provider, model): keys + price checks, fails before any call
context.py          which history a model sees (trim rule)
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

## Engines

The LangGraph engine is a small model/tools graph that streams through `astream_events`. It has no checkpointer: **the neutral transcript is the source of truth** and is rebuilt into model messages every turn (user, assistant with tool calls and their ids, tool results as `ToolResult.text`). That is why `/provider openai` mid-session just works: the next engine reads the same history, with nothing summarised.

- **Gate.** Tool calls run through bound handlers, so the executor stays the only approval gate. No LangGraph interrupts. Calls in one model message run one at a time, and a tool never starts before the session has handled that step's cost and "tool started" events (a spent budget or an interrupt stops the turn first).
- **Context.** System prompt + the last 20 turns + tool results as their short text (capped at 1,500 chars). Older turns are dropped, not summarised.
- **Prompt caching.** Claude only: `cache_control` on the system prompt and the last tool definition. It pays off above Anthropic's minimum cacheable prompt size.
- **Cost.** Strict. `make_engine` refuses a model with no row in `agent_runtime.budget._PRICING` and a missing key, before any call. Each model call writes a `turn_cost` audit record and a trace event. See session totals with `python3 scripts/agent_costs.py --agent <app> --by-session`.
- **Keys.** Passed to the model client, never exported. OpenAI: `CHAT_OPENAI_API_KEY` (falls back to `PRODUCTION_AGENTS_OPENAI_API_KEY`). Never export `ANTHROPIC_API_KEY` in your shell.
- **Switching** writes a `provider_switch` audit record and does not end the session (no end-of-session proposals).

## Decisions worth knowing

- **Reuse from agent-runtime:** `BudgetEnvelope` (and `derive_child`), `agent_runtime.tracing.span`, `estimate_cost`. Not reused: `BudgetTracker`, because it opens its own trace file and span per instance and prices unknown models at $0.00. The shell charges the cost the engine reports (priced strictly by `estimate_cost`) and writes the same trace format itself.
- **Confirm helpers not reused:** the existing y/n/edit/defer prompts live in `music-curation` (an agent package, off limits) and in `agent-runtime` docs ingestion (private, typed to doc sections). The shell has its own generic `Confirmer`.
- **`mcp_export.py` is a stub.** The `mcp` package is not a runtime dependency and this phase adds none. When built, MCP calls must go through `Executor.run` so the gate still applies.
- **Engines run tools through bound handlers** (`Executor.bind`), so a model's tool call hits the same gate, dry-run and audit as anything else.
- **Tests import helpers from `agent_shell.testing`**, not from `conftest`, because pytest's importlib mode cannot import sibling test modules.

## Tests and checks

```bash
uv run pytest packages/agent-shell -v
uv run ruff check packages/agent-shell
uv run mypy --config-file packages/agent-shell/pyproject.toml packages/agent-shell/src packages/agent-shell/tests --exclude 'tests/lg/'
uv run mypy --config-file packages/agent-shell/pyproject.toml packages/agent-shell/tests/lg   # two conftest.py files: separate run
(cd packages/agent-shell && ../../.venv/bin/lint-imports)

# live provider tests (a few cents; skipped by default)
op run --env-file=.env -- env AGENT_SHELL_LIVE=1 AGENT_SHELL_LIVE_OPENAI_MODEL=<model with a price row> \
    uv run pytest packages/agent-shell -m live -v
```

mypy needs the package's own config: `agent-runtime` ships no `py.typed`, so the config silences those imports.

**Import contract** (`[tool.importlinter]` in `pyproject.toml`, run by a test): `agent_shell` may not import `anthropic`, `openai`, `langchain*`, `langgraph*`, `claude_agent_sdk`, `agents`, or any agent package. The one exemption is `engine/langgraph_engine.py` importing `langgraph` / `langchain_*`; a source-scan test proves nothing else does, and probe tests plant violations to prove the contract is not checking nothing. (`langchain_core` is also loaded by `agent-runtime`'s text splitter, so the check on imported modules covers `langgraph` and the two model libraries only.)
