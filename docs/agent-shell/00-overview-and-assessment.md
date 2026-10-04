# 00 — Overview and assessment (revised against the source bundle)

Revised 2026-10-03 after reading the 68-document bundle: orchestrator and agent-runtime source, visual-generation `cli.py`, all agent READMEs, `architecture.md`, `ai-director-agent-system.md`, the v2-refinement backlogs, handoffs and audits, plus the diffusion-prompter README. This replaces the earlier report where they disagree. Suggested home in the repo: `docs/agent-shell/`.

Labels: **[Verified]** = read in the bundle. **[Unverified]** = file not in the bundle; Phase 0 checks it.

## 1. Decision summary

| # | Decision | Confidence |
|---|---|---|
| 1 | Do not move the orchestrator to its own repo and do not extend it. Freeze it, then retire it (Phase 7). | High |
| 2 | Build a new workspace package `agent-shell` (provider-neutral REPL core). Each agent opts in with a `chat` subcommand and a tool pack inside its own package, starting with `visual-generation chat` (alias `visual-agent`). | High |
| 3 | Engine: neutral tool registry + `Engine` interface, with a Claude Agent SDK adapter and an OpenAI Agents SDK adapter. Ollama excluded. | High |
| 4 | Approval gates run in our own tool executor, so they behave the same under both providers. | High |
| 5 | Only the owning agent writes to its Qdrant collection. New write paths (`record_evaluation`) are store functions inside `visual-generation`; chat tools only call them. | High |
| 6 | The REPL does not wrap `generate` until the execution-truth defects are fixed and Gate 0 passes. | High |
| 7 | Pod lifecycle wraps the existing `scripts/pod` (create/delete model). No new RunPod client in v1. | Medium-high |
| 8 | This reverses a recorded design decision (LangGraph over the Claude Agent SDK) and implements a deferred one (runtime conversational mode). Both are documented in §5. | High |

## 2. What the orchestrator is [Verified]

- **Role:** conversational "director's console" over the workspace. Entry points: `orchestrator chat [--thread <id>]` and `orchestrator remediate <report> [-y]`.
- **Loop:** a hand-rolled LangGraph `StateGraph` (`graph.py`): one `agent` node (Sonnet via `langchain-anthropic`, all tools bound) and one `tools` node wrapping `langgraph.prebuilt.ToolNode`. It is not `create_react_agent`.
- **State:** `messages` + `budget_exhausted`, checkpointed with `AsyncSqliteSaver` at `~/agent-data/agent-stack.db`, keyed by thread id.
- **Budget:** per-turn `BudgetTracker` (`max_items=12` tool calls, `max_cost_usd=1.50`, `max_wall_time_sec=300` per the README FAQ). A guard runs before each tool step. Sub-agent calls get a derived child budget.
- **Tools (22):** `search_knowledge`, `read_file`, `grep`; two tools each for tutorial-research, music-curation, voiceover-direction, concept-script, visual-generation, technique-research, edit-brief, feedback-iteration; three diagnostics tools. Sibling agents are called in-process through their library functions.
- **Hard rule:** free / non-side-effecting ops only. `generate` (GPU) and TTS are deliberately excluded. The orchestrator never writes to Qdrant; `remediate` delegates the write to the owning agent.

## 3. Why it does not do what you want

### Verified in the source

1. **It cannot operate visual-generation.** Its visual surface is `visual_draft(intent)` and `visual_recall(query)`. The CLI has about 35 commands (`redraft`, `generate`, `report`, `quick`, `batch`, `canon`, `lesson`, `fact`, `workflow`, `model`, `chain`, `digest`, `knowledge-verify`, `research`, `explain`). `visual_draft` takes only an intent: no project, template, `--from`, image, mask or canon.
2. **Stale system prompt.** `SYSTEM_PROMPT` in `graph.py` tells the model to "use the tutorial-research and music-curation tools to delegate real work". It never mentions the other six agents' tools, so the model under-uses them.
3. **No approval step inside the loop.** The only confirm is in the separate `remediate` command. Adding spend or writes to the loop means building gates it was designed not to have.
4. **Anthropic only.** `build_app` constructs `ChatAnthropic` directly. There is no provider switch.
5. **Thin REPL.** `graph.ainvoke` returns the whole answer at once (no streaming). Input is `click.prompt`: one line, no history, no slash commands, no interrupt.
6. **Cost shape.** Every step re-sends the whole thread, and `read_file` results (up to 20,000 chars) stay in context. Turns hit the caps and end as "partial". The README FAQ documents this.
7. **Lossy tool results.** Every tool returns a string truncated to 8,000 chars and converts exceptions into strings. The model gets no structured data and failures do not surface as failures.
8. **Fake values in tuning traces.** `_record_delegation` writes `local_max_score=0.0, threshold=0.0` into `record_delegation_decision`, which exists for threshold tuning.
9. **Private import.** `graph.py` imports `_safe_attr` from `agent_runtime.tracing.decorators`.
10. **Coverage and doc drift.** `yt-intelligence-pipeline` and `video-clipping` are not wrapped. The root README says "8 of 9", the package README says "8 of 10", `CLAUDE.md` says 12 workspace members. The technique-research README says the orchestrator reads `technique_research_outputs` as a `search_knowledge` domain, but the orchestrator README lists five domains without it.

