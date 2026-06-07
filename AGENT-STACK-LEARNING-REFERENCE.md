---
title: Agent-Stack Learning Reference
subtitle: The technologies, concepts, and infrastructure behind our AI agents — what they are and why we use them
type: reference
audience: engineer onboarding into the agent-stack as a learner
status: living document
---

# Agent-Stack Learning Reference

This document is a **map, not a tutorial.** It lists every technology, concept, and
piece of infrastructure that goes into the agents we build in `agent-stack`, says in a
sentence or two **what each thing is**, and — more importantly — **why it's relevant to
what we're building**. It does *not* try to teach any of these in depth. Its job is to
be the reference a learning project hangs off of: drop it into a Claude Code (or Claude
desktop) project, and you'll have a stable surface to ask context-aware questions
against and get context-aware answers back.

If a term here is unfamiliar, that's expected — that's what the project chat is for.
Pick a topic, ask about it, and the project's instructions (see the companion
`AGENT-STACK-LEARNING-PROJECT-INSTRUCTIONS.md`) will gauge where you are and meet you
there.

> **What we're building, in one line:** a set of *standalone, domain-specialized AI
> agents* (research, music, voiceover, scriptwriting, …) that multiple apps call as
> shared specialists, all sitting on one reusable runtime. Every entry below earns its
> place in service of that.

---

## How to read each entry

Each item follows the same shape:

- **What it is** — the plain definition.
- **Why it's relevant here** — the specific job it does in *our* stack. This is the part
  that makes the reference worth more than a glossary.

Topics are grouped, but the groups are porous — many concepts touch several layers.

---

## 1. AI agent foundations (the concepts)

These are the ideas that define *what an agent is* in this stack, independent of any
specific library.

### Large Language Model (LLM)
- **What it is.** A model trained to predict text that, at scale, can reason, write,
  classify, summarize, and follow instructions. We use Anthropic's Claude family.
- **Why it's relevant here.** The LLM is the "reasoning engine" of every agent. An agent
  is mostly *an LLM plus structure around it* — budgets, memory, tools, and a defined
  job. Understanding what an LLM can and can't do reliably is the foundation for
  everything else.

### AI agent (our definition)
- **What it is.** A standalone, domain-specialized capability built around an LLM: it
  does **one domain** well, is **independently invokable** (CLI + library entry point),
  and knows **nothing about the apps** that call it.
- **Why it's relevant here.** This is *the* organizing idea of the whole stack. We don't
  build "features of an app"; we build specialists that many apps reuse. Every design
  choice downstream follows from this.

### Prompt engineering & system prompts
- **What it is.** The practice of shaping an LLM's behavior through its instructions. A
  *system prompt* sets persistent role/rules; user/turn prompts carry the task.
- **Why it's relevant here.** Each agent's behavior lives largely in its prompts (see
  `chains.py` in any agent). Getting the system prompt right is how we make an agent
  reliably "stay in its lane" and produce structured output.

### Context window & token budgets
- **What it is.** An LLM can only "see" a fixed amount of text at once (its context
  window), measured in *tokens*. Every word in and out costs tokens, and tokens cost
  money and time.
- **Why it's relevant here.** Token budgets are *real constraints* we design around. It's
  why we split design (chat) from implementation (Claude Code), why we split builds into
  phases, and why agents carry explicit cost budgets. "Context discipline" is a recurring
  theme.

### Tool use / function calling
- **What it is.** Giving an LLM a set of callable functions (with typed schemas) it can
  choose to invoke, so it can act in the world (search, read files, query a database)
  rather than only emit text.
- **Why it's relevant here.** Tool use is how an agent does anything beyond talking —
  calling Tavily to search, querying Qdrant for memory, delegating to another agent. The
  agent reasons; tools let it act.

### Model selection / cost routing
- **What it is.** Choosing *which* model handles *which* sub-task: a strong, expensive
  model for hard reasoning; a cheap, fast model for simple classification/scoring.
- **Why it's relevant here.** We route reasoning chains to **Sonnet** and cheap
  scoring/classification to **Haiku**. This keeps quality high where it matters and cost
  low where it doesn't. Knowing *when a task is "Haiku-cheap"* is a real design skill.

### Multi-agent systems
- **What it is.** Multiple specialized agents that cooperate, rather than one monolithic
  "do-everything" agent.
