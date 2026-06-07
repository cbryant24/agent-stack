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

**Runtime fixes (2026-05-28):** During the tutorial-research build, four bugs were fixed in the shared layer: (1) `RuntimeConfig` now expands `~` in path fields via a validator (previously broke trace persistence silently); (2) `render_run_report` raises `FileNotFoundError` on a missing trace instead of returning a bogus path; (3) `record_tool_call` now correctly increments `BudgetTracker.consumption.tool_calls`; (4) tutorial-research's partial-vs-completed status logic was made explicit (completed unless an item fails or budget is exhausted).

**Runtime additions (2026-05-29, Session 1 of music-curation arc):** (1) `UserKnowledgeStore` added to `agent-runtime` — runtime-owned wrapper for the `user_knowledge` Qdrant collection (user-authored first-party knowledge, distinct from `tutorial_research`); (2) `BudgetTracker.check_budget()` now auto-fires `notify_budget_threshold` once per dimension when usage exceeds 75% — the explicit calls were removed from tutorial-research; (3) tutorial-research retrieval now queries `user_knowledge` in parallel, applies a 1.25× score boost to those hits, and instructs Sonnet to treat them as authoritative.

**Runtime additions (2026-05-29, Session 2 of music-curation arc):** (1) `record_delegation_decision(trigger_type, collection, query, local_max_score, threshold, decision)` added to `agent_runtime.tracing` — records delegation trigger check decisions as `event_type="info"` / `event_subtype="delegation_decision"` TraceEvents for post-hoc threshold tuning. Used by music-curation's delegation trigger logic.

**Current choices, open to revision.** The stack above reflects what's been chosen for the current build, not permanent commitments. Several tools were considered and set aside for now but remain viable if the situation changes:

- **LangGraph** — not currently used because sequential LangChain reasoning has been sufficient for the agents built so far. If an agent emerges that genuinely needs stateful, branching, looping multi-step control flow (a meta-orchestrator coordinating other agents, for example), LangGraph is the right tool and should be brought in for that agent.
- **n8n** — not currently used because CLI/library/MCP invocation covers present needs. If integration-heavy workflows arise (scheduled triggers, multi-app data shuffling, visual workflows the user wants to inspect and edit), n8n is a strong fit. It may also be the natural home if agents are ported to run on a Raspberry Pi.
- **Raspberry Pi** — everything currently runs on the M1, but the user may port some or all agents to a Pi in the future, or run dedicated agents there. The architecture (local Qdrant, local Docker infra, Python packages) ports cleanly; this is a deployment decision deferred, not foreclosed.
- **Google Sheets** — not currently used because Qdrant + filesystem covers the data layer. For genuinely tabular, human-reviewable logging (generation logs, project status tracking) where Qdrant would be overkill or over-complicate things, Google Sheets is a reasonable choice and not ruled out.

The principle: use the simplest tool that does the job well. Qdrant earns its place for semantic retrieval; it does not need to be forced onto problems that are better served by a spreadsheet or a flat file. Each of these tools should be adopted when it's the better answer, not avoided on principle.

## Working-relationship rules

Standing rules for how the user works with Claude across all agent builds. These survive into every chat that builds or modifies an agent in this system.

**Single-version-of-inputs rule.** Anything the user will paste, copy, type, or act on
elsewhere appears exactly once in the chat, in its final form. Refinements, improvements,
alternate phrasings, or "actually, better:" versions of the same input do NOT appear in
the same message as the original — by the time the refinement arrives, the user may have
already acted on the first version, making the refinement either wasted or actively
disruptive.

If a better version occurs while composing: use it directly, don't show the worse one.
If a better version occurs after sending: send a separate, clearly-marked follow-up
message ("Use this instead of what I sent above:") before the user has acted.

This rule applies to: Claude Code prompts, CLI commands the user will run, edited text
for confirmation flows, message drafts, configuration values, scripts, file contents,
or anything else the user will transfer out of chat. It does NOT apply to:
explanations, reasoning, or analysis the user reads but doesn't act on — those can
be revised in-message normally.

