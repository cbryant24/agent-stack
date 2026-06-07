---
title: Agent-Stack Blueprint
subtitle: How to design and build your own multi-agent stack
type: blueprint
audience: engineer starting a new agent-stack
status: living document
---

# Agent-Stack Blueprint

This document is a head start. It exists so you can build a working multi-agent
system **without re-deriving the process and the architecture from scratch** — both
already exist, proven, in the `agent-stack` repo cloned on your machine at
`~/Desktop/agent-stack`. Read this, then reference that repo for every concrete
detail.

You will **not** be building the same agents we did (research, music, voiceover,
scriptwriting are ours, for video production). You **will** be reusing the same
foundation, the same build process, and the same design instincts to build *your*
agents for *your* apps. This document gives you all three.

> **How to use this document.** Drop it into a new Claude **desktop** project,
> alongside the same course/reference material you already have about AI agents,
> LLMs, and MCP. Your very first chat in that project is a design conversation that
> produces **your** system-spec document — the equivalent of our
> `~/Desktop/agent-stack/docs/ai-director-agent-system.md`. A fill-in skeleton for
> that document is at the end of this blueprint. Everything before the skeleton is
> the context you and Claude need for that first chat to go well.

---

## 1. The one idea that makes this work

**Agents are standalone, domain-specialized capabilities — not features of an app.**

This is the single most important thing to internalize, and it's *more* important
for you than it was for us, because you've already told us you have **at least two
apps** in mind. If you build agents as parts of App A, you rebuild them for App B. If
you build them as standalone specialists, both apps — and the third you haven't
thought of yet — call the same agents.

Concretely, an agent in this model:

