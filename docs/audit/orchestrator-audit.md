# Orchestrator audit — agent-shell Phase 0

Audited 2026-10-04 against the working tree at `f17ae89` (main). No source files were
changed. Every orchestrator file cited here is clean in git, so all findings are in `HEAD`.
Checks `docs/agent-shell/00-overview-and-assessment.md` §2–§5 against the live repo.

Paths are relative to `packages/orchestrator/src/orchestrator/` unless they start with
`packages/` or `docs/`.

## 1. Environment (`op run`)

**Not verified.** The smoke test
`op run --env-file=.env -- uv run visual-generation recall "audit smoke test"` was declined
twice in the audit session and never ran. The 2026-07-15 "'Personal' isn't a vault in this
account" failure is therefore neither confirmed nor cleared. `CLAUDE.md:56` and the root
`README.md:35` still name the `Personal` vault. `.env` was not read.

Qdrant itself is up (`localhost:6333`, 7 collections) and its Docker healthcheck was fixed
in `f17ae89`.

## 2. Tests

`uv run pytest packages/orchestrator -v -rs` → **59 collected: 58 passed, 1 skipped, 0 failed**
(3.93 s, Qdrant up).

- Skip: `tests/test_diagnostics.py:354` `test_behavioral_probe_against_live_qdrant` —
  "collection not present on this live Qdrant".
- Real count is **59**. Root `README.md:19` says 59 (correct). `docs/architecture.md:811`
  and `:873` say 42 (stale).

Side effect of the prescribed `uv sync --all-packages`: it uninstalled a stale editable
install, `adult-video-generation==0.1.0` (`packages/adult-video-generation`), from `.venv`.
That directory does not exist on `main` and is not a workspace member. `uv.lock` is unchanged.

## 3. The four files the bundle lacked

| File | Finding |
|---|---|
| `constants.py:24-29` | `DEFAULT_BUDGET = BudgetEnvelope(max_items=12, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300)`. Matches the overview and `packages/orchestrator/README.md:134`. `max_depth=2` was not in the overview. |
| `constants.py:11,14` | `MODEL_ORCHESTRATOR = "claude-sonnet-4-6"`; `MODEL_UTILITY = "claude-haiku-4-5"` is declared but not wired. |
| `constants.py:33-37` | Child budget caps: 2 items, $0.50 or 30 % of parent cost, 180 s or 40 % of parent wall time. |
| `constants.py:40-43` | Checkpointer DB = `<agent_data_dir>/agent-stack.db`. |
| `retrieval.py:34-41` | `search_knowledge` `Domain` has **six** values: `tutorial_research`, `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`, `technique_research_outputs`, `langgraph_mechanics`. |
| `retrieval.py:71` | `technique_research_outputs` **is** a domain. |
| `diagnostics.py` | Report render/load (`:82`, `:150`), `behavioral_probe` (`:216`), remediation handler registry (`:283-295`). Text model `voyage-3-large`, multimodal `voyage-multimodal-3`, probe threshold 0.5 (`:70-74`). |
| `packages/orchestrator/pyproject.toml:15-17` | `langgraph>=1.0`, `langgraph-checkpoint-sqlite>=2.0`, `langchain-anthropic>=1.0`. Depends on 8 sibling agents (`:7-14`). |

Locked versions (`uv.lock`): `langgraph 1.2.1`, `langgraph-checkpoint 4.1.1`,
`langgraph-checkpoint-sqlite 3.1.0`, `langgraph-prebuilt 1.1.0`, `langgraph-sdk 0.3.15`,
`langchain 1.3.1`, `langchain-core 1.4.0`, `langchain-anthropic 1.4.3`,
`langchain-text-splitters 1.1.2`, `anthropic 0.104.1`, `pydantic 2.13.4`, `httpx 0.28.1`,
`click 8.4.1`.

## 4. Overview §2 — what the orchestrator is

| Claim | Verdict | Evidence |
|---|---|---|
| Entry points `chat [--thread]`, `remediate <report> [-y]` | Confirmed | `cli.py:24-26`, `cli.py:37-40` |
| Hand-rolled `StateGraph`, one `agent` + one `tools` node, only `ToolNode` from prebuilt | Confirmed | `graph.py:15-16`, `graph.py:163-169` |
| State = `messages` + `budget_exhausted`, `AsyncSqliteSaver`, keyed by thread id | Confirmed | `agent.py:72-76`, `cli.py:95-104` |
| Budget guard before each tool step | Confirmed | `graph.py:134-146` |
| Derived child budget for sub-agents | Confirmed | `tools.py:30-47` |
| 22 tools | Confirmed | `tools.py:815-840` (3 knowledge/repo + 16 sub-agent + 3 diagnostics) |
| Sibling agents called in-process | Confirmed | e.g. `tools.py:418-421` |
| Never writes to Qdrant; `remediate` delegates | Confirmed | `cli.py:80-86` |