### Environment issue to rule out first

- **`op run` vault failure.** The 2026-07-15 retrospective records `op run` failing with "'Personal' isn't a vault in this account", which blocks every API-calling command. `CLAUDE.md` still names the `Personal` vault. Current status is unknown; Phase 0 checks it before anything else.

### Unverified

- `constants.py`, `retrieval.py`, `diagnostics.py`, the tests and `pyproject.toml` were not in the bundle. Whether the 59 tests pass today, and whether the LangGraph/LangChain pins conflict with the two new SDKs, is for Phase 0.

## 4. What changed from the earlier report

| Earlier claim | Correction |
|---|---|
| Orchestrator probably uses the prebuilt ReAct agent | It is hand-rolled; only `ToolNode` comes from `langgraph.prebuilt`. |
| RunPod lifecycle is new scope; prefer resuming a persistent pod | `scripts/pod` already does `up/down/status/watch`. Pods are created and deleted, never started/stopped, because a stopped pod is pinned to its host. Models live on the `stably_diffused` Global Volume. |
| Library functions may not exist | They do: `draft_sync`, `redraft_sync`, `batch_project_sync`, `plan_generation_sync`, `spend_generation_sync`, `report_sync`, `quick_generate_sync`, `explain_sync`, `research_sync`, `verify_knowledge`, `recall`. The plan/spend split is the gate seam. |
| Provider switching is entirely new | visual-generation already has a provider seam (`--provider anthropic|openai`) and config has `PRODUCTION_AGENTS_OPENAI_API_KEY`. The OpenAI craft provider is a stub that raises. |
| Use Typer | Repo convention is Click. Use Click. |
| Classify feedback as prompt / implementation / outcome | Use the evaluation charter's three score layers and the retrospective's conditioning-first rule (Phase 4). |
| Separate `<agent>-tools` and app packages | No new package per agent. Each agent gets a `chat/` module and a `chat` subcommand, as the runtime v2-refinement already specified. |
| LangChain can be removed with the orchestrator | Only `langgraph` and its SQLite checkpointer can. The other agents and `yt-intelligence-pipeline` reason through `langchain-anthropic`. |
| `agent-stack.db` is the orchestrator's | It is the planned shared relational store (migration ledger). |
| "Bake-off queue, Phase 3B, Phase 5" | Those names are not in the bundle (the Consolidated Audit was not included). The matching sequence is the 12-step progression in `project-instructions.md` and Gates 0-6 in `evaluation-charter.md`. |

## 5. How this fits decisions already recorded in the repo

### It reverses "LangGraph over the Claude Agent SDK"

`ai-director-agent-system.md` records that the Agent SDK was evaluated for the orchestrator and LangGraph was chosen for two reasons: explicit control over the loop, and provider portability.

- **Provider portability was not delivered.** `build_app` constructs `ChatAnthropic` directly. The new `Engine` interface delivers it: two adapters, switchable per session.
- **Explicit control moves, it is not lost.** The SDK owns the model loop. Our executor owns everything the hand-rolled graph existed to control: the budget guard before each tool, tracing per tool call, and the approval gate.
- **If you still want to own the loop itself**, the fallback is a third adapter: a hand-rolled loop on the raw Messages / Responses APIs. It replaces one file.

Record the reversal as `docs/adr/0001-agent-shell.md` and update the "Technology" paragraph of the orchestrator spec when Phase 7 lands.

### It implements the deferred "Conversational query mode"

`agent-runtime-v2-refinements.md` already specifies a runtime-level REPL that any agent opts into (`music-curation chat`), with the agent supplying its system prompt, collections and proposable memory types, and writes that are "never silent". That is this project. What this plan keeps from it and what it changes:

