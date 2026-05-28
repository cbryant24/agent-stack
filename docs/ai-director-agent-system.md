---
title: AI Director Agent System
date: 2026-05-26
type: system-spec
project: agent-stack
status: active
tags:
  - agent-system
  - architecture
  - director-workflow
  - video-production
  - audio-production
---

# AI Director Agent System

A personal toolkit of standalone AI agents, each specialized for a domain in creative production, built on a shared runtime (`agent-stack`). The user acts as **director** — making creative decisions, approving outputs, providing taste — while agents handle research, generation, organization, and pipeline operations.

This document specifies the agent ecosystem at the system level. Implementation details for each agent live in its respective package under `packages/<agent-name>/` in the `agent-stack` workspace.

## Design Principles

**Agents are standalone, domain-specialized, and reusable across projects.** No agent is "part of" a specific deliverable like an anime mashup. The same Music Curation agent plans to serve but is not limted to anime mashups/amv's, video game reviews, and travel vlogs with more planned in the future. The same Tutorial Research agent gathers knowledge for any domain. Project-specific orchestration is its own thin layer above the agents, when and if needed.

**Agents handle reasoning, infrastructure handles the rest.** The `agent-runtime` package provides budgets, delegation, tracing, vector memory, and reporting. Individual agents focus on domain logic. This separation is enforced architecturally — agents import the runtime, never reimplement its concerns.

**Clean separation between user material and agent material.** The user's personal Obsidian vault is untouched by agents. Agent-generated reports go to `~/obsidian/agent-reports/`. Agent knowledge bases live in Qdrant. Source documents live on disk under `~/agent-data/sources/`. Agents never reach into the user's curated spaces.

**Budget governance from day one.** Every agent invocation carries a `BudgetEnvelope` with hard caps on items, cost, depth, and wall time. Delegated calls derive child budgets capped against parents. This is built into the runtime; agents inherit it for free.

**Standalone over orchestrated.** Each agent is independently invokable and individually useful. The current invocation surfaces are CLI and library entry point, with MCP server exposure planned — but the invocation layer is deliberately open. Future surfaces (Telegram or other messaging triggers, voice input, a scheduled trigger on a Raspberry Pi, a web endpoint) are all on the table where they're the better fit for how the user wants to reach a given agent. The point is that agents are standalone capabilities, not that there's only one way to call them. Composition happens when the user (or a thin orchestrator) chooses to chain them — not as a forced workflow.

## Tech Stack