- Does **one domain** well (e.g. "research a topic into a knowledge base," "turn an
  intent into a prompt for tool X," "translate a plan into an actionable checklist").
- Is **independently invokable** — CLI command and a Python library entry point at
  minimum, MCP/other surfaces later if useful. It is never "called only from inside
  App A."
- Knows **nothing about your apps.** Apps are thin workflows *over* the agents. The
  same agents serve different apps in different sequences.
- **Specializes first, broadens later.** Ship an MVP that does the core job, then
  widen its capability across v2/v3 iterations as real use reveals what it's missing.
  Our agents all followed this — MVP → `v2-refinements-<agent>.md` → (likely) v3.
  Yours should too. Don't try to build the fully-general agent on day one; build the
  specialist and let iterations broaden it.

Everything else in this blueprint follows from this one idea.

---

## 2. The two tools and who does what

You work across **two** Claude surfaces. Keeping their jobs separate is most of the
discipline.

| Surface | Job | What happens here |
|---|---|---|
| **Claude desktop (chat, in a project)** | **Decide.** Design conversations, architecture choices, the system spec, per-agent design questions, drafting the prompts you'll hand to Claude Code, smoke-test interpretation. | No code is written *by you* here. This is where reasoning lives. |
| **Claude Code (CLI in `~/Desktop/agent-stack` or your repo)** | **Build.** Scaffolds packages, writes the implementation, runs tests, edits files. | Implementation only. Design questions that surface mid-build get answered back in chat, not improvised in code. |

The rhythm of a build is: **chat decides → chat drafts a Claude Code prompt → you
paste it into Claude Code → Claude Code builds → you smoke-test → results go back to
chat → repeat.** Chat is the architect and director; Claude Code is the
implementer. Don't let Claude Code make architecture decisions, and don't make chat
write whole packages.

Why two tools instead of one continuous Claude Code session: **token budgets are
real** and a single long session blows through them. Splitting design (chat) from
implementation (Code), and splitting the build itself into phases (below), keeps each
context window focused and affordable.

---

## 3. What you inherit for free — copy this, don't rebuild it

The repo at `~/Desktop/agent-stack` already contains a **domain-agnostic foundation**
that has nothing to do with video production. Copy it verbatim into your new
workspace and build your agents on top. Re-deriving it would be wasted effort.

### Copy these as-is

| Path in `~/Desktop/agent-stack` | What it is | Action |
|---|---|---|
| `packages/agent-runtime/` | The shared runtime: config, tracing, budgets, delegation, vector memory, reporting. **Every agent imports this.** Nothing in it is video-specific. | **Copy verbatim.** |
| `infrastructure/` | `docker-compose.yml` (Qdrant + Jaeger) + `qdrant-config.yaml`. Local vector DB + tracing. | **Copy verbatim.** |
| `pyproject.toml` (root), `.python-version`, `.env.example`, `.gitignore` | uv workspace config, pytest config (`--import-mode=importlib`), env template. | **Copy and trim** to your packages. |
| `packages/yt-intelligence-pipeline/` | YouTube → transcript/screenshots → Qdrant ingestion. This is the **one domain-specific piece** in the foundation. | **Copy only if you need ingestion** of YouTube content. Otherwise it's a reference for "how a non-LLM-heavy capability package is structured." |

> **Completed agents in the repo:** `agent-runtime`, `yt-intelligence-pipeline`,
> `tutorial-research`, `music-curation`, `voiceover-direction`. A scriptwriting agent
> is planned but not yet built. The domain-specific agents (everything except
> `agent-runtime`) are references and starting points — don't copy them unless their
> domain overlaps with yours.

### What `agent-runtime` gives you (so you know what NOT to write)

Read `~/Desktop/agent-stack/docs/ai-director-agent-system.md` under "Tech Stack / agent-runtime" for the full API.
The short version of what you get for free:

- **`RuntimeConfig` / `get_config()`** — reads `.env`, validates keys, auto-creates
  `~/agent-data/{sources,runs,qdrant,drafts}/` and the reports vault on startup.
- **Budgets** — `BudgetEnvelope` (caps on items/cost/depth/wall-time) +
  `BudgetTracker` (async context manager that tracks spend and raises
  `BudgetExhaustedError`). Every agent run is wrapped in one. Auto-fires a
  notification at 75% of any dimension.
- **Tracing** — `@traced`, `span()`, and `record_*` helpers that write JSONL traces
  to `~/agent-data/runs/...` and emit OpenTelemetry spans to Jaeger.
- **Memory** — `MemoryStore` (the single Qdrant interaction point: chunking,
  embedding via Voyage, upsert, semantic search, multimodal) and `UserKnowledgeStore`
  (runtime-owned `user_knowledge` collection with a propose→confirm workflow for
  first-party verified facts).
- **Delegation** — `register_agent` + `delegate()` so one agent can call another with
  a derived, depth-capped child budget.
- **Reporting** — `render_run_report()` turns a run's trace into a Markdown report;
  `notify_*` for desktop notifications.

You should be able to build a new agent touching **none** of this except by importing
it. If you find yourself reimplementing budgets, tracing, or Qdrant access, stop —
it's already there.

### The tech stack you're inheriting

| Layer | Tool | Notes |
|---|---|---|
| Workspace | `uv` monorepo | One `.venv` at root; packages import each other as workspace members |
| LLM | Claude API via the Anthropic SDK | Sonnet for reasoning chains, Haiku for cheap scoring/classification. Use the latest models. |
| Vector DB | Qdrant (local, Docker, 1024-dim, cosine) | |
| Embeddings | Voyage AI (`voyage-3-large` text, `voyage-multimodal-3` image+caption) | |
| Observability | OpenTelemetry + Jaeger (local, Docker) | |
| Web search | Tavily | Only if an agent needs discovery |

These are the *current* choices, not commitments. The repo's spec has a "Current
choices, open to revision" section documenting tools deliberately set aside
(LangGraph, n8n, Raspberry Pi, Google Sheets) and *when* each would earn its way in.
The principle: **use the simplest tool that does the job well.** Qdrant earns its
place for semantic retrieval; don't force it onto a problem a flat file or a
spreadsheet handles better.

---

## 4. Platform setup (Intel Mac now, Apple Silicon later)

Everything here is portable. You're on an Intel MacBook Pro now and will move to
Apple Silicon later — the architecture ports cleanly either way (local Qdrant, local
Docker, Python packages). A few Intel-specific notes:

1. **Docker Desktop** runs the same on Intel; Qdrant and Jaeger images are
   multi-arch. No change needed now or after you move to Apple Silicon.
2. **uv + Python** — install `uv`; the repo pins a Python version in `.python-version`.
   Works identically on both architectures.
3. **Local Whisper fallback** (only relevant if you copy `yt-intelligence-pipeline`)
   runs on CPU on Intel — it works, just slower than on an M-chip's accelerators.
   YouTube captions are tried first, so Whisper rarely runs. Not a blocker.
4. Nothing in the foundation depends on Apple Silicon. When you migrate, `uv sync`
   on the new machine and you're running.

**First-run setup** (mirrors `~/Desktop/agent-stack/README.md`):

```bash
# in your new workspace root
uv sync
cp .env.example .env          # then fill ANTHROPIC_API_KEY, VOYAGE_API_KEY, etc.
docker compose -f infrastructure/docker-compose.yml up -d
curl http://localhost:6333/healthz   # Qdrant up
open http://localhost:16686          # Jaeger UI
```

---

## 5. The build methodology — how an agent actually gets built

This is the process that saves you the refinement pain we went through. It is
**mandatory for every new agent build** and it is the heart of why this works.
The full version lives in `~/Desktop/agent-stack/docs/ai-director-agent-system.md`
under "Build Methodology" — read it. The essentials:

### Every new agent = three discrete chat sessions

Each phase is its own Claude desktop chat with its own scope and end condition. The
reason is twofold: token budgets (one continuous session overruns), and the natural
shape of agent work has three distinct modes that each want a fresh context window.

**A handoff document carries state between phases.** This is the load-bearing
mechanism. At the end of each phase, chat produces a handoff doc (see
`~/Desktop/agent-stack/docs/voiceover-direction-phase2-handoff.md` for a real example)
that contains everything the next phase needs to begin *without re-deriving the
previous phase's conclusions*. You start the next chat by loading that handoff.

#### Phase 1 — Design & discovery (no code)

- Opens with a **design conversation, not a build prompt.**
- Settles the agent's **central design question** first — the one gate question that
  everything else depends on (e.g. for our voiceover agent it was "where does cost
  live, and how does that shape the iterate-vs-commit loop?"). Identify yours and
  resolve it *before* touching secondary questions.
- **Scope discipline:** resist opening adjacent questions ("while we're at it…").
  Questions not needed for Phase 2 go on a "revisit later" list. A short Phase 1 that
  closes cleanly beats a long one that drifts.
- Record each decision **with its reasoning**, not just the conclusion.
- If the design reveals a **knowledge gap** the agent will need at build time (e.g.
  it depends on a third-party API you haven't ingested docs for), Phase 1 produces
  the *signal* to close it (a research prompt or a list of URLs) — but does **not**
  do the ingestion. That happens between phases.
- **Ends** with: all Phase-2-blocking questions answered, the first build session's
  scope proposed, and a Phase-2 handoff doc written.

#### Phase 2 — Implementation (build the MVP)

- Opens by **loading the Phase-1 handoff and verifying it still holds** with fresh
  eyes before any build prompt. Reconcile any drift in chat first.
- Claude Code does the implementation; chat handles design questions that surface,
  smoke verification, and drafting the Claude Code prompts.
- The bar is **MVP, not feature-complete**: the agent does its stated job, confirmed
  by a real-use smoke test. Anything that isn't MVP-blocking (performance,
  ergonomics, nice-to-haves) is **deferred to Phase 3** and written down.
- After the smoke test there's a small **"post-MVP polish"** window for
  immediate-friction items you notice on first contact (a badly-named flag, a missing
  output line). Small things only; anything larger is Phase 3.
- **Ends** with: working agent, docs updated, a Phase-3 handoff listing every
  deferred item.

#### Phase 3 — Refinement (polish, smaller-touch)

- Addresses the deferred items, scoped to non-major changes.
- Whatever doesn't earn a build pass is moved to `v2-refinements-<agent>.md` — the
  durable record of "captured but not built." This is how you avoid losing good ideas
  without bloating the MVP. (See our `docs/v2-refinements-*.md` files.)
- **Ends** with a handoff for the **next** agent. Phase 3's end is the next agent's
  Phase 1 start.

### When the three-phase pattern does NOT apply

- Small follow-up changes to an existing agent (add a flag, rename a value, fix a
  bug) → single focused session.
- Docs-only updates → single session.
- Cross-agent refactors → scope independently.

The three phases are specifically for **building a new agent from a cold start.**

---

## 6. Working-relationship rules — carry these into every chat

These are standing rules for how you (and your engineer) work with Claude across
every build chat. Paste them, or a pointer to them, into each new design session. The
full text is in `~/Desktop/agent-stack/docs/ai-director-agent-system.md` under
"Working-relationship rules." The ones that matter most:

- **Single-version-of-inputs.** Anything you'll paste, run, or act on elsewhere (a
  Claude Code prompt, a CLI command, a config value, file contents) appears **exactly
  once, in final form.** If a better version occurs while composing, use it directly —
  don't show the worse one. If it occurs after sending, send a clearly-marked
  "use this instead" follow-up before you've acted. (Explanations you only read, not
  act on, can be revised freely.)