## 5. Overview §3 — the ten complaints

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Visual surface is only `visual_draft(intent)` + `visual_recall(query)` | **Confirmed** | `tools.py:411-412`, `tools.py:442-443`. `visual_draft` passes only `intent` and a budget (`tools.py:421`). |
| 1 | CLI has "about 35 commands" | **Partly** | The CLI has **30** leaf commands in 7 groups — see `visual-generation-tool-surface.md`. |
| 2 | System prompt names only tutorial-research and music-curation | **Confirmed** | `graph.py:50-53` |
| 3 | No approval step inside the loop | **Confirmed** | No confirm in `graph.py`; the only one is `cli.py:80-81` in `remediate`. |
| 4 | Anthropic only | **Confirmed** | `agent.py:31-37` constructs `ChatAnthropic` directly. |
| 5 | No streaming; one-line `click.prompt` input | **Confirmed** | `agent.py:74`, `cli.py:112` |
| 6 | Whole thread re-sent each step; `read_file` up to 20,000 chars | **Confirmed** | `graph.py:108-118`, `tools.py:26`, `tools.py:126` |
| 7 | Tool results truncated to 8,000 chars; exceptions become strings | **Confirmed** | `tools.py:25`, `tools.py:64-67`; e.g. `tools.py:422-424` |
| 8 | `_record_delegation` writes `local_max_score=0.0, threshold=0.0` | **Confirmed** | `tools.py:58-59` |
| 9 | Private import of `_safe_attr` | **Confirmed** | `graph.py:21`, used at `graph.py:158` |
| 10 | Root README says "8 of 9" | **Refuted** | `README.md:19` says "8 of 10", same as `packages/orchestrator/README.md:16,72`. |
| 10 | `yt-intelligence-pipeline` and `video-clipping` not wrapped | **Confirmed** | Absent from `tools.py:815-840` and `pyproject.toml:7-14`. |
| 10 | CLAUDE.md says 12 workspace members | **Confirmed, and correct** | `packages/` holds 12 directories; `pyproject.toml:7` globs `packages/*`. |
| 10 | Orchestrator README omits `technique_research_outputs` from the domain list | **Confirmed (doc drift)** | `packages/orchestrator/README.md:69-71` lists five; code has six (`retrieval.py:34-41`). The technique-research README is right. |

## 6. Overview §4–§5 — claims this audit corrects

| Claim | Verdict | Evidence |
|---|---|---|
| "The other agents and `yt-intelligence-pipeline` reason through `langchain-anthropic`", so only LangGraph can be removed | **Refuted** | Only two members import LangChain at all: `orchestrator` (`langchain_core` ×5, `langchain_anthropic` ×1) and `yt-intelligence-pipeline` (`langchain_core` ×4, `langchain_anthropic` ×3). The other ten import neither and declare `anthropic>=0.40` directly. |
| Only the orchestrator uses LangGraph | **Confirmed** | `langgraph.graph`, `langgraph.graph.message`, `langgraph.prebuilt`, `langgraph.checkpoint.sqlite.aio` — orchestrator only. |
| `agent-stack.db` is the planned shared relational store | **Partly** | Today it holds only LangGraph's tables: `checkpoints` (171 rows, 7 threads) and `writes` (320 rows). No migration ledger exists yet. Last written 2026-06-13. |
| Readers/writers of `agent-stack.db` | **One** | `constants.py:43` → `cli.py:97-101`. No other package references the file or uses sqlite. |
| Provider seam exists; OpenAI craft provider is a stub that raises | **Confirmed** | Seam lives in **agent-runtime**, not visual-generation: `packages/agent-runtime/src/agent_runtime/llm/registry.py:13-30`, `llm/base.py:32-54`. Stub raises `NotImplementedError` at `llm/providers/openai.py:38-39,50`. Also used by `video-clipping`. |
| `PRODUCTION_AGENTS_OPENAI_API_KEY` in config | **Confirmed** | `packages/agent-runtime/src/agent_runtime/config.py:20-22`; default provider at `:23-25`. |
| `scripts/pod` does `up/down/status/watch` | **Confirmed** | `scripts/pod:652-655` (file has uncommitted changes). |

## 7. Dependency resolution test

Run in a scratchpad copy of the workspace (the checkout and its `uv.lock` were not touched):
a throwaway member depending on `claude-agent-sdk` and `openai-agents`, then `uv lock`.

**Result: resolves cleanly, no conflict.** 182 → 205 packages.

- Added: `claude-agent-sdk 0.2.163`, `openai-agents 0.23.1`, `openai 3.24.0`, `mcp 2.3.0`,
  plus transitive `starlette`, `uvicorn`, `sse-starlette`, `jsonschema`, `cryptography`,
  `pyjwt`, `httpx2`, and others.
- Bumped: `idna 3.16→3.20`, `jiter 0.15.0→0.17.0`, `urllib3 2.7.0→2.8.0`.
- Unchanged: every `langgraph*`, `langchain*`, `anthropic`, `pydantic`, `httpx`, `anyio`, `click` pin.

Consequence: the phase order stands. Phase 7 does not need to move ahead of Phase 2.

## Open questions

1. `op run` was never exercised. Does it work today, and is `Personal` still the right vault name?
2. `uv sync --all-packages` removed the `adult-video-generation` editable install from `.venv`. Is that package expected on this machine (another branch), and does it need reinstalling?
3. Since `yt-intelligence-pipeline` is the only other LangChain user, should Phase 7 plan to drop LangChain from the workspace entirely by porting it, or leave it?
4. `architecture.md` says 42 orchestrator tests and the orchestrator README omits a domain. Fix the docs now, or leave them since the package is to be frozen?
5. `agent-stack.db` has had no writes since 2026-06-13. Is the orchestrator in use at all, and does "keep it usable read-only during the build" still matter?