- **Why it's relevant here.** Our entire stack is multi-agent. Specialists compose better,
  are independently testable, and are reusable across apps. The cost is coordination —
  which is what delegation and the runtime solve.

### Delegation (agent-to-agent calls)
- **What it is.** One agent calling another agent as a sub-task, passing along a *derived,
  depth-capped child budget* so nested calls can't run away.
- **Why it's relevant here.** It's how a "hub" agent (for us, research) gets reused: other
  agents `delegate()` to it instead of re-implementing its capability. The depth cap and
  child budget are what make delegation safe.

### Stateful vs. stateless agents
- **What it is.** A *stateful* agent remembers across runs (it has a memory store); a
  *stateless* agent computes fresh each time and keeps nothing.
- **Why it's relevant here.** We decide this per agent with a sharp test: *does the agent
  have a feedback loop that accumulates learning?* If yes (music, voiceover) → stateful.
  If no (tutorial-research) → stateless. This prevents "storage with no learning" — memory
  that costs complexity but never improves output.

### Memory & feedback loops
- **What it is.** An agent storing past outcomes (often a `report`/`reaction` signal) and
  retrieving them later to improve future output.
- **Why it's relevant here.** Memory only earns its place when there's a *signal worth
  remembering*. The feedback loop — user reacts to a result, that reaction feeds future
  retrieval — is what turns a vector store into actual learning.

### Retrieval-Augmented Generation (RAG)
- **What it is.** Before answering, fetch relevant documents/snippets from a knowledge
  store and put them in the LLM's context, so the answer is grounded in real data rather
  than the model's parametric memory.
- **Why it's relevant here.** This is the core pattern of our stateful agents and the
  ingestion pipeline: chunk content → embed → store in Qdrant → retrieve semantically at
  query time → feed to Claude. It's how agents "know" domain-specific things.

### Vector embeddings
- **What it is.** A numeric vector representation of text (or images) where semantic
  similarity becomes geometric closeness.
- **Why it's relevant here.** Embeddings are the substrate of all our retrieval. We embed
  with Voyage AI into 1024-dimensional vectors and store them in Qdrant. "Find similar
  meaning" becomes "find nearby vectors."

### Semantic search
- **What it is.** Searching by *meaning* (vector similarity) rather than exact keywords.
- **Why it's relevant here.** It's what `MemoryStore.search()` does. It's why an agent can
  recall a relevant past lesson even when the wording is completely different.

### Multimodal embeddings
- **What it is.** Embeddings that put images (with captions) and text into the *same*
  vector space, so you can search across both.
- **Why it's relevant here.** The YouTube pipeline ingests screenshots alongside
  transcripts; `voyage-multimodal-3` lets us retrieve visual moments by meaning. It's how
  an agent can "remember what was on screen."

### Model Context Protocol (MCP)
- **What it is.** An open protocol for exposing tools/data to an LLM application over a
  standard interface, so capabilities can be shared across clients.
- **Why it's relevant here.** It's a *planned surface* for our agents — beyond CLI and
  library entry points, MCP lets other clients call an agent as a tool. Understanding MCP
  matters as we broaden how agents are invoked.

### Budget governance
- **What it is.** Wrapping every run in explicit caps — items, cost, recursion depth, wall
  time — and tracking spend against them.
- **Why it's relevant here.** Every agent run is wrapped in a `BudgetTracker`. It's how we
  keep autonomous, LLM-calling, possibly-delegating agents from quietly burning money or
  looping forever. Budgets are a *first-class design input*, not an afterthought.

### Observability & tracing
- **What it is.** Recording structured events about what a system did (spans, costs, tool
  calls) so you can inspect and debug behavior after the fact.
- **Why it's relevant here.** Agents are non-deterministic and multi-step; without traces
  you can't tell *why* a run did what it did. We emit JSONL traces and OpenTelemetry spans
  for every run, then render them into human-readable reports.

---

## 2. The LLM layer

### Claude API / Anthropic SDK
- **What it is.** Anthropic's API for calling Claude models, accessed through the official
  Python SDK (`anthropic`, used async as `AsyncAnthropic`).