Genuine forks where the call depends on user preference (e.g., "interactive vs.
scripted") are not refinements; presenting both with their tradeoffs is correct.
Refinements of the same recommendation are not forks and should not be presented as
options.

**No timelines, timeframes, or duration estimates.** Do not include phrases like "this should take X hours", "spend some time testing", "after a week of use", "in a few sessions", or any speculative duration or schedule. The user manages their own time. Recommendations include order and dependency, not schedule.

**Treat the user as an experienced programmer.** No beginner framing, no over-explanation of fundamentals. Push back directly when the user's stated approach is wrong rather than accommodating it.

**Terminal-first.** Prefer terminal-based solutions over GUI alternatives. CLI subcommands, scripts, and one-off Python invocations over web UIs or graphical tools, unless the GUI is genuinely the only option.

## The Agents

The agents specified below are the ones currently identified — they are not a closed set. The system is designed to grow: new agents will be added as new domains and needs emerge (image generation, thumbnail design, social media scheduling, analytics, and others not yet imagined). Each new agent follows the same pattern — standalone, runtime-backed, independently invokable — so adding one doesn't disturb the others. Treat the list as the current roster, not a ceiling.

Status reflects current state of the `agent-stack` workspace.

**A note on the "Inputs" and "Tools" listed per agent.** Except where an agent is already built, these are starting points the user can currently think of — not exhaustive or final specifications. The user is explicit that for most agents he does not yet know the full set of inputs that would serve them best, and he wants the design process to *discover* useful inputs and tools rather than lock into only the obvious ones. When building any planned agent, treat the listed inputs and tools as a seed, and actively surface additional ones (and let the agent help the user understand what's worth providing). The built agents (Tutorial Research, the YouTube pipeline) have firm input/tool sets because they exist; the planned ones do not.

### Tutorial Research Agent — `tutorial-research`

**Status: complete.** 52 tests passing.

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
- `MemoryStore.search()` for querying tutorial knowledge; `UserKnowledgeStore`-compatible query for `user_knowledge` (read-only)
- Claude (Haiku) for candidate scoring; Claude (Sonnet) for synthesis (with authoritative weighting of user-knowledge hits)

---

### Concept & Script Agent — `concept-script`

**Status: Phase 2 complete (MVP).** 33 tests passing.

**Purpose:** A structural/craft scriptwriting collaborator. It proposes craft scaffolding — section breakdown, pacing, an emotional arc, and candidate per-section emotion direction — and **surfaces, never decides** the creative core (theme, message, which references matter). The user owns every decision by editing the output. This isn't a forced workflow and it isn't a creative automator; it's a collaborator that turns decided inputs into the artifact the next agent ingests.

**The load-bearing claim (what makes it useful):** v1's output **is** the Voiceover-Direction-ready `script.md`, not an abstract brief the user adapts later. If the primary output weren't the artifact the next agent consumes, the agent would produce homework, not input. Both input modes converge on the same editable `script.md`, and `voiceover-direction direct` consumes it unchanged.

**Two input modes → one editable `script.md`:**
- **`draft` (generative)** — sparse seeds (theme/topic, mood, target duration or a musical reference implying it, stylistic references, project type) plus an optional `--ref` prior-script reference. The agent *proposes* structure.
- **`shape` (curation)** — a verbatim voice-dictation transcript. The agent *extracts* the structure latent in the stream-of-consciousness: it preserves verbatim content, strips disfluencies, keeps natural stumbles/self-corrections as content (the voiceover agent narrates them — intended), and resolves an in-band command channel where the `director note` wake phrase is the one deliberate edit signal (executed, then removed; each cut listed in a trailer).

**Output:** a single editable `script.md` — a logline, per-section script with **inline** emotion direction (literal `[tag]`s in the prose; there is no separate voice-direction field), and an optional music-hint block for Music Curation. The logline, music hint, and curation cut-trailer live in the pre-heading preamble, which the voiceover parser skips, so the same file is consumed by `direct` with nothing leaking into narration. No Obsidian note — the script file is the artifact the user edits and owns.

**Memory model — stateless v1.** The agent owns **no Qdrant collection**. The feedback loop that earns a memory collection elsewhere (a `report --reaction` signal accumulating into lessons) does not exist here, so a collection would be storage with no learning mechanism. Prior work as reference material is covered by file reference (`--ref @prior-script.md`). Reading `user_knowledge` / `tutorial_research` to fill a gap is deferred (`docs/v2-refinements-concept-script.md`).

**Tools:** Claude (Sonnet) for both the generative and curation chains. v1 stands alone on Claude plus user-provided references; Technique Research delegation and knowledge-base reads are deferred enhancements, not v1 dependencies. (The `voiceover-direction` package is a test-only dependency — the integration test imports its parser to prove the contract holds.)

---

### Music Curation Agent — `music-curation`

**Status: complete.** 214 tests passing.

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

### Voiceover Direction Agent — `voiceover-direction`

**Status: Phase 2 complete (MVP).** 145 tests passing.

**Purpose:** Same shape as Music Curation but for voice. Reference-driven, iterative, knows the user's voice library. Generates ElevenLabs-ready directed scripts with emotion direction, then spends characters on generation as a deliberate commitment.

**The central design decision (the cost inversion).** ElevenLabs *inverts* music-curation's cost structure. There, emitting the prompt was free and the scarce step was running it in Suno. Here it's reversed: **direction** (choosing text, emotion tags, voice, pacing) is LLM-only — cheap, infinitely iterable — while **generation** (the ElevenLabs TTS call) burns a scarce monthly character budget. So a turn is *direct freely until the direction is settled, then spend characters on generation as a deliberate commitment.* Iteration lives in direction, never in generation. The lifecycle is split — `generate` writes audio + a `pending` take and exits; the user listens, then `report`s a reaction.

**Inputs:** Script content as **markdown with headings** (each heading is a section), produced by a human or the planned Concept & Script Agent. Voice references and intended delivery shape the direction. The "use case" categories (narration, character voice, energetic intro) remain examples, not a fixed taxonomy — the agent's direction lessons accumulate the real distinctions over use.

**Outputs:**
- An **editable directed-script file** (`direct`) — markdown, headings preserved, audio tags (`[excited]`, `[whispers]`, etc.) inline, per-section metadata (voice, model, settings, notes) in invisible HTML-comment JSON that round-trips losslessly.
- **Generated audio files + a `take` record** (`generate`) — born `pending` until the user reacts; section-scoped lineage so re-directs compound.
- **Recorded reactions** (`report`) — `loved`/`liked`/`liked_with_changes`/`disliked`/`render_failed`, with the load-bearing `disliked` (aesthetic — weighs against the direction) vs. `render_failed` (the render missed, the direction was fine — territory stays open) distinction.
- **Direction lessons + ElevenLabs-mechanics facts** accumulated in memory for retrieval on future runs.

**Two orthogonal budgets.** The per-run Claude cost (`direct` and the `generate` re-direction fold-in) stays in `BudgetEnvelope`. The **monthly ElevenLabs character budget never enters `BudgetEnvelope`** — it is queried from the vendor at generation time (source of truth, not a local counter that drifts because the user also generates in the ElevenLabs UI), shown at a **soft-inform** gate (cost + remaining, `--yes` to skip), and recorded only as a span attribute. ElevenLabs already hard-enforces the quota, so the agent informs rather than gatekeeps.

**Fixing a bad section (option B).** There is no separate re-direct command. The user notes the problem on `report`; the next `generate` for that section folds the note into a section-scoped re-direction (a Claude call) and shows the revised markup + cost at the soft-inform gate before spending. `--raw` skips the fold-in and speaks the file's markup verbatim (the hand-edit branch).

**Tools:** Claude (Sonnet) for whole-script direction and the per-section re-direction; the runtime's memory layer (`voiceover_direction_memory` for takes + direction lessons, `user_knowledge` for `elevenlabs_mechanics` facts, `tutorial_research` for direction judgment — composed in parallel, user-knowledge score-boosted); the ElevenLabs API for `voice sync` (catalog), usage query (soft-inform), and TTS generation. Direction never triggers research inline — the cold-start knowledge gap is closed between phases via `knowledge ingest-docs` and tutorial-research, not at runtime.

**Voice library:** synced from ElevenLabs via `voice sync` (stock + cloned, with labels/description) into a local JSON registry — vendor is source of truth, no hand-entry. Voice cloning is out of scope (done in ElevenLabs; `voice sync` picks clones up once they exist). The "which voice for what" intelligence emerges from takes + direction lessons (a `lesson add` with the voice attached), not a separate annotation surface.

**Note on ElevenLabs status:** the user is currently on the free plan. The design is cost-conscious by construction — direction is free and infinitely iterable, generation is section-scoped behind a soft-inform gate, and nothing pays blind. `eleven_v3` is the expressive, audio-tag-capable default; its discrete stability *mode* (`creative`/`natural`/`robust`) is translated to the API's float at the ElevenLabs client boundary only (`creative→0.0`, `natural→0.5`, `robust→1.0`).

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
| `user_knowledge` | `agent-runtime` (`UserKnowledgeStore`) | User-authored first-party knowledge: verified facts, doc distillations, hand-written experience. Shared across all agents. Seeded with Suno-mechanics facts (music-curation seed ingestion) and ElevenLabs-mechanics facts (`domain=elevenlabs_mechanics`, via voiceover-direction's `knowledge ingest-docs` / `fact add`). |
| `tutorial_research` | Tutorial Research | YouTube tutorial chunks + screenshot+caption multimodal points across all domains |
| `music_curation_memory` | Music Curation | Generation history (prompts + reactions + chains), taste lessons, templates, sound references |
| `voiceover_direction_memory` | Voiceover Direction | Takes (section text → voice/settings/reaction, section-scoped lineage) and direction lessons. The voice library is a local JSON registry, not a vector type; ElevenLabs-mechanics facts live in `user_knowledge` (`domain=elevenlabs_mechanics`). |
| `technique_research_outputs` | Technique Research | Curated technique findings per domain |
| `project_archive` | Cross-agent | Final artifacts and decisions from completed projects (planned, low priority) |

Cross-collection reads are fine. Tutorial Research's collection is *the* tutorial knowledge base; any agent can query it.

### Runtime-owned shared knowledge layer

`user_knowledge` is special: it is owned by the runtime, not by any single agent. Any agent can read from it; only `UserKnowledgeStore` writes to it (via a propose → confirm workflow for individual entries, or `bulk_load_verified` for seed ingestion). This prevents multiple agents from independently writing conflicting facts to the same shared collection. The propose/confirm workflow makes human review practical — entries can be inspected as drafts before committing to Qdrant. Drafts live in `~/agent-data/drafts/user_knowledge/` and expire after 7 days.

## Build Order

A rough current order, subject to revision based on what the user wants to use next. This covers the agents identified so far; new agents will slot in wherever they make sense.

1. **Tutorial Research** — done (52 tests passing)
2. **Music Curation** — done (214 tests passing)
3. **Voiceover Direction** — done, Phase 2 MVP (145 tests passing). Built ahead of Concept & Script: it consumes a markdown-with-headings script, which a human can author directly, so it doesn't block on the scriptwriting agent existing yet.
4. **Concept & Script** — done, Phase 2 MVP (33 tests passing). Produces the `script.md` that Voiceover Direction consumes unchanged (and Edit Brief will consume later); the inline emotion-tag format aligns with the directed-script input contract already in place.
5. **Technique Research** — useful in parallel with the above; not blocking
6. **Edit Brief** — needs the upstream agents to produce its inputs
7. **Feedback & Iteration** — needs Edit Brief to iterate on
8. **Project Organizer** — possibly never built if Cowork covers it

Beyond these, the roster is open — image generation, thumbnail design, social scheduling, analytics, and others will be added as the need becomes concrete.

Each agent build follows the same shape: scaffold the package, design the data models, build the chains, build the invocation surface(s), integrate into the runtime, write tests, document.

## Build Methodology

Every agent build in this system is split across three discrete chat sessions, each with its own scope and end condition. This pattern exists for two reasons: (1) chat and Claude Code token budgets are real constraints that one continuous session frequently exceeds, and (2) the natural shape of agent development has three distinct modes (design, implementation, refinement) that each benefit from a fresh context window.

The phased pattern is mandatory for new agent builds. It does not apply to small follow-up changes to existing agents (e.g., the Group A reaction-vocabulary changes to music-curation), which are scoped to a single focused session.

### Phase 1: Design and discovery

**Scope.** Architecture, technology choices, memory model, workflow shape, CLI surface, and any other design questions specific to the new agent. No code is written.

The phase opens with a design conversation, not a build prompt. The user and Claude work through the central design question for the agent (which is identified in the agent's handoff doc), then secondary questions in dependency order. Each decision is recorded with its reasoning, not just its conclusion. No premature schemas.

**Scope discipline.** The central design question is the gate. Secondary questions are addressed only after the central question is settled with the user's explicit confirmation. Questions that surface during Phase 1 but are not necessary for Phase 2 to begin go on a "design questions to revisit" list — they do NOT get worked through in Phase 1. The instinct will be to keep opening adjacent design questions ("while we're at it, let's also figure out X"); resist that instinct. Phase 1 ends when the questions that must be answered for Phase 2 to make decisions are answered, not when every interesting question has been explored. A short Phase 1 that closes cleanly is better than a long Phase 1 that drifts.

If during this phase the design conversation reveals gaps in the existing knowledge bases (`tutorial_research` and `user_knowledge`) that the agent will need at build time — for example, the new agent depends on understanding a third-party API the user hasn't yet ingested docs or tutorials for — Phase 1 also produces the *signals* for closing those gaps:

- A Claude Code prompt for running `tutorial-research` against specific topics (preferred), and/or
- A list of specific URLs, domains, or documents the user should manually retrieve and ingest into `user_knowledge` via the seed/docs ingestion paths.

Phase 1 does NOT include actually gathering or ingesting that research. That happens as a between-phase activity. Phase 2 opens against a knowledge base that already has the gaps closed.

**End condition.** All design questions necessary for Phase 2 are resolved with documented reasoning, the first build session's scope is concretely proposed, all research signals (if any) have been identified, and an updated handoff document is produced that hands off to Phase 2. The handoff includes everything Phase 2 needs to begin without re-deriving Phase 1's conclusions.

### Phase 2: Implementation

**Scope.** Write the agent. The phase begins with the Phase-1 handoff loaded as context, and the knowledge gaps from Phase 1's research signals already filled by the user. Claude Code does the implementation work; chat handles design questions that surface during build, smoke verification of intermediate states, and Claude Code prompt drafting.

**Handoff verification at start.** Phase 2 opens with a deliberate verification turn before any implementation work begins. The user reads the Phase-1 handoff fresh and either confirms it still reflects their understanding, or flags any drift — things they learned during between-phase research ingestion that change Phase 1's conclusions, or anything that no longer feels right with fresh eyes. Any drift gets reconciled in the chat before any build prompt is sent. This is a short step but a load-bearing one: skipping it can mean Phase 2 commits to building against a stale design, with the staleness only surfacing mid-implementation when fixes are more expensive.

The bar for Phase 2 completion is an MVP — the agent accomplishes the tasks described in its `ai-director-agent-system.md` section, confirmed working by the user via a real-use smoke test. Not "feature-complete." Not "all v2 refinements landed." Just: it works for its stated purpose.

Issues, gaps, optimizations, and refinement opportunities will surface during Phase 2. These are evaluated against a single test:

- If the issue blocks the MVP from working at all (architecture broken, data corruption, agent literally cannot complete its stated task), fix it in Phase 2.
- If the issue is anything else — performance, ergonomics, missing-but-not-blocking features, code quality, doc cleanup — defer it to Phase 3.

The judgment call to flag explicitly: code or architecture changes that would be substantially harder to make in Phase 3 (because Phase 3 is meant to be smaller-touch) should be considered for Phase 2 inclusion even if not strictly MVP-blocking. The threshold is real but not bright-line; when uncertain, propose the inclusion to the user with reasoning.

**Post-MVP polish within Phase 2.** After the smoke test confirms the MVP working, there is typically a small set of immediate-friction items the user notices on first contact with the working agent — a confusingly-named flag, a missing display line, a default that proves wrong. These items are NOT Phase 3 work; they fall in a named "post-MVP polish" segment of Phase 2. The bar for inclusion in this segment is: noticed during the smoke test or immediately after, small enough to land in the remaining Phase 2 token budget, and would create accumulated friction if deferred. Anything larger than that, or anything not noticed in immediate post-smoke-test use, properly belongs in Phase 3. This segment exists to prevent the MVP-boundary ambiguity that otherwise forces users to choose between "extend Phase 2 indefinitely" and "live with rough edges until Phase 3."

**End condition.** The agent is working as designed, verified by user smoke testing against a real use case, with immediate post-smoke-test friction items addressed. All documentation (`README.md`, `docs/architecture.md`, `docs/ai-director-agent-system.md`, the agent's own `packages/<agent>/README.md`) updated to reflect the post-Phase-2 state. An updated handoff document produced for Phase 3, capturing all deferred items from Phase 2.

### Phase 3: Refinement

**Scope.** Address the issues, changes, improvements, optimizations, and preferences deferred from Phase 2, scoped to non-major architecture changes, cost considerations, necessity, and scope-appropriate work. Phase 3 is deliberately smaller-touch than Phase 2 — it polishes a working agent, not redesigns one.

Same pattern as Group A in the music-curation arc: focused, well-defined changes, often grouped by surface area for cohesion, each with explicit smoke verification.

**End condition.** All Phase-3-scoped items either landed or moved to `v2-refinements-<agent>.md` with documented reasoning for the defer. The `v2-refinements-<agent>.md` file is the durable record of everything captured-but-not-built; it stays current. All other documentation (agent-stack `README.md`, `docs/architecture.md`, `docs/ai-director-agent-system.md`, the agent's own README) reflects the post-Phase-3 state. A handoff document is produced for the next agent, tool, or application to be built.

### What survives between phases

Between Phase 1 and Phase 2: the updated handoff doc, any new `docs/v2-refinements-<agent>.md` skeleton, any architecture-document additions, plus the user's between-phase research ingestion.

Between Phase 2 and Phase 3: everything in the codebase plus the updated handoff with deferred-item list and all docs reflecting the post-Phase-2 state.

After Phase 3: a new handoff for the next agent, plus all documentation fully current. Phase 3's end is the next agent's Phase 1 starting point.

### When this pattern does NOT apply

- Small follow-up changes to existing agents (e.g., adding a flag, renaming a value, fixing a bug). These fit in a single focused session.
- Documentation-only updates (e.g., the post-Session housekeeping passes). Single session.
- Cross-agent refactors that touch multiple existing agents but don't constitute a new agent build. Scope these independently.

The three-phase pattern is specifically for new agent builds — the case where a new agent is being designed, implemented, and refined from a cold start.

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