| Recorded design | This plan |
|---|---|
| Runtime-level capability, agents opt in | Same. Lives in a sibling package `agent-shell`, not inside `agent-runtime`, so `agent-runtime` stays free of LLM agent SDKs. |
| CLI surface `<agent> chat` | Same: `visual-generation chat`. Works with the existing `agent()` wrapper. |
| Retrieval-only conversation | Extended: tool-using, so it can craft, generate and operate the pod. |
| End-of-session proposals, y/n/edit/defer | Kept, and added per-write confirmation during the session with the same four choices. |
| History not persisted across sessions | Changed: sessions are resumable, as in the orchestrator. Conclusions still persist through confirmed writes. |
| Build after music-curation structured references | Not applicable: the trigger here is visual-generation. |

### Other recorded principles it follows

- **"Standalone over orchestrated"** and the rejected "single monolithic app": per-agent chat, router optional and last.
- **"Agents import the runtime, never reimplement its concerns"**: budgets, tracing, memory and config come from `agent-runtime`.
- **Planned MCP exposure and other surfaces** (Telegram, voice, web): the tool registry can be exported as an MCP server, and the session API is separate from the terminal front end, so another surface is a new front end, not a new agent.
- **One relational store.** The planned schema-migration ledger shares `~/agent-data/agent-stack.db` with the orchestrator's checkpointer. The shell's session tables go in the same file with an `agent_shell_` prefix.
- **Working-relationship rules**: no timelines in these docs; each Claude Code prompt appears once, in final form.

## 6. The finding that most affects sequencing

`coraline-failure-conclusions.md` §9 lists 13 open defects and says to fix them "before any further generation, on any model". The first: a random seed is recorded but never written to the submitted graph. `project-instructions.md` repeats that this defect "remains present until code and a regression test prove otherwise".

A REPL that records structured evaluations against generation records would store verdicts about settings that never ran. So Phase 5 (GPU) is blocked on Gate 0 (execution truth). Phases 1-4 are not blocked: they spend no GPU.

## 7. Target architecture

```
packages/
  agent-runtime/          # gains AGENT_PROJECTS_DIR; stays free of LLM agent SDKs
  agent-shell/            # NEW: registry, executor, gate, audit, session store, Engine, REPL
  visual-generation/
    src/visual_generation/
      chat/               # NEW: tool pack, schemas, system prompt, label resolver
      ...                 # gains thin library functions + record_evaluation
  orchestrator/           # frozen, removed in Phase 7
scripts/pod               # wrapped by the chat pod tools in Phase 5
```

`visual-generation` depends on `agent-shell` core (prompt_toolkit, Rich, no LLM SDK). The two engine SDKs are optional extras of `agent-shell`.

Rules:

- `agent-shell` imports no agent package. Enforced by an import-linter contract.
- Tool packs call library functions and contain no Qdrant client code. The one subprocess exception is the bash `scripts/pod` family.
- Every tool declares an effect class. `GPU_SPEND`, `MEMORY_WRITE` and `DESTRUCTIVE_LOCAL` always prompt. Memory writes use the repo's y/n/edit/defer vocabulary.
- Two provider settings exist and are independent: the **REPL engine** provider (who runs the conversation) and the **craft** provider (who writes specs inside `draft`). In v1 craft stays Anthropic.

## 8. Phase map

| Phase | Document | Spends GPU | Blocked by |
|---|---|---|---|
| 0 | Ground truth and unblockers | No | — |
| 1 | `agent-shell` core | No | 0 |
| 2 | Engine adapters | No | 1 |
| 3 | visual-generation chat: read and craft | No | 2 |
| 4 | visual-generation chat: evaluation and memory writes | No | 3 |
| 5 | visual-generation chat: generation and pod lifecycle | Yes | 4 + Gate 0 |
| 6 | Onboard other agents, optional router | Varies | 4 |
| 7 | Retire the orchestrator | No | 6 (partial) |

## 9. Decisions

| Decision | My pick | Confidence |
|---|---|---|
| Fix the §9 execution-truth items in parallel with Phases 1-4 | **Decided 2026-10-03: yes**, as their own Claude Code sessions. | — |
| Implement the OpenAI craft provider (the stub)? | Not in this plan. REPL engine switching does not need it. | Medium |
| Keep the orchestrator usable read-only during the build? | Yes, frozen. One small fix: the stale system prompt. | Medium |
| Default REPL engine | Claude; OpenAI selectable per session. | Medium |
| `chat` module inside each agent package, or a separate `<agent>-agent` package? | Inside the agent package. It matches the recorded design, keeps writes with the owner, and works with the `agent()` wrapper. | Medium-high |
| Record the LangGraph-to-SDK reversal as an ADR? | Yes, before Phase 2. | High |
