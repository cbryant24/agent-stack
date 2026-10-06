# Phase 2 — The LangGraph engine (Claude and OpenAI)

**Goal:** one real `Engine` that runs on Claude or OpenAI models, switchable per session with the history intact.

**Depends on:** Phase 1. **Spends GPU:** no. **LLM spend:** a few cents of live smoke tests.

Decision record: `docs/adr/0001-agent-shell.md` (LangGraph kept as the engine; the orchestrator is retired for its design, not its framework; the Claude Agent SDK / OpenAI Agents SDK stay possible later adapters behind the `Engine` protocol).

## What was built

- **Dependencies.** Optional extra `agent-shell[langgraph]`: `langgraph`, `langchain-core`, `langchain-anthropic` at the repo's existing locked versions, plus `langchain-openai`, all pinned exactly. The root dev group installs the extra so the default suite runs. The Phase 2 lock test passed: only `langchain-openai` and `openai` were added; no existing pin moved.
- **Import contract.** Only `agent_shell.engine.langgraph_engine` may import `langgraph` / `langchain_*`; a test scans the source to prove it, and another proves a violation elsewhere breaks the contract.
- **Structured transcript (changes Phase 1).** Stored history is now `user`, `assistant` (text + `tool_calls` with ids) and `tool` (`tool_call_id`, content = `ToolResult.text`, `is_error`). `Engine.send(handle, user_text, history)` receives the history. A guarded migration adds the `meta` column to existing databases. An interrupted or crashed turn is closed with a synthetic error result for every unanswered call, so stored history is always valid for providers that reject unbalanced history.
- **The engine** (`engine/langgraph_engine.py`): a hand-rolled `StateGraph` (model node, tools node, conditional edge), streaming through `astream_events`. No checkpointer and no LangGraph interrupts. Tools are compiled from the registry into `StructuredTool`s whose coroutines call the executor-bound handlers, so the gate, dry-run and audit are unchanged; the structured `ToolResult` rides on `ToolMessage.artifact`. Tool calls in one model message run one at a time. A handshake makes the tools node wait until the session has handled the model step's events, so a spent budget or an interrupt stops the turn before any tool runs.
- **Context rule** (`context.py`, vendor-free): system prompt + the last N user turns (default 20; a window never splits a call from its result) + tool results as `ToolResult.text` capped at 1,500 chars. Older turns are dropped, not summarised.
- **Prompt caching** (Claude only): `cache_control` on the system prompt block and on the last tool definition; verified against `langchain-anthropic`'s own request builder.
- **Cost.** `agent_runtime.budget.estimate_cost` is a strict lookup (`None` for an unpriced model), with cache-read/-write prices. `make_engine` refuses an unpriced model or a missing key before any call. Each model call writes a `turn_cost` audit record and an `llm_call` trace event; `run_end` carries `session_id`, `turns` and `providers`, so `scripts/agent_costs.py --by-session` rolls up REPL sessions.
- **Switching.** `Session.switch_engine` swaps the engine without ending the session, writes a `provider_switch` audit record, and the new engine rebuilds its messages from the same transcript. `/provider <name> [model]` and `/model <name>` use it; `agent-shell demo --provider [fake|claude|openai] --model ...`.
- **Keys.** Passed to the model client, never exported. OpenAI uses `CHAT_OPENAI_API_KEY`, falling back to `PRODUCTION_AGENTS_OPENAI_API_KEY`; Claude uses the runtime's Anthropic key.

## Tests

- Contract suite (`tests/lg/test_contract.py`): the fake and the engine in both provider shapes (Anthropic-style content blocks, OpenAI-style strings) through a scripted chat model: text, tool call, gate accept, gate reject, dry-run, budget stop, interrupt, resume.
- Live (`tests/lg/test_live.py`, `@pytest.mark.live`, skipped unless `AGENT_SHELL_LIVE=1`): a tool turn on each provider, a Claude → OpenAI → Claude switch that keeps the conversation, and a Claude cache-read check.

## Run the live tests

```bash
op run --env-file=.env -- env AGENT_SHELL_LIVE=1 AGENT_SHELL_LIVE_OPENAI_MODEL=<model with a price row> \
    uv run pytest packages/agent-shell -m live -v
```

## Risks

- Cache markers depend on `langchain-anthropic` passing `cache_control` through; a request-builder test guards it. Caching only helps above the provider's minimum prompt size.
- Anthropic extended thinking is not enabled (the transcript stores text only).
- Dropped history is not summarised.
- Model prices change; rows in `agent_runtime.budget._PRICING` carry a "sourced" date.
- Plan B: any of the Claude Agent SDK, OpenAI Agents SDK or a raw-API loop can replace this module behind the same protocol; tools and gates do not change.