- **No timelines or duration estimates.** Recommendations carry *order and
  dependency*, never "this takes X hours" or "after a week of use." You manage your
  own time.
- **Treat the reader as an experienced programmer.** No beginner framing. Push back
  directly when an approach is wrong rather than accommodating it.
- **Terminal-first.** Prefer CLI/scripts over GUIs unless the GUI is genuinely the
  only option.
- **Decisions with reasoning.** Every design decision is recorded with *why*, so a
  future chat (or your engineer) can re-evaluate it instead of cargo-culting it.

---

## 7. The patterns and gotchas worth inheriting

You don't need to memorize the runtime internals, but a handful of patterns recur in
**every** agent, and a few gotchas will silently break things if you don't know them.
These are the things that cost us refinement passes; inheriting them costs you
nothing.

### The anatomy of an agent package

Every agent we built has the same shape (look at
`~/Desktop/agent-stack/packages/tutorial-research/` for a clean stateless example,
`packages/voiceover-direction/` for a full stateful one (and
`packages/music-curation/` as a second stateful reference)):

```
packages/<your-agent>/
├── pyproject.toml
├── README.md
├── cli-prompts/            # optional: fill-in templates for long CLI inputs
└── src/<your_agent>/
    ├── __init__.py         # public exports (the library API)
    ├── agent.py            # run lifecycle: budget tracker → work → report
    ├── chains.py           # LLM calls, system prompts, cost-routing bridge
    ├── models.py           # Pydantic data models (inputs, outputs, memory types)
    ├── store.py            # Qdrant wrapper — ONLY if the agent is stateful
    ├── retrieval.py        # parallel context composition — ONLY if stateful
    ├── constants.py        # budgets, model ids, thresholds
    ├── cli.py              # CLI subcommands
    └── serialize.py        # ONLY if the agent reads/writes a file format
└── tests/
    ├── conftest.py
    └── test_*.py           # NO __init__.py here (see gotcha below)
```