- **Why it's relevant here.** Every agent's reasoning goes through this. Note the gotcha:
  construct the client with the key explicitly (`AsyncAnthropic(api_key=...)`) because our
  config doesn't push keys into `os.environ`.

### Claude Sonnet
- **What it is.** A strong, balanced Claude model for reasoning-heavy work.
- **Why it's relevant here.** Our default for "reasoning chains" — synthesis, drafting,
  multi-step judgment. Where output quality matters, Sonnet runs.

### Claude Haiku
- **What it is.** A fast, cheap Claude model for lightweight tasks.
- **Why it's relevant here.** Our default for scoring/classification/filtering at volume
  (e.g. ranking search hits). Routing these to Haiku is a core cost lever.

### Pydantic & pydantic-settings
- **What it is.** `pydantic` defines typed, validated data models; `pydantic-settings`
  loads configuration (from `.env`) into typed config objects.
- **Why it's relevant here.** Every agent's inputs, outputs, and memory types are Pydantic
  models (`models.py`). `RuntimeConfig` is a pydantic-settings object. Typed models are how
  we keep LLM-shaped data structured and validated. (Gotcha: pydantic-settings does *not*
  populate `os.environ`.)

---

## 3. Retrieval & memory infrastructure

### Qdrant
- **What it is.** An open-source vector database. We run it locally in Docker, 1024-dim
  vectors, cosine distance.
- **Why it's relevant here.** It's the single store behind all agent memory and the
  ingestion pipeline. `MemoryStore` is the *only* code that talks to it directly —
  everything goes through that wrapper.

### Voyage AI (embeddings)
- **What it is.** An embeddings provider. We use `voyage-3-large` for text and
  `voyage-multimodal-3` for image+caption.
- **Why it's relevant here.** Voyage turns content into the vectors Qdrant stores and
  searches. The choice of embedding model determines retrieval quality. (Gotcha: like the
  Anthropic client, construct it with the key explicitly.)

### Chunking
- **What it is.** Splitting a long document into retrieval-sized pieces before embedding —
  optionally structure-aware (respecting headings/sections).
- **Why it's relevant here.** Retrieval quality depends on chunk size and boundaries. The
  runtime gives us `chunk_document` and `chunk_document_with_structure` so agents don't
  reinvent this.

### `user_knowledge` collection & the propose→confirm workflow
- **What it is.** A runtime-owned Qdrant collection of *first-party verified facts*, shared
  across agents, written through a propose-then-confirm flow rather than blindly.
- **Why it's relevant here.** It's the shared "ground truth" memory. An agent can *propose*
  a fact, but it becomes durable knowledge only on confirmation — which keeps the shared
  store trustworthy across all agents.

### Graceful memory degradation
- **What it is.** Retrieval composes several collections in parallel; if Qdrant is down or
  a collection is missing, that leg degrades to an empty result instead of crashing.
- **Why it's relevant here.** It's why an agent is useful *from a cold start with
  everything empty* and never hard-fails on missing memory. New agents should be built the
  same way.

---

## 4. Observability infrastructure

### OpenTelemetry
- **What it is.** A vendor-neutral standard for emitting traces/metrics from software.
- **Why it's relevant here.** Our tracing helpers (`@traced`, `span()`) emit OpenTelemetry
  spans so an agent's internal steps are observable in a standard format.

### Jaeger
- **What it is.** An open-source distributed-tracing UI/backend. We run it locally in
  Docker.
- **Why it's relevant here.** It's where you *see* the spans — visualize a run's steps,
  timings, and nesting. Paired with Qdrant in the same `docker-compose`.

### JSONL traces & run reports
- **What it is.** Every run also writes append-only JSON-lines events to
  `~/agent-data/runs/...`; `render_run_report()` turns a run's trace into a Markdown
  report.
- **Why it's relevant here.** This is the durable, greppable record of what an agent did
  and what it cost — the artifact you read after a run, separate from the live Jaeger view.

---

## 5. External capability services

### Tavily (web search)
- **What it is.** A search API designed for LLM/agent consumption.
- **Why it's relevant here.** The discovery step for agents that need to find sources on
  the open web (e.g. tutorial-research). Only added when an agent genuinely needs
  discovery — not by default.

### Whisper (speech-to-text)
- **What it is.** A speech-recognition model; we use it as a *local fallback* for
  transcription.
