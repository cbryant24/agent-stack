# Phase 2 — Engine adapters (Claude and OpenAI)

**Goal:** two `Engine` implementations that pass one shared contract suite, switchable per session.

**Depends on:** Phase 1, and a clean lock result from Phase 0. **Spends GPU:** no. **LLM spend:** a few cents of live smoke tests.

Before starting, write `docs/adr/0001-agent-shell.md` recording that this reverses the orchestrator spec's "LangGraph over the Claude Agent SDK" choice and why (overview §5).

SDK details below come from the official docs as researched on 2026-10-03. Both SDKs change often: re-check option names against current docs when building, and pin exact versions.

## Claude adapter (`engine/claude_sdk.py`)

- One `ClaudeSDKClient` per session.
- Compile the registry into `@tool` functions bundled with `create_sdk_mcp_server()`, passed through `ClaudeAgentOptions.mcp_servers`. Tool names surface as `mcp__<server>__<tool>`; map them back to registry names in events.
- Isolation from your interactive Claude Code setup: `setting_sources=[]` and `strict_mcp_config=True`. Without these the REPL inherits your user and project settings and MCP servers.
- Disable the built-in file and shell tools so only registry tools exist.
- List the registry tools in `allowed_tools` so the SDK never shows its own permission prompt. Our executor is the only gate.
- `include_partial_messages=True` for streaming.
- `max_budget_usd` as a backstop behind our session budget.
- Pass the API key through `ClaudeAgentOptions.env` only. Do not export `ANTHROPIC_API_KEY` in the shell: it would also change how your interactive Claude Code sessions are billed.
- Auth is an API key. Anthropic's docs do not allow claude.ai subscription login for agents built on the SDK.
- The SDK runs a bundled Claude Code CLI binary as a subprocess. An SDK upgrade is an engine upgrade.

## OpenAI adapter (`engine/openai_agents.py`)

- Compile the registry into `FunctionTool`s with `needs_approval=False` (our executor gates).
- `Runner.run_streamed(...).stream_events()` for streaming; map to the neutral events.
- `SQLiteSession` keyed by our session id for native history.
- Route or disable the SDK's built-in tracing so traces stay local. Verify the setting name.
- Key from `PRODUCTION_AGENTS_OPENAI_API_KEY` (already in `RuntimeConfig`), or a dedicated chat key for separate cost attribution, following the `ORCHESTRATOR_ANTHROPIC_API_KEY` precedent.

## How the differences are absorbed

| Concern | Claude Agent SDK | OpenAI Agents SDK | In `agent-shell` |
|---|---|---|---|
| Tool schema | JSON Schema, MCP content results | Pydantic / type hints, strict schema | `ToolSpec.input_model` generates both; `ToolResult` is normalized |
| Approval | `can_use_tool`, hooks | `needs_approval` interruptions | Executor gate before the side effect; SDK approvals off |
| Streaming | partial messages | `stream_events()` | Five neutral events |
| Sessions | CLI transcripts, `resume` | `Session` backends | Neutral transcript + native handle per provider |
| Cost | result cost, `max_budget_usd` | usage objects | One REPL budget; pricing for non-Claude models added per the Phase 0 finding |
| Prompt caching | harness-managed | automatic prefix caching | Byte-stable system prompt and tool list; volatile state only in user turns |

## Switching provider mid-session

`/provider openai` starts a new native session seeded with a generated summary plus the last N turns from the neutral transcript, and writes the switch to the audit log. Native history does not transfer between providers; the neutral transcript is the source of truth.

## The two provider settings

- **REPL engine provider:** this phase. Who runs the conversation and chooses tools.
- **Craft provider:** the existing `--provider` seam inside visual-generation. Its OpenAI implementation is a stub. Running the REPL on OpenAI still uses Anthropic for `draft` and needs the Anthropic key. Implementing the stub is a separate task and not part of this plan.

Every agent's internal chains run on `langchain-anthropic`. That is unaffected: the engine adapters run the conversation only.

## Tasks

1. Add both SDKs as optional extras of `agent-shell` (`agent-shell[claude]`, `agent-shell[openai]`), pinned exactly.
2. Implement both adapters.
3. Write the shared contract suite and run it against `FakeEngine`, Claude and OpenAI.
4. Add `--provider` and `--model` to the demo command, and `/provider`, `/model` slash commands.
5. Add cost reporting for both providers into the audit log and the agent-runtime trace so `scripts/agent_costs.py` shows REPL sessions.
6. Add 1Password items and `.env.example` entries for the new keys.

## Acceptance

- Contract suite green for all three engines: tool call, gate accept, gate reject, dry-run, budget stop, interrupt, resume.
- Live smoke test under `op run` with each provider, marked `@pytest.mark.live` and excluded from the default run.
- `/provider openai` and back works in one session and is recorded in the audit log.
- With the Claude adapter running, no setting, hook or MCP server from `~/.claude` or the repo's `.claude/` is loaded (test asserts the tool list equals the registry).
- Session cost appears in `scripts/agent_costs.py --by-session`.

## Risks

- **SDK churn.** Pin, and treat upgrades as their own change with the contract suite as the check.
- **Lock conflict with LangChain pins.** If Phase 0 found one, do the Phase 7 dependency removal first.
- **Plan B / C.** If an adapter proves unworkable, the fallback is a Pydantic AI adapter (model-agnostic, has deferred tool approval), then a hand-rolled loop on the raw Messages / Responses APIs. Either replaces one file; tools and gates do not change.

## Claude Code prompt

1. **Goal:** implement both adapters behind the Phase 1 `Engine` protocol.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/agent-shell/phase-2-engine-adapters.md @packages/agent-shell/ @docs/audit/orchestrator-audit.md @packages/agent-runtime/src/agent_runtime/config.py @.env.example`
4. **Prompt:**

```
Implement engine/claude_sdk.py and engine/openai_agents.py in packages/agent-shell per
docs/agent-shell/phase-2-engine-adapters.md.

Before writing code, read the current official docs for claude-agent-sdk (Python) and
openai-agents (Python) and list any option names in the phase doc that have changed. Show me
that list first.

Requirements:
- Both SDKs are optional extras, pinned to exact versions.
- The executor in agent_shell.tools.executor is the only approval gate. Configure each SDK so
  it never prompts on its own.
- Claude adapter must not load user, project or local Claude Code settings or MCP servers.
  Add a test that asserts the tool list seen by the model equals the registry.
- Pass API keys through SDK options, not by mutating os.environ globally.
- Write one contract test suite parameterized over fake, claude and openai engines. Live
  provider runs are marked @pytest.mark.live and skipped by default.
- Report REPL LLM cost per turn into the audit log and the agent-runtime trace, using the
  pricing approach recorded in docs/audit/orchestrator-audit.md.

Run the default test suite, then tell me the exact op run command to execute the live tests.
```