Not every agent needs every file. A **stateless** agent (no memory) skips `store.py`
and `retrieval.py` — our `concept-script` does exactly this.

### The "does this agent need memory?" decision

This is one of the most useful heuristics we landed on. An agent earns a Qdrant
collection **only if it has a feedback loop that accumulates learning** — typically a
`report`/`reaction` signal that turns outcomes into retrievable lessons over time.

- Our music and voiceover agents are **stateful**: the user reports a reaction to each
  result, and that reaction feeds future retrieval. Memory earns its place.
- Our `tutorial-research` agent is **stateless**: it produces a research artifact on
  demand with no feedback signal to accumulate — there's nothing to remember between
  runs that improves future output. So it has no collection; outputs are files passed
  to downstream agents by reference.

Apply this to each of your agents. Don't give an agent memory by default — give it
memory when there's a signal worth remembering.

### Find where the cost/scarcity lives — it often *is* the central design question

For several agents, the central design decision came down to **where the scarce
resource is**, and the whole interaction loop was shaped around it:

- Suno (music) has no API: emitting a prompt is free, *running* it is the scarce
  manual step → the agent emits freely and logs results after the fact.
- ElevenLabs (voiceover): *direction* is free LLM iteration, *generation* burns a
  scarce character quota → "direct freely, then generate as a deliberate commitment."

