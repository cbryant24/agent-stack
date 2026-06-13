---
title: Orchestrator — LangGraph Ingestion (between Phase 1 and Phase 2)
date: 2026-06-09
type: research-signals
agent: orchestrator
project: agent-stack
status: active
---

# Orchestrator — LangGraph Ingestion

Closes the one cold-start gap the [Phase 2 handoff](orchestrator-phase2-handoff.md) names before implementation: LangGraph is new to this stack (every built agent is plain sequential LangChain). Mirrors the ElevenLabs seeding pattern in [voiceover-direction-phase1-research-signals.md](voiceover-direction-phase1-research-signals.md) — two collections, two paths, split by content type:

- **`user_knowledge` (`domain="langgraph_mechanics"`)** — LangGraph's own reference docs. Authoritative ground truth for the API surface the build depends on (`StateGraph`, `ToolNode`, conditional edges, `SqliteSaver`, `bind_tools`). You collect these as markdown; `scripts/ingest_user_knowledge.py` ingests them. This is the primary path — the build needs precise API facts, which live in text docs, not video.
- **`tutorial_research`** — conceptual ReAct/orchestration patterns and practical know-how the reference docs don't teach. Populated by running the `tutorial-research` agent directly.

**Where to run:** the original Mac, which hosts Qdrant. Both writes land in the authoritative store at the default `QDRANT_URL` (`localhost:6333`), using the `.env` keys already there. **No `QDRANT_URL` change is needed for this step** — that variable is only for pointing the *new* Mac at the shared host later.

**Currency note:** the LangGraph Python docs moved from `langchain-ai.github.io/langgraph` (the URL the handoff cites) to **`docs.langchain.com/oss/python/langgraph`**, with the API reference at **`reference.langchain.com/python`**. The URLs below are current as of 2026-06-09. LangGraph's API moves — re-check each page when you collect it rather than trusting a cached version, and prefer the official docs over third-party tutorials for mechanics.

---

## A. LangGraph docs to collect as markdown → `user_knowledge`

Save each page as a markdown file in one folder, e.g. `~/agent-data/sources/langgraph-docs/`. The script does **not** fetch these — you collect them, so you can currency-check and strip nav/boilerplate.

**Collection format (matches the parser):**

- One `.md` file per page.
- Start each file with frontmatter recording the URL, so the entry's source is the page (not a local path):

  ```markdown
  ---
  source_url: https://docs.langchain.com/oss/python/langgraph/persistence
  ---
  ```

- Keep the page's heading structure. Each **H2/H3** section becomes one verified `user_knowledge` statement, and the heading hierarchy becomes its `topic_tags`; **H1** is treated as the page title only. So keep sections self-contained and factual, and drop site chrome.

**Pages, grouped by the handoff's four topic areas:**

Graph construction (`StateGraph`, nodes, edges, the agent/tools loop):

- https://docs.langchain.com/oss/python/langgraph/quickstart
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://reference.langchain.com/python/langgraph/graph/state/StateGraph
- https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges

Tool-calling nodes and routing (`ToolNode`, `tools_condition`):

- https://reference.langchain.com/python/langgraph.prebuilt/tool_node/ToolNode
- https://reference.langchain.com/python/langgraph.prebuilt/tool_node/tools_condition

Persistence / checkpointers (`SqliteSaver`, thread-keyed resume — the conversation-continuity backbone):

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://reference.langchain.com/python/langgraph/checkpoints
- https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver

Binding tools to the model and reading tool calls back (`langchain-anthropic`):

- https://reference.langchain.com/python/langchain-anthropic/chat_models/ChatAnthropic/bind_tools
- https://reference.langchain.com/python/integrations/langchain_anthropic/ChatAnthropic/

> Package note while collecting: `SqliteSaver` ships in its own package — `langgraph-checkpoint-sqlite` (`from langgraph.checkpoint.sqlite import SqliteSaver`), with an `AsyncSqliteSaver` variant. The orchestrator's dependency set is therefore `langgraph`, `langgraph-checkpoint-sqlite`, and the already-present `langchain-anthropic`. (Captured here as a build input; not something to ingest.)

**Then ingest** (on the original Mac, from the repo root):

```bash
uv run python scripts/ingest_user_knowledge.py ~/agent-data/sources/langgraph-docs --domain langgraph_mechanics
```

Confirm sections interactively (y/n/edit/defer), or add `--yes` to accept all, or `--dry-run` to see the parse counts first. Re-runnable — already-ingested sections are skipped, so you can collect more pages and run it again.

---

## B. `tutorial-research` runs → `tutorial_research`

Run these directly in iTerm2 on the original Mac. They populate the conceptual/orchestration know-how the reference docs don't cover. (Invocation form per the handoff; adjust flags to your `tutorial-research` CLI.)

```bash
tutorial-research "LangGraph ReAct agent loop design patterns and best practices"
```

```bash
tutorial-research "LangGraph multi-tool orchestration and conditional routing patterns"
```

```bash
tutorial-research "LangGraph checkpointer and conversation memory patterns for chat agents"
```

```bash
tutorial-research "building tool-calling agents with LangGraph and Anthropic Claude"
```

These land in `tutorial_research`, which the Orchestrator will query via its `search_knowledge(query, domain="...")` tool the same way it reaches every other collection.

---

## Done condition

The gap is closed when `langgraph_mechanics` exists in `user_knowledge` with the reference-doc sections above, and the `tutorial_research` runs have completed. At that point Phase 2 implementation builds against a closed gap, and the first build slice (orchestrator scaffold) can begin.
