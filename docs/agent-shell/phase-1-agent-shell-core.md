# Phase 1 — `agent-shell` core

**Goal:** a provider-neutral REPL core with no LLM SDK in it, proven with a scripted fake engine.

**Depends on:** Phase 0. **Spends GPU:** no. **LLM spend:** none.

## Design

New workspace member `packages/agent-shell` (import name `agent_shell`). It depends on `agent-runtime` and on no agent package.

This is the "Conversational query mode" already specified in `docs/v2-refinements/agent-runtime-v2-refinements.md`, extended to tool use. It is a sibling package, not a module of `agent-runtime`, so the runtime's dependency set stays free of agent SDKs. Agents opt in by supplying a `ChatConfig` and exposing `<agent> chat`.

```
src/agent_shell/
  tools/registry.py     # ToolSpec, EffectClass, Registry
  tools/executor.py     # validate -> gate -> dry-run -> call -> ToolResult -> audit
  guard/gate.py         # confirm policy, session budgets
  audit/log.py          # JSONL + OTel spans through agent-runtime tracing
  session/store.py      # SQLite: neutral transcript + per-provider native handles
  engine/base.py        # Engine protocol and events
  engine/fake.py        # scripted engine for tests and demos
  session/api.py        # front-end-neutral session API (the REPL is one front end)
  proposals.py          # end-of-session proposal queue
  repl/app.py           # prompt_toolkit input, Rich output, slash commands
  mcp_export.py         # optional: expose a registry as an MCP server
  config.py             # pydantic-settings; ChatConfig
```

### Tool contract

```python
class EffectClass(str, Enum):
    NONE = "none"                        # pure
    READ = "read"                        # local reads, Qdrant queries
    EXTERNAL_READ = "external_read"      # network read, no spend
    LLM_SPEND = "llm_spend"              # paid LLM call inside the tool
    GPU_SPEND = "gpu_spend"              # pod time, ElevenLabs characters
    MEMORY_WRITE = "memory_write"        # Qdrant or knowledge-base write
    DESTRUCTIVE_LOCAL = "destructive_local"

class ToolSpec(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    effect: EffectClass
    handler: Callable[..., Awaitable[ToolResult]]
    preview: Callable[..., str] | None = None   # text shown in the confirm panel

class ToolResult(BaseModel):
    text: str               # short summary for the model
    data: dict = {}         # structured payload (ids, counts)
    artifacts: list[str] = []
    is_error: bool = False
```

Differences from the orchestrator, on purpose: results are structured, errors are flagged as errors, and summaries stay small (ids plus one line; full detail on request).

### Gate

- `GPU_SPEND`, `DESTRUCTIVE_LOCAL`: always y/n, showing exact arguments, the tool's preview, and the target.
- `MEMORY_WRITE`: the repo's standard y/n/edit/defer. Edit reopens the payload for change before writing. Defer queues it under `~/agent-data/drafts/<agent>/` for a later session, matching music-curation's deferred-taste queue.
- `LLM_SPEND`: counted against the session budget; prompts only when the remaining budget would be exceeded.
- `--dry-run` or `/dry-run on`: gated tools return what they would do and perform nothing.
- Session budgets: one for REPL LLM cost, one for tool LLM cost (child `BudgetEnvelope`), one for GPU. They stay separate, matching the repo's "two budgets stay orthogonal" rule.

### Engine interface

```python
class Engine(Protocol):
    provider: Literal["claude", "openai", "fake"]
    async def start(self, system_prompt: str, tools: list[ToolSpec], session: SessionRef | None) -> SessionHandle: ...
    def send(self, handle: SessionHandle, user_text: str) -> AsyncIterator[EngineEvent]: ...
    async def interrupt(self, handle: SessionHandle) -> None: ...
    async def close(self, handle: SessionHandle) -> None: ...
```

Events: `TextDelta`, `ToolCallStarted`, `ToolCallFinished`, `TurnCost`, `TurnEnd`.

### REPL

- Click for the outer CLI (repo convention).
- `prompt_toolkit` for input: file history, multi-line, slash-command completion, Ctrl-C interrupts the turn.
- `Rich` for output: streamed Markdown, confirm panels, per-turn cost footer.
- Slash commands handled locally with no LLM call: `/help /exit /cost /budget /dry-run /tools /audit /session list|resume|rename /provider /model`.

### What an agent supplies