When you design an agent, ask early: what's the scarce/expensive/irreversible step,
and how should the loop protect it? The answer frequently *is* your Phase-1 gate.

### Two-budget pattern for vendor quotas

Internal LLM cost goes in the `BudgetEnvelope`. A **vendor's own quota** (like
ElevenLabs characters) does *not* — query it from the vendor at spend time (the vendor
is the source of truth; a local counter drifts), show it at a "soft-inform" gate, and
record it only as a trace attribute. Don't try to mirror a vendor's quota in your
budget tracker.

### Gotchas that will silently break things

These are real bugs we hit. Inherit the fixes:

1. **Construct API clients with the key explicitly.** `pydantic-settings` loads `.env`
   into config fields but does **not** put them in `os.environ`. SDKs that read the
   environment directly (Anthropic, Voyage, Tavily) will fail to authenticate if you
   call `Client()` with no args. Always:
   ```python
   from agent_runtime.config import get_config
   from anthropic import AsyncAnthropic
   client = AsyncAnthropic(api_key=get_config().anthropic_api_key)
   ```
2. **Route LLM cost through the tracker, not just the trace helper.** Call
   `tracker.add_llm_cost(model, in_tokens, out_tokens)` (which records cost *and*
   updates consumption). Calling `record_llm_call` directly emits a trace event but
   leaves every aggregate cost reading at `$0.00`. Use the `_record_llm` bridge
   pattern (via the `_current_tracker` ContextVar) that our agents use — see
   `voiceover-direction/chains.py` (also demonstrates the two-budget pattern for
   vendor quotas).
3. **Call `check_budget()` at the TOP of each loop iteration, before doing work** —
   not after. Calling it after the last item spuriously marks a fully-successful run
   `partial`.
4. **Monorepo pytest isolation:** the root `pyproject.toml` sets
   `--import-mode=importlib` and packages have **no `tests/__init__.py`**. This
   prevents namespace collisions when pytest collects across packages. Keep it.
5. **Memory degrades silently, by design.** Retrieval composes multiple collections
   in parallel (`asyncio.gather`); each leg degrades to an empty bucket if Qdrant is
   down or a collection is absent, so an agent stays useful from a cold start with
   everything empty. Build new agents the same way.

### The run lifecycle (the spine of `agent.py`)

Every run wraps work in a `BudgetTracker`, then renders a report and notifies after
the context exits. Copy this shape:

```python
async with BudgetTracker(effective_budget, "<your-agent>") as tracker:
    run_id = tracker.run_id
    # ... the agent's actual work, reading stats from the tracker ...
except BudgetExhaustedError:
    status = "partial"

# after the context exits — trace is finalized, stats are accurate
report_path = render_run_report(run_id, "<your-agent>")
notify_run_complete("<your-agent>", run_id, status, cost_usd)
```

---

## 8. Your first Claude desktop chat — producing your system spec

Before you build any agent, you write your **system-spec document** — your equivalent
of `~/Desktop/agent-stack/docs/ai-director-agent-system.md`. This is the document that
started everything for us, and it's the document your whole stack hangs off of.

