# Phase 0 — Ground truth and unblockers

**Goal:** turn every [Unverified] item in `00-overview-and-assessment.md` into a fact, and confirm nothing in the environment blocks the build. No source changes.

**Spends GPU:** no. **LLM spend:** one cheap `recall` call.

## Why this phase still exists

The bundle answered most of the earlier open questions. What it could not answer needs a live repo: test results, the lockfile, four orchestrator files that were not included, and the current state of the §9 defects.

## Tasks

1. **`op run` health.** Run one API-calling command under `op run`. The 2026-07-15 retrospective recorded "'Personal' isn't a vault in this account". If it still fails, fix the `.env` `op://` references before anything else.
2. **Orchestrator tests, with Qdrant up.** `uv run pytest packages/orchestrator -v -rs`. Record failures and every skip with its reason.
3. **Read the four unseen orchestrator files:** `constants.py`, `retrieval.py`, `diagnostics.py`, `pyproject.toml`. Confirm the `search_knowledge` domain list and whether `technique_research_outputs` is in it.
4. **Confirm the verified defects with file:line** (overview §3, items 1-10).
5. **Visual-generation library surface.** For every CLI command in `cli.py`, record: backing library function, or "logic inline in `cli.py`". Expected inline candidates: `model sync/list/rm`, `workflow register/list`, `lesson add/list/rm`, `fact add/ingest-docs`, `canon set/show/edit/rm`, `batch list/rm`, `digest`, `review-pending`, `chain show`.
6. **§9 status table.** For each of the 13 open items in `coraline-failure-conclusions.md` §9: fixed or open, file:line, and whether a regression test exists. Item 1 (random seed not written to the graph) decides when Phase 5 can start.
7. **Known issues that touch the REPL:** KI-4 (generation status stays `PENDING`), KI-8 (template retrieval picks inpaint), and the batch-file regex that stops at the first `-->`.
8. **Provider seam.** Where it lives (agent-runtime or visual-generation), how aliases resolve, and what the OpenAI stub raises.
9. **Budget pricing table.** `BudgetTracker` prices "supported Claude models" from a hardcoded table. Record the table and how a non-Claude model would be costed.
10. **Dependency resolution.** On a scratch branch, add `claude-agent-sdk` and `openai-agents` to a throwaway member and run `uv lock`. Report conflicts with the LangChain/LangGraph pins. Revert.
11. **Payload models.** Dump the `visual_generation_memory` payload models (`VisualGeneration`, `TechniqueLesson`, `WorkflowTemplate`) with `parent_id` / `chain_root_id`.
12. **Shared database.** List everything that reads or writes `~/agent-data/agent-stack.db` and its current tables. The design docs plan to put the schema-migration ledger in the same file.
13. **LangChain usage map.** Which members import `langchain*` and which import `langgraph*`. The design docs say every agent's chains use `langchain-anthropic` and only the orchestrator uses LangGraph.
14. **Doc drift.** Orchestrator test count is 42 in `architecture.md` and 59 in the root README; record the real number.

## Outputs

- `docs/audit/orchestrator-audit.md`
- `docs/audit/visual-generation-tool-surface.md`
- `docs/audit/execution-truth-status.md`

## Acceptance

- Each [Unverified] item is marked confirmed or refuted with file:line.
- The tool-surface table covers every CLI command.
- The lock test has a recorded result.
- `op run` works, or the fix is recorded.

## Risks

None to the code. If the lock conflicts, the plan changes order: remove the orchestrator's LangGraph dependencies (Phase 7) before Phase 2.

## Claude Code prompt

1. **Goal:** factual audit, no source edits.
2. **Mode:** plan mode (Shift+Tab).
3. **Files:** `@CLAUDE.md @pyproject.toml @packages/orchestrator/ @packages/visual-generation/src/visual_generation/ @packages/agent-runtime/src/agent_runtime/ @packages/visual-generation/docs/coraline-failure-conclusions.md @docs/visual-generation-known-issues.md @docs/agent-shell/00-overview-and-assessment.md`
4. **Prompt:**

```
Audit this uv workspace before a redesign. Do NOT modify source files. Write findings only to
docs/audit/orchestrator-audit.md, docs/audit/visual-generation-tool-surface.md and
docs/audit/execution-truth-status.md. Cite file:line for every claim.

Step 1 - environment
- Run: op run --env-file=.env -- uv run visual-generation recall "audit smoke test"
  Report success, or the exact error. If the 1Password vault reference fails, stop and tell me.

Step 2 - orchestrator
- Bring Qdrant up (docker compose -f infrastructure/docker-compose.yml up -d), then run
  uv sync --all-packages && uv run pytest packages/orchestrator -v -rs
  Record failures and every skip with its reason.
- Read constants.py, retrieval.py, diagnostics.py, pyproject.toml. Report DEFAULT_BUDGET, the
  search_knowledge Domain list, and exact langgraph / langchain-* / anthropic versions from uv.lock.
- Confirm or refute each item in section 3 of docs/agent-shell/00-overview-and-assessment.md.

Step 3 - visual-generation tool surface
- Table: every CLI command in cli.py -> backing library function (module.function) or
  "inline in cli.py" -> signature -> return type -> side effects (LLM spend / GPU spend /
  Qdrant write / file write / none) -> collection and payload model touched.
- Dump the payload models stored in visual_generation_memory, including lineage fields.
- Describe the LLM provider seam: where it is defined, how model aliases resolve, what the
  openai provider does today.
- Report whether AGENT_PROJECTS_DIR exists in RuntimeConfig (the runtime v2-refinements list
  it as deferred).

Step 4 - execution truth
- For each of the 13 "still open" items in coraline-failure-conclusions.md section 9, report
  fixed or open, file:line, and whether a regression test covers it.
- Report the status of KI-4 and KI-8, and the batch_file.py metadata regex issue.

Step 5 - runtime
- Show the BudgetTracker pricing table and explain how a non-Claude model would be costed.

Step 6 - dependencies and shared state
- On a scratch branch, add claude-agent-sdk and openai-agents to a throwaway workspace member,
  run uv lock, report any resolution conflict, then delete the branch.
- List which workspace members import langchain* and which import langgraph*.
- List every reader and writer of ~/agent-data/agent-stack.db and its current tables.

End each file with a short list of open questions for me.
```