```python
class ChatConfig(BaseModel):
    agent_name: str                    # "visual-generation"
    system_prompt: str
    tool_pack: Callable[[], list[ToolSpec]]
    default_budget: BudgetEnvelope     # per session
    on_session_end: Callable[..., list[Proposal]] | None = None
```

### End-of-session proposals

Kept from the recorded design: writes are never silent, and conclusions outlast the transcript. On `/exit` the shell lists anything proposed but not yet written (interpretations, lesson candidates, deferred items) and walks through them with y/n/edit/defer.

### Front ends and MCP

The session API (`start`, `send`, `events`, `confirm`) has no terminal code in it. The REPL is the first front end; the design docs list Telegram, voice and web as possible later ones. `mcp_export.py` turns a registry into an MCP server, which covers the docs' planned "agents as MCP servers" and lets Claude Code call the same tools. The executor still gates every call made through MCP.

### Audit and sessions

- Audit JSONL at `~/agent-data/runs/<date>/<app>/<session_id>/audit.jsonl`: every tool call, arguments, gate decision, result summary, cost, provider, model. Same root the existing `scripts/agent_costs.py` reads.
- Session store in `~/agent-data/agent-stack.db`, tables prefixed `agent_shell_`. The design docs make that file the single relational store and plan the migration ledger there. The shell creates its own tables at startup, as the LangGraph checkpointer does today, until the migration runner exists.

## Tasks

1. Create the package and add it to the workspace members.
2. Implement the modules above.
3. Add an import-linter contract: `agent_shell` may import `agent_runtime` only.
4. Write a demo app with three fake tools (one per gate behavior) driven by `FakeEngine`.

## Acceptance

- `uv run pytest packages/agent-shell` passes offline with fake keys.
- Tests cover: gate accept, reject, edit and defer; dry-run; budget stop; interrupt; session resume; end-of-session proposals; slash commands (prompt_toolkit pipe input).
- The session API is exercised by a test front end with no terminal, proving the REPL is not required.
- The demo streams text, shows a confirm panel, honors dry-run, and resumes a session.
- `uv run ruff` and `uv run mypy` are clean for the new package (do not add to the 73-error baseline).
- No `claude-agent-sdk`, `openai-agents`, `langchain` or `langgraph` dependency.

## Risks

- Over-designing the event model. Keep to the five events until an adapter needs more.
- Confirm prompts fighting streamed output. The confirmer must pause the stream while it waits.

## Claude Code prompt

1. **Goal:** build the core package with tests; no LLM SDKs.
2. **Mode:** plan mode first, then direct.
3. **Files:** `@docs/agent-shell/00-overview-and-assessment.md @docs/agent-shell/phase-1-agent-shell-core.md @docs/audit/orchestrator-audit.md @docs/v2-refinements/agent-runtime-v2-refinements.md @pyproject.toml @packages/agent-runtime/README.md @packages/agent-runtime/src/agent_runtime/ @docs/naming-conventions.md`
4. **Prompt:**

```
Create workspace member packages/agent-shell (import agent_shell) exactly as specified in
docs/agent-shell/phase-1-agent-shell-core.md. Follow repo conventions in CLAUDE.md: Python
>=3.12, uv only, Click, Pydantic v2, pytest-asyncio, fake keys in tests.

Constraints:
- agent_shell may import agent_runtime and nothing from any agent package. Add an
  import-linter contract and a test that runs it.
- Reuse agent-runtime for budgets (BudgetEnvelope / BudgetTracker), tracing and config where
  the API fits. Read the source first and tell me where it does not fit before working around it.
- Do not add claude-agent-sdk, openai-agents, langchain or langgraph.
- Tool handlers return ToolResult; exceptions become ToolResult(is_error=True) with the
  exception type and message, and are recorded in the audit log.
- The confirmer is injected so tests can script answers. Memory writes support y/n/edit/defer;
  reuse the existing confirmation helpers in agent-runtime or music-curation if they are
  importable without pulling in an agent package, and tell me what you found.
- Session tables live in ~/agent-data/agent-stack.db with an agent_shell_ prefix. Do not touch
  the LangGraph checkpointer tables.
- mcp_export.py is optional in this phase: implement it only if it adds no new dependency;
  otherwise leave a stub and say so.

Deliver: the package, tests for every acceptance item in the phase doc, a FakeEngine demo
command (agent-shell demo), and a README.md for the package in the same style as the other
package READMEs. Run ruff, mypy and pytest for the new package and show me the results.
```