**Run this as one extensive design chat** in your Claude desktop project (with this
blueprint and your AI/LLM/MCP course material loaded as project knowledge). The goal
is to fill in as much of the skeleton (§9) as you can.

Key things to get right in that chat:

- **It's not a deep technical conversation.** The only technical depth needed is
  **feasibility and difficulty** — "is this even possible?", "how hard is this goal,
  realistically?", "does this need an API that doesn't exist?" (the way Suno having no
  public API shaped our music agent). You're deciding *what's worth building and how
  hard*, not *how to implement it*. Implementation is Claude Code's job later.
- **Design for your apps — plural — and beyond.** You have at least two apps coming.
  For each candidate agent, ask: would this serve *both* apps? Could it broaden to
  serve a third? Push toward agents that **specialize now but can broaden across
  iterations**, not agents welded to one app. The discoverability you want is "what
  standalone specialists do my apps need," not "what does App A need."
- **Surface inputs and tools you haven't thought of.** For most agents you won't know
  the full set of useful inputs up front. Treat the obvious list as a seed and let the
  chat actively propose more (our spec explicitly does this for every planned agent).
- **It's a living document.** Ours has been revised many times as real builds taught
  us things — note the dated "Runtime additions" entries in our spec. Yours will be
  too. Don't try to make it perfect or final; make it good enough to start, and
  update it as each agent build teaches you something.
- **Record decisions with reasoning**, per the working-relationship rules.

When the spec is solid enough to start, pick your first agent (favor one that's
useful standalone and doesn't depend on agents you haven't built — we built our
knowledge/research agent first because everything else could delegate to it), and open
its **Phase 1** chat.

---

## 9. Skeleton: your system-spec document

Copy everything in the fenced block below into a new file in your workspace
(`docs/<your-system>-agent-system.md`) and fill it in during your first design chat.
Bracketed `[...]` notes tell you what goes where. Delete the notes as you fill them.
This mirrors the structure of our `ai-director-agent-system.md` — read ours alongside
this for a worked example.

````markdown
---
title: [Your System Name] Agent System
date: [today]
type: system-spec
status: active
---

# [Your System Name] Agent System

[One paragraph: what this collection of standalone agents is for, and the role you
play vs. the role the agents play. Name the fact that these agents serve MULTIPLE
apps and are not tied to any one of them.]

## Design Principles

[3–6 principles that govern the whole system. Steal and adapt ours:]
- **Agents are standalone, domain-specialized, and reusable across apps.** No agent
  is "part of" a specific app. [Name your apps and assert agents serve all of them.]
- **Agents handle reasoning; the runtime handles the rest.** Agents import
  `agent-runtime`; they never reimplement budgets, tracing, memory, or reporting.
- **Specialize first, broaden later.** Each agent ships an MVP, then widens across
  v2/v3 as real use reveals gaps. [This is your iteration philosophy — state it.]
- **Budget governance from day one.** Every invocation carries a `BudgetEnvelope`.
- **Clean separation of user material vs. agent material.** [Where do agent outputs,
  knowledge bases, and source docs live, separate from your personal files?]
