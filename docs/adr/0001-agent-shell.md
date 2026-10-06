# ADR 0001 — agent-shell: a provider-neutral chat shell on a LangGraph engine

Status: accepted, 2026-10-06. Plan: `docs/agent-shell/`.

## Context

The orchestrator is the only chat agent. It cannot operate `visual-generation` (two tools out of about 30 commands), has no approval step inside its loop, is bound to one model vendor, does not stream, and its system prompt names two of eight wrapped agents. The runtime refinements backlog already specifies a reusable "conversational query mode" that agents opt in to.

The orchestrator spec recorded "LangGraph chosen over the Claude Agent SDK" for two reasons: explicit control of the loop, and provider portability. Portability was not delivered: the orchestrator constructs `ChatAnthropic` directly.

## Decision

1. Build `packages/agent-shell`, a provider-neutral REPL core. Agents opt in with a tool pack and a `chat` subcommand.
2. **LangGraph stays as the engine.** One engine, `engine/langgraph_engine.py`: a small model/tools `StateGraph` streaming through `astream_events`, with the model built from provider + model name (`langchain-anthropic` or `langchain-openai`). It is an optional extra (`agent-shell[langgraph]`); the shell core imports no LLM SDK, enforced by an import-linter contract that exempts only that module.
3. **The orchestrator is retired for its design, not its framework**: read-only tools, no approval gates, a stale prompt, no streaming, one vendor. Its replacement keeps the same framework with those faults fixed. Phase 7 removes the `orchestrator` package and keeps `langgraph`.
4. **Provider portability is delivered by the engine.** The neutral transcript (user, assistant with tool calls and their ids, tool results as `ToolResult.text`) is the source of truth. Every turn rebuilds the model's messages from it, so switching provider or model mid-session reuses the full history with nothing summarised.
5. **Our executor is the only approval gate.** Every tool call, whatever engine or front end made it, goes through validate, gate, dry-run, call, audit. No LangGraph interrupt-based approval is used.
6. Cost is strict: an unpriced model is refused before any call (`agent_runtime.budget.estimate_cost` returns `None`, where the older `add_llm_cost` silently priced it at $0). Each model call writes a `turn_cost` audit record and an agent-runtime trace event; `scripts/agent_costs.py --by-session` rolls them up.

## Alternatives considered

- **Claude Agent SDK and OpenAI Agents SDK adapters** (the earlier draft of Phase 2). Two SDKs means two session models, two tool schemas, two approval mechanisms, a bundled CLI subprocess for Claude, and an SDK upgrade being an engine upgrade. A single engine behind the same protocol is less to keep working.
- **Hand-rolled loop on the raw Messages / Responses APIs.** Possible later; replaces one file.
- **Pydantic AI.** Model-agnostic with deferred tool approval; not needed while the LangChain stack is already in the lock and used by every agent.

## Consequences

- The Claude Agent SDK and OpenAI Agents SDK remain possible future adapters behind the `Engine` protocol. Nothing here forecloses them.
- LangGraph is no longer orchestrator-only, so Phase 7 keeps it (and still removes `langgraph-checkpoint-sqlite` if nothing else uses it).
- Old turns beyond a fixed window (default 20) are dropped from what the model sees, not summarised. Anthropic extended thinking is not enabled, because the transcript stores text only and thinking blocks would have to be echoed back on tool turns.
- Anthropic prompt caching is enabled on the system prompt and tool definitions; it only pays off above the provider's minimum cacheable prompt size.
- Phase 1's saved-history format and `Engine.send` changed (structured messages with tool-call ids; `send` takes `history`). A guarded migration adds the new column to existing databases.