- **Why it's relevant here.** In the YouTube pipeline, captions are tried first; Whisper
  only runs when they're absent. Relevant mostly as a "graceful fallback" pattern and a
  CPU-vs-accelerator performance note.

### YouTube ingestion (the one domain-specific foundation piece)
- **What it is.** A pipeline: YouTube → transcript + screenshots → embed → Qdrant.
- **Why it's relevant here.** It's the canonical example of a *non-LLM-heavy capability
  package* and the source of much of the multimodal memory. Copy it only if you need
  YouTube ingestion; otherwise it's a structural reference.

---

## 6. Workspace, tooling & local infrastructure

### `uv` monorepo (workspace)
- **What it is.** `uv` is a fast Python package/dependency manager; we run a single-`.venv`
  workspace where packages import each other as members.
- **Why it's relevant here.** One repo holds the runtime + every agent, and agents import
  the runtime as a workspace dependency. `uv sync` sets the whole thing up.

### Python & asyncio
- **What it is.** The implementation language; `asyncio` is its concurrency model
  (`async`/`await`, `asyncio.gather`).
- **Why it's relevant here.** Agents are I/O-bound (LLM calls, DB queries, web search), so
  concurrency matters — e.g. parallel retrieval across collections via `asyncio.gather`,
  and the `BudgetTracker` as an async context manager.

### Docker & docker-compose
- **What it is.** Containerization; `docker-compose` brings up multiple services with one
  command.
- **Why it's relevant here.** Qdrant + Jaeger run as local containers via
  `infrastructure/docker-compose.yml`. It's the whole local backing infrastructure in one
  file, multi-arch (Intel and Apple Silicon).

### `.env` / configuration (`RuntimeConfig` / `get_config()`)
- **What it is.** Environment-based configuration loaded into a typed config object that
  validates keys and auto-creates the data directories on startup.
- **Why it's relevant here.** It's the single source of config for every agent — API keys,
  paths (`~/agent-data/{sources,runs,qdrant,drafts}/`). Agents call `get_config()` rather
  than reading the environment themselves.

### pytest with `--import-mode=importlib` (monorepo test isolation)
- **What it is.** A pytest import mode, plus the convention of **no `tests/__init__.py`** in
  packages.
- **Why it's relevant here.** It prevents namespace collisions when pytest collects tests
  across many packages in one workspace. A real gotcha: add an `__init__.py` to a tests
  dir and collection breaks.

---

## 7. The `agent-runtime` building blocks (what you inherit, don't rebuild)

`agent-runtime` is the shared, domain-agnostic foundation every agent imports. Knowing
its surface tells you what you should *never* re-implement.

- **`RuntimeConfig` / `get_config()`** — typed config, key validation, data-dir creation.
- **`BudgetEnvelope`** — the caps for a run (items / cost / depth / wall-time).
- **`BudgetTracker`** — async context manager that tracks spend, raises
  `BudgetExhaustedError`, auto-notifies at ~75% of any dimension. Call
  `tracker.add_llm_cost(...)` so aggregate cost is correct (gotcha: `record_llm_call`
  alone leaves cost at `$0.00`).
- **Tracing** — `@traced`, `span()`, and `record_*` helpers (`record_llm_call`,
  `record_tool_call`, `record_memory_query/write`, `record_delegation`).
- **`MemoryStore`** — the single Qdrant interaction point (chunk, embed, upsert, search,
  multimodal). Plus `EmbeddingClient` / `get_embedding_client`.
- **`UserKnowledgeStore`** — the shared `user_knowledge` collection with propose→confirm.
- **`register_agent` / `delegate`** — the delegation registry and call mechanism with
  depth-capped child budgets.
- **Reporting** — `render_run_report()` and `notify_*` (`notify_run_complete`,
  `notify_budget_threshold`) for Markdown reports and desktop notifications.

**Why it's relevant here.** If you find yourself writing budgets, tracing, Qdrant access,
embedding, delegation, or reporting from scratch, stop — it already exists. Building a new
agent should touch *none* of this except by importing it.

---

## 8. Architectural patterns & methodology concepts

These aren't libraries — they're the recurring design moves and process that make the
stack work.

### Standalone, reusable-across-apps agents
- **What it is.** Agents as app-agnostic specialists, with apps as thin workflows *over*
  them.