- **Simplest tool that does the job.** [Note tools you're deliberately NOT using yet
  and when they'd earn their way in.]

## Tech Stack

| Layer | Tool |
|---|---|
| Workspace | `agent-stack`-style uv monorepo |
| Shared runtime | `agent-runtime` (copied from ~/Desktop/agent-stack) |
| LLM | Claude API (Sonnet for reasoning, Haiku for cheap scoring) |
| Vector DB | Qdrant (local, Docker, 1024-dim, cosine) |
| Embeddings | Voyage AI |
| Observability | OpenTelemetry + Jaeger |
| [your domain tools] | [e.g. APIs your agents call — note if any lack a public API] |

[Add a "Current choices, open to revision" note for anything deferred.]

## The Apps These Agents Serve

[List the apps you're building now. For EACH, sketch the workflow over the agents —
which agents, in what order. This is what proves your agents are app-agnostic: the
same roster appears in multiple app workflows. Add "and future apps not yet defined."]

## The Agents

[For EACH agent — current roster, explicitly NOT a closed set:]

### [Agent Name] — `[package-name]`

**Status:** [planned | building | MVP complete | refined]

**Purpose:** [The one domain it owns. One or two sentences.]

**The core problem it solves:** [What pain does it remove? Be concrete.]

**Central design question (Phase 1 gate):** [The single question whose answer shapes
everything else — often "where does the cost/scarcity live?" Leave as TBD until its
Phase 1 chat if needed.]

**Inputs (seed, not final):** [Known starting inputs. Note that Phase 1 should
surface more.]

**Outputs:** [What it produces, and which other agent/app consumes it.]

**Memory model:** [Stateful with its own collection, or stateless? Apply the "is
there a learning feedback loop?" test. Justify.]

**Tools:** [Claude + which APIs + runtime memory + any delegations.]

**Broadening path (v2/v3 aspirations):** [How this specialist could widen later.]

---

[repeat per agent]

## Agent-to-Agent Delegation Map

[A simple diagram of which agents delegate to / inform which. Most agents talk to few
others. Identify any "hub" agent that many others delegate to — for us it was the
research agent.]

## What the User Handles (not an agent)

[Table of tasks that stay human: creative taste, tool limitations, rights/legal,
final approval, account ownership.]

## Scope: Rejected vs. Deferred

**Rejected (out of scope, not postponed):** [hard constraints — e.g. an API that
doesn't exist, anything you've decided not to build.]

**Deferred but open:** [things viable later if the situation changes — note the
trigger that would bring each in.]

## Knowledge / Collection Map

| Collection | Owned by | Contents |
|---|---|---|
| `user_knowledge` | `agent-runtime` (shared) | First-party verified facts, shared across agents |
| [per-agent collections] | [agent] | [memory contents] |

## Build Order

[Rough order. Favor agents that are useful standalone and don't depend on unbuilt
agents. Note which can be built in parallel.]

## Build Methodology

[Reference the three-phase pattern from AGENT-STACK-BLUEPRINT.md / our
ai-director-agent-system.md. Restate it or point to it — every new agent build
follows it.]

## Working-Relationship Rules

[Reference AGENT-STACK-BLUEPRINT.md §6. These survive into every build chat.]

## State of Connected Services

| Service | Account state | Notes |
|---|---|---|
| Anthropic | [plan] | |
| Voyage AI | [plan] | |
| [your APIs] | [plan] | |
````

---

## 10. Quick-start checklist

1. **Set up the workspace.** Clone/reference `~/Desktop/agent-stack`. Copy
   `agent-runtime/`, `infrastructure/`, and the root config files into your new repo.
   `uv sync`, fill `.env`, `docker compose up -d`, verify Qdrant + Jaeger. (§3, §4)
2. **Load context into a Claude desktop project.** This blueprint + your AI/LLM/MCP
   course material.
3. **Run the system-spec design chat.** Fill in the §9 skeleton — feasibility and
   difficulty are the only technical depth; design for multiple apps; living
   document. (§8)
4. **Pick your first agent** — standalone-useful, no unbuilt dependencies.
5. **Build it across three phases**, each its own chat, each ending in a handoff doc.
   Chat decides, Claude Code builds. MVP first; defer the rest to
   `v2-refinements-<agent>.md`. (§5)
6. **Inherit the gotchas** (§7) so you don't pay for them.
7. **Repeat per agent.** Update your system spec as each build teaches you something.

When something here is unclear or a decision needs context this document doesn't carry
— ask. You work closely with the person who built this stack; the fastest path
through a genuinely ambiguous design call is to ask them, not to guess. This blueprint
removes the *re-derivation*; it doesn't replace the conversation.