| Layer | Tool |
|---|---|
| Workspace | `agent-stack` uv monorepo |
| Shared runtime | `agent-runtime` package (budgets, delegation, tracing, memory, reporting) |
| LLM | Claude API via `langchain-anthropic` (`claude-sonnet-4-6` for most chains, `claude-haiku-4-5` for cheap scoring) |
| Vector database | Qdrant (local, Docker, 1024-dim, cosine) |
| Embeddings | Voyage AI (`voyage-3-large` for text, `voyage-multimodal-3` for image+caption) |
| Observability | OpenTelemetry + Jaeger (local, Docker) |
| Web search | Tavily |
| YouTube ingestion | `yt-intelligence-pipeline` package |
| Music generation | Suno AI (manual; agent generates prompts) |
| Voiceover | ElevenLabs API |
| Video editing | DaVinci Resolve (manual; possible Tier 1 advisory agent later) |
| Knowledge base storage | Qdrant collections per domain |
| Agent-readable references | Obsidian vault `agent-reports/` (separate from user's personal vault) |
| Source documents | `~/agent-data/sources/` on disk |

**Runtime fixes (2026-05-28):** During the tutorial-research build, four bugs were fixed in the shared layer: (1) `RuntimeConfig` now expands `~` in path fields via a validator (previously broke trace persistence silently); (2) `render_run_report` raises `FileNotFoundError` on a missing trace instead of returning a bogus path; (3) `record_tool_call` now correctly increments `BudgetTracker.consumption.tool_calls`; (4) tutorial-research's partial-vs-completed status logic was made explicit (completed unless an item fails or budget is exhausted). One deferred item: `notify_budget_threshold` is still called explicitly by agents rather than auto-firing from `BudgetTracker` — fold into the runtime when a second consumer justifies it.

**Current choices, open to revision.** The stack above reflects what's been chosen for the current build, not permanent commitments. Several tools were considered and set aside for now but remain viable if the situation changes:

- **LangGraph** — not currently used because sequential LangChain reasoning has been sufficient for the agents built so far. If an agent emerges that genuinely needs stateful, branching, looping multi-step control flow (a meta-orchestrator coordinating other agents, for example), LangGraph is the right tool and should be brought in for that agent.
- **n8n** — not currently used because CLI/library/MCP invocation covers present needs. If integration-heavy workflows arise (scheduled triggers, multi-app data shuffling, visual workflows the user wants to inspect and edit), n8n is a strong fit. It may also be the natural home if agents are ported to run on a Raspberry Pi.
- **Raspberry Pi** — everything currently runs on the M1, but the user may port some or all agents to a Pi in the future, or run dedicated agents there. The architecture (local Qdrant, local Docker infra, Python packages) ports cleanly; this is a deployment decision deferred, not foreclosed.
- **Google Sheets** — not currently used because Qdrant + filesystem covers the data layer. For genuinely tabular, human-reviewable logging (generation logs, project status tracking) where Qdrant would be overkill or over-complicate things, Google Sheets is a reasonable choice and not ruled out.

The principle: use the simplest tool that does the job well. Qdrant earns its place for semantic retrieval; it does not need to be forced onto problems that are better served by a spreadsheet or a flat file. Each of these tools should be adopted when it's the better answer, not avoided on principle.

## The Agents

The agents specified below are the ones currently identified — they are not a closed set. The system is designed to grow: new agents will be added as new domains and needs emerge (image generation, thumbnail design, social media scheduling, analytics, and others not yet imagined). Each new agent follows the same pattern — standalone, runtime-backed, independently invokable — so adding one doesn't disturb the others. Treat the list as the current roster, not a ceiling.

Status reflects current state of the `agent-stack` workspace.

**A note on the "Inputs" and "Tools" listed per agent.** Except where an agent is already built, these are starting points the user can currently think of — not exhaustive or final specifications. The user is explicit that for most agents he does not yet know the full set of inputs that would serve them best, and he wants the design process to *discover* useful inputs and tools rather than lock into only the obvious ones. When building any planned agent, treat the listed inputs and tools as a seed, and actively surface additional ones (and let the agent help the user understand what's worth providing). The built agents (Tutorial Research, the YouTube pipeline) have firm input/tool sets because they exist; the planned ones do not.

### Tutorial Research Agent — `tutorial-research`

**Status: complete.** 41 tests passing.

**Purpose:** Builds domain knowledge bases for other agents to query. Given a topic, discovers relevant tutorial content, processes it through `yt-intelligence-pipeline`, and produces chunked + embedded points in the `tutorial_research` Qdrant collection. Can also delegate to itself — when another agent identifies a knowledge gap, it requests research on that gap.

**Crucial design point:** the agent's outputs are primarily for *other agents to consume*, not for the user to read. Obsidian notes are a side-effect for human inspection; the canonical output is structured Qdrant ingestion. Other agents query the resulting knowledge base via semantic search.

**Current knowledge base:** the `tutorial_research` collection holds ~564 points across ~30 videos, spanning Suno mechanics (features, tags, syntax, structure, stems, remix, v5.5), music theory (harmony/chord progressions, song structure, genre conventions, rhythm/groove, melody/hooks, mixing/mastering), and cross-cutting production. Seeded deliberately so downstream agents (Music Curation first) can delegate for both Suno-feature and music-theory knowledge from day one.

**Modes:**
- Research mode: Tavily discovery → candidate scoring → ingestion → optional synthesis
- Plan-only mode: scores candidates without processing (preview before commitment)
- Retrieve mode: pure query against existing knowledge base, no ingestion

**Invocation:**
- CLI: `uv run tutorial-research "topic"`
- Library: `from tutorial_research import research, research_sync`
- MCP exposure planned but not yet built

**Tools it uses:**
- Tavily web search for candidate discovery
- `yt-intelligence-pipeline.process_video()` for ingestion
- `MemoryStore.search()` for querying existing knowledge
- Claude (Haiku) for candidate scoring; Claude (Sonnet) for synthesis

---

### Concept & Script Agent — `concept-script` *(planned)*

**Status: not built.**

**Purpose:** Creative brief generator. Given a theme, mood, target duration, and stylistic references, produces a structured brief containing concept, pacing arc, script sections for voiceover, and creative direction for downstream agents.

The user explicitly wanted to start simple here — this isn't a forced workflow, it's a scriptwriting collaborator. Initial implementation should focus on producing a brief that the user actually wants to use as input to other agents, not on automating creative decisions.

**Inputs (starting points, not exhaustive):** theme/topic, mood descriptors, target duration (or a musical reference that implies duration), stylistic references (artists, films, prior work), project type. The actual best inputs will be discovered as the agent is built.

**Outputs:**
- A structured `VideoBrief` containing a logline, pacing/structure plan, per-section voiceover script with emotion direction, and cross-references to other agents' inputs (music style hints for Music Curation, voice direction for Voiceover Direction)
- Optional Obsidian note for human review

**Tools (starting points):** Claude for generation, the runtime's memory layer for retrieving reference material from prior projects, and possible delegation to Tutorial Research when style references involve techniques the agent doesn't know. Additional tools added as they prove useful.

---

### Music Curation Agent — `music-curation` *(under development)*

**Status: skeleton package exists, implementation pending.** Next in line for development.

**Purpose:** A music-theory expert and creative partner with persistent memory, helping craft Suno prompts grounded in real musical understanding. The agent is genuinely expert in music theory — it understands harmony, rhythm, genre conventions, instrumentation, song structure, production techniques — and uses that expertise to translate the user's intent into effective Suno prompts. Reusable across video projects, podcasts, and standalone music exploration — not anime-mashup-specific.

**The core problem this solves.** The user has created 100+ tracks with Claude's help and Suno — some he loves, some he likes, some he hates. The actual pain points were:

1. **No continuity between sessions.** Every time he picked the music work back up in a fresh Claude conversation, he started from zero. The prompts that produced music he loved weren't retained, so he couldn't reliably reproduce or iterate on a sound he'd already achieved.
2. **Inconsistent output from drifting prompts.** Without a record of exactly what prompt produced what result, new prompts couldn't match what he'd gotten before. He'd lose a good direction and be unable to get back to it.
3. **Misunderstandings about Suno itself.** Claude conversations sometimes got Suno's interface, features, and prompt syntax wrong, producing prompts that didn't work the way expected.

The agent's persistent memory and deep Suno-feature knowledge directly target all three. Memory gives continuity and reproducibility across sessions. Accurate, current Suno knowledge (kept fresh via Tutorial Research delegations) prevents the interface/feature misunderstandings.

**What the agent needs to be good at:**
- Persistent memory of the user's taste and what he's generated, across sessions, so he can iterate on directions he liked instead of restarting
- Genuine music-theory expertise to reason about *why* a sound works and how to push it in a desired direction
- Accurate, current knowledge of Suno's prompt vocabulary, tags, and features (built and refreshed via Tutorial Research)
- The ability to take references — songs, artists, films, TV scenes — and translate them into Suno prompts that target the right musical territory
- A record of prior generations linking prompt → result → the user's reaction, so good directions are reproducible

**Suno does not have a public API.** The agent generates prompts; the user runs them in Suno manually. The agent logs the chosen result and the user's reaction back for future reference and iteration.

**Inputs:** The user is candid that he doesn't yet know the full set of inputs that would help this agent most — and explicitly wants the agent (and its design) to surface inputs he hasn't thought of. The known starting points are things like stated mood or vibe, reference tracks/artists/films, and an optional brief from the Concept & Script Agent. But this list is a starting point, not a limit. Part of building this agent well is discovering what additional inputs (key/tempo preferences, structural intentions, instrumentation wishes, emotional arc, references to his own prior tracks) genuinely improve its output. The agent should help the user understand what's worth providing.

**Outputs:**
- One or more Suno prompts with style-tag breakdowns
- Music-theory reasoning explaining the choices (so the user learns and can give better direction next time)
- Cross-references to similar prior generations in memory (for iteration)
- A logged generation entry once the user reports back which prompt was used and how he felt about the result

**Tools:** The known tools are the runtime's memory layer (for persistent taste/generation memory), Claude for prompt generation and music-theory reasoning, and delegation to Tutorial Research for Suno-feature and music-theory knowledge gaps. As with inputs, this is not a closed list — the agent may benefit from tools not yet identified (a music-reference lookup, audio analysis of tracks the user points to, BPM/key detection, etc.). New tools should be added when they'd genuinely improve the agent.

**Memory model:**
- The `music_curation_memory` collection contains:
  - The user's stated taste preferences (genres, vibes, things he likes and dislikes)
  - Reference song/artist commentary (what about them resonates)
  - A prior generation log: prompt → result → the user's reaction, so liked directions are reproducible and iterable
- Memory is curated, not auto-harvested. The agent asks before storing things, or stores explicit user inputs. It does not vacuum up everything from his personal vault.

---

### Voiceover Direction Agent — `voiceover-direction` *(planned)*

**Status: not built.**

**Purpose:** Same shape as Music Curation but for voice. Reference-driven, iterative, knows the user's voice library. Generates ElevenLabs-ready scripts with emotion direction.

**Inputs:** As with Music Curation, the user doesn't yet know the full set of inputs that would serve this agent best and wants to discover them. Known starting points: script content (from Concept & Script Agent or provided directly), voice references (films, speeches, TV characters, prior voiceovers that hit the right tone), and some notion of intended delivery. But the user is explicit that he doesn't know all the useful framings — for example, the "use case" categories (narration, character voice, energetic intro, somber transition) are just examples he can think of, not a fixed taxonomy. Part of building this agent well is surfacing the inputs that genuinely shape good voice direction, including ones neither of us has named yet.

**Outputs:**
- Per-section text with emotion tags (`[excited]`, `[whispering]`, `[deadpan]`, etc.) in ElevenLabs's tag format
- Recommended voice profile (which voice in the user's library, with reasoning)
- Direction notes for delivery
- Generated audio files via ElevenLabs API once the user approves

**Tools:** Known tools are Claude for direction and tagging, the runtime's memory layer (`voiceover_direction_memory`), the ElevenLabs API for generation, and delegation to Tutorial Research for ElevenLabs feature knowledge. Not a closed list — additional tools (audio analysis of reference voices, voice-matching heuristics) may be added if they improve results.

**Note on ElevenLabs status:** the user is currently on the free plan. Cost-conscious design is appropriate — the agent should batch reasonably, support a "preview a single section before generating the rest" mode, and avoid burning credits on iterations the user could review in script form first.

---

### Technique Research Agent — `technique-research` *(planned)*

**Status: not built.** This replaces what was originally framed as "Footage Research Agent" — the user clarified he sources clips himself and doesn't need clip discovery. What he does want is technique discovery: given a video type or theme, find out what makes videos like that work.

**Purpose:** "I want to make a video like X — what techniques are involved?" The agent identifies relevant skill domains, then *delegates to Tutorial Research* to gather the actual training material. Output is a curated list of techniques + the knowledge to apply them, accumulating in the Qdrant knowledge base.

**Inputs (starting points, not exhaustive):** a video reference (description, examples, mood), and the domain (AMV, game review, travel, etc.). Other useful inputs to be discovered during the build.

**Outputs:**
- A `TechniqueReport` containing a list of techniques identified as relevant; for each, a brief description, why it matters, and where to learn more; the knowledge gaps that triggered Tutorial Research delegations; and links to the resulting tutorial-research run reports

**Tools (starting points):** Claude for technique identification and reasoning, the runtime's memory layer to check what's already known before delegating, **delegation to Tutorial Research** when knowledge gaps are identified (this agent exercises the cross-agent delegation pattern most heavily), and Tavily for high-level reference video discovery. Additional tools as they prove useful.

**Cross-agent dynamics:** Technique Research is upstream of Concept & Script Agent (informs what techniques the brief should call for) and signals downstream to Edit Brief Agent (which techniques apply to which moments of the final edit).

---

### Project Organizer Agent — `project-organizer` *(planned, possibly minimal)*

**Status: not built. May be replaced by Cowork for most use cases.**

**Purpose:** Standardized scaffolding for project working directories. Creates folder structures, renames incoming files consistently, generates project manifests, tracks what's ready vs. missing.

**Open question:** Cowork (Anthropic's file-management product) does most of this natively. The user already plans to use Cowork for project scaffolding. A custom Project Organizer agent may only be needed for the manifest/status tracking piece, or to bridge between Cowork-managed folders and the other agents' inputs/outputs.

**Decision deferred until other agents are built and the actual gap is clear.**

---

### Edit Brief Agent — `edit-brief` *(planned)*

**Status: not built.**

**Purpose:** Translates the creative artifacts (Concept & Script output, Music Curation choice, Technique Research findings, available footage) into an actionable editing checklist for the user's DaVinci Resolve session. The user does the editing; this agent prepares the briefing.

**Critical caveat:** the agent does NOT use the DaVinci API or attempt automated editing. Tier 1 only — knowledge consultant. Translates a creative plan into a "here's what to do, in order, in DaVinci" document.

**Inputs (starting points, not exhaustive):** an approved `VideoBrief`, the selected music (filename + duration + BPM if known), voiceover files (filenames + durations per section), a list of available footage (filenames + brief descriptions), and style references and technique findings. The build will likely surface more.

**Outputs:**
- Markdown editing checklist written to the agent-reports vault
- Timeline structure (rough timestamps for sections)
- Beat-sync guide (approximate cut points based on BPM)
- Transition/effect recommendations per moment
- Color grade direction (if appropriate to the project)

**Tools (starting points):** Claude for brief synthesis and the runtime's memory layer for retrieving relevant editing techniques. No external APIs in the known set — purely a reasoning + writing agent — though that could change if a useful tool emerges.

---

### Feedback & Iteration Agent — `feedback-iteration` *(planned)*

**Status: not built.**

**Purpose:** After the user produces a draft edit, this agent accepts natural-language feedback and translates it into specific actionable changes. Closes the iteration loop without requiring the user to learn precise DaVinci terminology.

**Inputs (starting points, not exhaustive):** the current `EditBrief` and version notes, and the user's natural-language feedback ("the drop feels too slow," "voiceover is competing with the music in the bridge," "the color in the third section feels off"). Other inputs to be discovered.

**Outputs:**
- Specific change recommendations with DaVinci Resolve actions
- Updated `EditBrief` reflecting the changes
- Version log entry

**Tools (starting points):** Claude for feedback interpretation, the runtime's memory layer for technique knowledge relevant to the feedback, and reads of prior versions from the agent's run history. Additional tools as useful.

## Agent-to-Agent Delegation Map

Not every agent talks to every other. The realistic delegation graph:

```
Technique Research ──delegates──> Tutorial Research
       │
       └── informs ──> Concept & Script
                              │
                              ├── informs ──> Music Curation
                              ├── informs ──> Voiceover Direction
                              └── feeds ────> Edit Brief
                                                  │
                                                  └── informs ──> Feedback & Iteration

Music Curation     ──may delegate to──> Tutorial Research (for music theory / Suno features)
Voiceover Direction ──may delegate to──> Tutorial Research (for ElevenLabs features)
Edit Brief          ──may delegate to──> Tutorial Research (for editing techniques)
```

Tutorial Research is the only agent that gets delegated to by multiple others. It is the knowledge-acquisition arm of the system.

## Director Tasks (What the User Handles)

| Task | Why the user, not an agent |
|---|---|
| Final music track selection from Suno | Creative taste |
| Sourcing and organizing anime/video footage | Rights/legality, taste |
| Actual timeline editing in DaVinci Resolve | Tool limitation; quality matters |
| Voice selection from ElevenLabs library | Creative taste |
| Final export approval | Quality control |
| Publishing to platforms | Account ownership, platform-specific judgment |
| Curating Music Curation's memory | Personal preferences are private |
| Approving Tutorial Research candidate selections (when budget-tight) | Avoiding wasted ingestion |

## Scope: Rejected vs. Deferred

Two different categories here, worth keeping distinct.

**Genuinely out of scope (rejected, not just postponed):**

- **Autonomous color grading via DaVinci API (Tier 3).** Discussed at length. Tier 1 (advisory — telling the user what to do in DaVinci) is feasible later. Tier 3 (the agent autonomously grading) is a research project with quality limitations, not a deliverable. The autonomous-execution version is rejected; the advisory version is merely not-yet-built.
- **Suno API integration.** No public API exists. The agent generates prompts; the user runs Suno manually. This is a hard external constraint, not a choice.
- **Single monolithic "video creation app."** The whole architecture is standalone agents that compose when wanted. A monolith is the thing we deliberately moved away from.

**Deferred but open (not now, but viable if the situation changes):**

- **LangGraph.** Not used yet because sequential LangChain reasoning suffices for current agents. The right tool if a future agent needs genuine stateful/branching/looping control flow (e.g., a meta-orchestrator). Bring it in for that agent if/when it appears.
- **n8n.** Not used yet because CLI/library/MCP invocation covers current needs. A strong fit if integration-heavy or scheduled workflows arise, and a natural home if agents move to a Raspberry Pi. On the table.
- **Raspberry Pi deployment.** Everything runs on the M1 today, but porting some or all agents to a Pi — or running dedicated agents there — is a real future possibility. The architecture ports cleanly. Deferred, not foreclosed.
- **Google Sheets (or similar) as a logging/data layer.** Not used yet because Qdrant + filesystem covers it. For tabular, human-reviewable data (generation logs, project status) where Qdrant would be overkill, a spreadsheet is a reasonable choice. Open.
- **Hosted/cloud deployment.** Local-first today. Not planned, but not philosophically rejected either — a future need could justify it.
- **Additional invocation surfaces.** Telegram or other messaging triggers, voice input, web endpoints, scheduled triggers — any of these are fair game as ways to reach an agent when they're the better fit. CLI and library are just what exist now.

## Project Knowledge Storage

Each agent owns one or more Qdrant collections. The structure:

| Collection | Owned by | Contents |
|---|---|---|
| `tutorial_research` | Tutorial Research | YouTube tutorial chunks + screenshot+caption multimodal points across all domains |
| `music_curation_memory` | Music Curation | User taste, reference commentary, prior generation log |
| `voiceover_direction_memory` | Voiceover Direction | User voice library notes, prior direction patterns, reference voices |
| `technique_research_outputs` | Technique Research | Curated technique findings per domain |
| `project_archive` | Cross-agent | Final artifacts and decisions from completed projects (planned, low priority) |

Cross-collection reads are fine. Tutorial Research's collection is *the* tutorial knowledge base; any agent can query it.

## Build Order

A rough current order, subject to revision based on what the user wants to use next. This covers the agents identified so far; new agents will slot in wherever they make sense.

1. **Tutorial Research** — done (41 tests passing)
2. **Music Curation** — next, has the most existing user material to work from
3. **Concept & Script** — needed before Edit Brief and Voiceover Direction make sense
4. **Voiceover Direction** — after Concept & Script (it consumes the script)
5. **Technique Research** — useful in parallel with the above; not blocking
6. **Edit Brief** — needs the upstream agents to produce its inputs
7. **Feedback & Iteration** — needs Edit Brief to iterate on
8. **Project Organizer** — possibly never built if Cowork covers it

Beyond these, the roster is open — image generation, thumbnail design, social scheduling, analytics, and others will be added as the need becomes concrete.

Each agent build follows the same shape: scaffold the package, design the data models, build the chains, build the invocation surface(s), integrate into the runtime, write tests, document.

## State of Connected Services

| Service | Account state | Notes |
|---|---|---|
| Anthropic | Paid, $25 manual reload | Cost-conscious agent design appropriate |
| Voyage AI | Payment method added; standard rate limits | 200M free tokens still apply; free-tier rate limits no longer a constraint |
| Tavily | Free tier sufficient for current scale | |
| Suno | Paid Pro account | Manual workflow; agent generates prompts only |
| ElevenLabs | Free plan | Cost-conscious VO agent design |
| Qdrant | Local Docker | No account |
| Jaeger | Local Docker | No account |

## How Projects Use These Agents

A project (anime mashup, game review intro, travel vlog) is not built into any agent. Projects are *workflows the user runs over the agents*, and they can be ad-hoc or scripted.

Example anime mashup flow (the originating use case):

1. User has a theme: "Demon Slayer + phonk + ~90 seconds + revenge mood"
2. User runs Technique Research: "what makes an effective AMV?"
3. User runs Concept & Script Agent with the theme and Technique Research output
4. User reviews and edits the brief
5. User runs Music Curation against the brief
6. User runs the Suno prompts, picks a track, logs it
7. User runs Voiceover Direction against the brief and the music track timing
8. User reviews the VO script, approves, runs ElevenLabs generation
9. User downloads anime footage (manual, legal boundary)
10. User runs Edit Brief with all the above
11. User edits in DaVinci Resolve
12. User reviews the draft, runs Feedback & Iteration if needed
13. Final export, publish

No agent forces this sequence. Each agent is independently useful. The sequence is the user's choice for this project type.

The same agents support entirely different sequences for game reviews (different brief style, different music vibe), travel vlogs (different VO direction, different pacing), or pure music exploration (just Music Curation, standalone).

This is what "standalone agents" delivers: the same infrastructure serves many creative outputs, with the user as the constant connecting them.