- **Why it's relevant here.** It's the founding principle (§1 of the blueprint). It's what
  lets two — or three — apps share the same roster instead of each rebuilding it.

### Specialize first, broaden later
- **What it is.** Ship an MVP that does the core job, then widen capability across v2/v3 as
  real use reveals gaps.
- **Why it's relevant here.** Every agent followed this (MVP → `v2-refinements-<agent>.md`).
  It's how we avoid trying to build the fully-general agent on day one.

### Cost/scarcity-driven design
- **What it is.** Finding *where the scarce/expensive/irreversible step is* and shaping the
  whole interaction loop around protecting it.
- **Why it's relevant here.** It's often the agent's central Phase-1 design question. E.g.
  Suno has no API (running a prompt is the scarce manual step → emit freely, log after);
  ElevenLabs voiceover (generation burns a character quota → direct freely, generate as a
  deliberate commitment).

### Two-budget pattern for vendor quotas
- **What it is.** Internal LLM cost lives in the `BudgetEnvelope`; a *vendor's own quota*
  (e.g. ElevenLabs characters) does not — query it from the vendor at spend time, show it
  at a soft-inform gate, record it only as a trace attribute.
- **Why it's relevant here.** Mirroring a vendor quota in your own tracker drifts and lies.
  See `voiceover-direction/chains.py`. It's the clean way to handle two different scarce
  resources at once.

### Three-phase build methodology
- **What it is.** Every new agent is built across **three discrete chat sessions** —
  Phase 1 Design (no code), Phase 2 Implementation (MVP), Phase 3 Refinement — each its own
  context window, each ending in a handoff doc.
- **Why it's relevant here.** It's *mandatory* for every cold-start agent build. It exists
  because token budgets are real and because agent work has three distinct modes that each
  want a fresh context.

### Handoff documents
- **What it is.** A document produced at the end of each phase that carries state forward —
  decisions *with reasoning*, open questions, next-phase scope — so the next chat begins
  without re-deriving the last one.
- **Why it's relevant here.** It's the load-bearing mechanism between phases (and between
  agents — a Phase 3 handoff is the next agent's Phase 1 start). See the
  `*-handoff.md` files in `docs/`.

### `v2-refinements-<agent>.md` (the deferred-ideas ledger)
- **What it is.** The durable record of "captured but not built" — ideas that didn't earn a
  build pass.
- **Why it's relevant here.** It's how we keep the MVP lean without losing good ideas.
  Every agent has one.

---

## 9. The agents themselves (concrete reference points)

The roster, as built — useful as worked examples when a concept feels abstract:

| Agent | Package | Stateful? | What it does |
|---|---|---|---|
| (foundation) | `agent-runtime` | n/a | Shared runtime every agent imports |
| Ingestion | `yt-intelligence-pipeline` | stateful (writes memory) | YouTube → transcript/screenshots → Qdrant |
| Research | `tutorial-research` | **stateless** | Discovers + synthesizes a research artifact on demand |
| Music | `music-curation` | **stateful** | Curates music; learns from user reactions |
| Voiceover | `voiceover-direction` | **stateful** | Directs + generates voiceover; manages a vendor quota |
| Scriptwriting | `concept-script` | (stateless) | Concept/script drafting (planned/early) |

**Why it's relevant here.** When you ask "what does a stateless agent look like?" the
answer is `tutorial-research`; "what does memory-with-a-feedback-loop look like?" is
`music-curation`; "what does the two-budget pattern look like?" is `voiceover-direction`.
Reach for these as living examples.

---

## 10. Suggested ways into this material

You don't have to read top-to-bottom. Some sensible first questions for the project chat:

- "What actually *is* an AI agent in this stack, versus just calling an LLM?" (§1)
- "Why Qdrant and embeddings — what problem does RAG solve for us?" (§1, §3)
- "How do we decide whether an agent needs memory?" (§1 stateful/stateless)
- "Walk me through what one agent run does, start to finish." (§7 run lifecycle)
- "Why three phases per build, and what's a handoff doc?" (§8)
- "When do we use Haiku vs Sonnet, and why?" (§1 cost routing, §2)

Bring any of these (or anything not on this list) to the project chat. The project
instructions will figure out where you're starting from and take it from there.
