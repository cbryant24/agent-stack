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

**Standalone over orchestrated.** Each agent is independently invokable and individually useful. The current invocation surfaces are CLI and library entry point, with MCP server exposure planned — but the invocation layer is deliberately open. Future surfaces (Telegram or other messaging triggers, voice input, a scheduled trigger on a Raspberry Pi, a web endpoint) are all on the table where they're the better fit for how the user wants to reach a given agent. The point is that agents are standalone capabilities, not that there's only one way to call them. Composition happens when the user — or the Orchestrator Agent acting on the user's behalf — chooses to chain them, not as a forced workflow. The Orchestrator is that composition layer made explicit: it sits above the standalone agents and invokes them as tools, without making any of them depend on it.

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
| Schema migrations | Custom runtime runner + SQLite ledger across Qdrant and relational *(planned)* |
| Agent-readable references | Obsidian vault `agent-reports/` (separate from user's personal vault) |
| Source documents | `~/agent-data/sources/` on disk |

**Runtime fixes (2026-05-28):** During the tutorial-research build, four bugs were fixed in the shared layer: (1) `RuntimeConfig` now expands `~` in path fields via a validator (previously broke trace persistence silently); (2) `render_run_report` raises `FileNotFoundError` on a missing trace instead of returning a bogus path; (3) `record_tool_call` now correctly increments `BudgetTracker.consumption.tool_calls`; (4) tutorial-research's partial-vs-completed status logic was made explicit (completed unless an item fails or budget is exhausted).

**Runtime additions (2026-05-29, Session 1 of music-curation arc):** (1) `UserKnowledgeStore` added to `agent-runtime` — runtime-owned wrapper for the `user_knowledge` Qdrant collection (user-authored first-party knowledge, distinct from `tutorial_research`); (2) `BudgetTracker.check_budget()` now auto-fires `notify_budget_threshold` once per dimension when usage exceeds 75% — the explicit calls were removed from tutorial-research; (3) tutorial-research retrieval now queries `user_knowledge` in parallel, applies a 1.25× score boost to those hits, and instructs Sonnet to treat them as authoritative.

**Runtime additions (2026-05-29, Session 2 of music-curation arc):** (1) `record_delegation_decision(trigger_type, collection, query, local_max_score, threshold, decision)` added to `agent_runtime.tracing` — records delegation trigger check decisions as `event_type="info"` / `event_subtype="delegation_decision"` TraceEvents for post-hoc threshold tuning. Used by music-curation's delegation trigger logic.

**Current choices, open to revision.** The stack above reflects what's been chosen for the current build, not permanent commitments. Several tools were considered and set aside for now but remain viable if the situation changes:

- **LangGraph** — now in use by exactly one built agent: the **Orchestrator Agent** (first slice shipped), the meta-orchestrator coordinating the others, which genuinely needs stateful, branching, looping control flow and a conversation checkpointer. The other five agents remain on plain sequential LangChain, which is sufficient for them. LangGraph was the chosen tool for the orchestrator over the Claude Agent SDK (see the Orchestrator Agent section).
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

The agents specified below are the ones currently identified — they are not a closed set. The system is designed to grow: new agents will be added as new domains and needs emerge. Image generation, once an anticipated future agent, is now specified below as the Visual Generation Agent; others (thumbnail design, social media scheduling, analytics, and more not yet imagined) remain on the open roster. Each new agent follows the same pattern — standalone, runtime-backed, independently invokable — so adding one doesn't disturb the others. Treat the list as the current roster, not a ceiling.

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

**Status: Phase 2 complete (MVP).** 45 tests passing.

**Purpose:** A structural/craft scriptwriting collaborator. It proposes craft scaffolding — section breakdown, pacing, an emotional arc, and candidate per-section emotion direction — and **surfaces, never decides** the creative core (theme, message, which references matter). The user owns every decision by editing the output. This isn't a forced workflow and it isn't a creative automator; it's a collaborator that turns decided inputs into the artifact the next agent ingests.

**The load-bearing claim (what makes it useful):** v1's output **is** the Voiceover-Direction-ready `script.md`, not an abstract brief the user adapts later. If the primary output weren't the artifact the next agent consumes, the agent would produce homework, not input. Both input modes converge on the same editable `script.md`, and `voiceover-direction direct` consumes it unchanged.

**Two input modes → one editable `script.md`:**
- **`draft` (generative)** — sparse seeds (theme/topic, mood, target duration or a musical reference implying it, stylistic references, project type) plus an optional `--ref` prior-script reference. The agent *proposes* structure.
- **`shape` (curation)** — a verbatim voice-dictation transcript. The agent *extracts* the structure latent in the stream-of-consciousness across four distinct categories: it strips disfluencies; **preserves natural stumbles/self-corrections verbatim as content by default** (the voiceover agent narrates them — the point of the agent; `--clean` opts into resolving them into final prose instead, and is the only category that flag affects); executes and removes the `director note` wake phrase (the one deliberate edit signal — a single deletion, a global/repeated change, a replacement, or a reorder), recording each executed note in a cut trailer; and applies sectioning + inline emotion direction.

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

### Visual Generation Agent — `visual-generation`

**Status: Phase 2 complete (MVP).** 152 tests passing.

**Purpose:** A diffusion image/video generation collaborator. Like Music Curation and Voiceover Direction, it is a standalone, domain-agnostic capability that projects compose — it bakes in no single project. It fills three intertwined roles. **Prompt-craft** — translate creative intent into effective prompts and settings for the chosen models. **Platform tutor** — explain platform setup and every relevant setting in plain, step-by-step terms: what CFG, steps, sampler, the WAN 2.2 high-noise/low-noise split, shift, and LoRA strength actually do, and what to do next on the platform. **Generation + iteration** — drive the generation backend through its API, capture results, and iterate and curate toward the target. The tutor role is a genuine agent responsibility, not a side note: the director is an experienced programmer but a novice in *this* domain who learns by doing, not by reading concepts — which is exactly why generic ComfyUI/Udemy tutorials did not work for him.

**Why it fits the system.** Same pattern as Music Curation (`music-curation`) and Voiceover Direction (`voiceover-direction`): a domain-specialized standalone agent that projects consume without being coupled to any of them. Two projects already consume it — the anime/AMV creative pipeline (character imagery, thumbnails) and a separate adult-content contractor engagement (`wardrobe-poc`: clothed wardrobe and scene variation on a consenting subject) — and it bakes in neither.

**Platform (confirmed in Phase 1).** **RunPod** for pay-per-hour GPU, chosen because its content policy is permissive for legal adult content and it isolates cleanly from personal identity (Google Colab was ruled out — its content/identity policy is hostile to this use case regardless of paid tier). Confirmed **pod, not serverless** (serverless wraps the native endpoints and cold-starts each request — wrong for a warm session and the tutor role). **ComfyUI** as the generation backend, driven via its native pod API (`/prompt` → `/history` → `/view`, `/object_info`) rather than manual node clicks — the same orchestration pattern the other agents use against their backends; v1 **consumes** API-format graphs the user builds (graph authoring deferred). Pod lifecycle is **Tier-1 advisory** in v1 — the agent holds **no RunPod API key**, talks only to the user-supplied ComfyUI `--endpoint`, and prompts to stop on drain (real stop-automation is Tier-2, deferred). Models: **Flux.1 dev** for stills (v1 is stills-first); **WAN 2.2** (T2V / I2V / VACE) for video as a fast-follow on the same path; **SDXL** checkpoints where relevant; **character LoRAs** (trained via ai-toolkit, training itself deferred) for identity lock.

**The central design decision (the cost inversion).** Visual Generation shares Voiceover Direction's cost structure, more extreme. **Prompt-craft and direction are free, infinitely iterable LLM loops.** The scarce, costly steps are **GPU compute** (RunPod per-hour pod uptime) and **generation runs** (minutes of GPU per image, far more per video clip). So the agent treats a generation run as a *deliberate, budgeted commitment* and surfaces cost before spending; pod start/stop discipline is part of what it tracks and advises on. Two budget axes mirror voiceover-direction: per-run **Claude** cost stays in `BudgetEnvelope`; **GPU/pod** spend is tracked and advised but is a separate axis from the Claude budget.

**Inputs (starting points, not exhaustive):** creative intent (subject, style, mood, references); reference images (for IP-Adapter, img2img, or an I2V seed frame); a character LoRA or the intent to train one; target output (still vs. short video, resolution, count); and an optional brief from Concept & Script or Technique Research. As with the other agents, part of building it well is surfacing inputs the director hasn't thought of.

**Outputs:**
- Effective prompts plus a full **settings recipe** (model, sampler, steps, CFG, shift, LoRA stack and strengths, ControlNet / IP-Adapter config), each choice explained in plain language so the director learns as he goes
- **Generated assets** via the ComfyUI API
- A **generation record** (prompt + settings + workflow → result → director reaction) for reproducibility and iteration — the same prompt→result→reaction pattern Music Curation uses
- **Step-by-step platform guidance** when the director operates the platform directly
- **Iteration recommendations** — what to change to move output toward the target

**Memory model.** Owns a `visual_generation_memory` Qdrant collection with three memory types (discriminated by `memory_type`): **`generation`** — the core record (prompt + full settings + model/LoRA stack + workflow → result → reaction + chain lineage), embedded from the **image/keyframe + caption** via `voyage-multimodal-3`; **`technique_lesson`** — settings/technique lessons learned by doing (`scope` ∈ prompt/settings/workflow/model, valence, confirmed); **`workflow_template`** — a reusable parameterized ComfyUI graph plus its **slot map** (semantic param → node input) and required models. Curated, not auto-harvested — the music-curation discipline. The model/LoRA **registry** is a *local JSON file*, not a vector type (the voice-registry analog: looked up by name, never searched), carrying the `identity_bearing` flag. Platform-mechanics facts (ComfyUI, RunPod, Flux, WAN settings) live in the shared `user_knowledge` collection under `comfyui_mechanics` and `runpod_mechanics`, seeded from the Stable Diffusion / ComfyUI / WAN / Veo course documents (via the shared `knowledge ingest-docs` mechanism) and refreshed via Tutorial Research — the same pattern voiceover-direction uses for `elevenlabs_mechanics`. This is the first agent whose own generation memory leans on the `voyage-multimodal-3` image+caption embedding, since its outputs are images.

**Tools:** Claude (Sonnet) for prompt-craft, settings reasoning, and plain-language tutoring; the ComfyUI API (`/prompt` → `/history` → `/view`, `/object_info`) for generation and registry sync; the runtime memory layer (`visual_generation_memory`, plus `user_knowledge` ComfyUI/RunPod facts and `tutorial_research`, composed in parallel with the user-knowledge score boost — the voiceover-direction retrieval pattern); delegation to Tutorial Research for ComfyUI / Flux / WAN / LoRA technique gaps (the explicit `research` command, a Claude-only child budget). No RunPod API in v1 — pod lifecycle is Tier-1 advisory (above). The Stable Diffusion / ComfyUI / WAN / Veo course documents in the user's course project are a `user_knowledge` ingestion source.

**Scope note.** The agent is content-agnostic at the platform layer: the chosen platform permits legal adult content, which the agent supports where that is the project (the `wardrobe-poc` engagement — clothed wardrobe and scene variation on a consenting subject, the subject being the user himself). It carries the hard line established in that work: clothing/scene variation and creative generation only — nude generation or clothed-to-unclothed transformation of real people is out of scope and is not a capability the agent builds. Operational security for sensitive artifacts (character LoRAs encode identity and preserve it through any prompted transformation) lives at the storage/access layer, not the model layer.

**Cross-agent dynamics:** Concept & Script and Technique Research can inform *what* to generate (style, technique); the agent delegates to Tutorial Research for technique/settings knowledge gaps; and it feeds generated stills/clips downstream to Edit Brief as available assets (footage sourcing is otherwise director-handled).

**Realized command surface (the built turn):**
```bash
visual-generation draft "<intent>" [-o batch.md] [--template <name>]                      # free Claude prompt-craft → batch file
visual-generation generate <batch.md> (--section <id> | --all) --endpoint <url> [--max-session-cost N] [-y]  # warm-session GPU spend, soft-inform gate
visual-generation report <gen_id> --reaction <loved|liked|liked_with_changes|disliked|render_failed> [--rating 1-5]
visual-generation model sync --endpoint <url>;  visual-generation model list             # registry from /object_info
visual-generation workflow register <exported-api.json>;  visual-generation workflow list # slot-map propose→confirm
visual-generation review-pending;  visual-generation recall "<query>";  visual-generation chain show <root_id>
visual-generation lesson add "<statement>" --scope ... --valence ...;  visual-generation fact add "<statement>" --domain ...
visual-generation explain "<concept>" [--level full|concise|quiet];  visual-generation research "<topic>"
```

**Deferred (the path is built to accept them):** video/WAN (a fast-follow on the same turn shape) · LoRA training (ai-toolkit) · RunPod stop-automation (Tier-2) · encryption-at-rest for identity artifacts · the `reference` memory type · the shared `ingest-docs` `--decisions`/`--url` refinements · graph authoring.

---

### Technique Research Agent — `technique-research`

**Status: Phase 2 MVP complete (40 tests passing); smoke-verified on a real goal.** The full Mode A turn works end to end — ground → identify → check → gate → delegate → curate → outputs; `recall` retrieves findings; the orchestrator wraps it. Deferred items live in `docs/v2-refinements-technique-research.md`; Phase 1 design rationale in `docs/technique-research-phase1-handoff.md`. This replaces what was originally framed as "Footage Research Agent" — the user clarified he sources clips himself and doesn't need clip discovery. What he does want is technique discovery: given a video type or theme, find out what makes videos like that work.

**Purpose:** "I want to make a video like X — what techniques are involved?" The agent identifies relevant skill domains, then *delegates to Tutorial Research* to gather the actual material. Output is a curated `TechniqueReport` plus per-technique findings accumulating in `technique_research_outputs`.

**The central design decision (the anti-redundancy boundary).** Tutorial-research already discovers, ingests, and synthesizes — so technique-research owns only what the delegate doesn't: **(a)** the identification layer ("goal → prioritized technique domains" — tutorial-research takes a topic as given; this agent decides which topics matter); **(b)** the control flow *identify → check existing knowledge → delegate gaps → curate* (the check step makes run N+1 cheaper than run N); **(c)** the curated layer — *relevance decisions, not material*. No tutorial discovery, no ingestion, no yt-pipeline calls in this agent, ever. Both agents use Tavily, for different purposes: tutorial-research searches for tutorials to ingest; technique-research searches only to *understand the reference* (what "videos like X" are).

**Two modes.** **Mode A (reference-based) is v1:** Claude reasoning (vision-capable) + conditional Tavily reference grounding, with optional reference image(s) (the technique may just be a look) and an optional video URL (yt-dlp metadata/description as context only — no frame extraction). **Mode B (footage-based diagnosis) is V2, parked:** a YouTube URL + start/stop timestamps or a local video file → ffmpeg interval frames → multi-frame Claude-vision technique diagnosis → search/match on the diagnosis. The one v1 provision: the identification chain's input model is "text + zero-or-more images + optional context" from the start, so Mode B becomes more frames into the same chain plus an extraction front-end — an extension, not a redesign.

**Inputs (v1):** the creative goal (required); optional domain (AMV, game review, travel — inferable), reference image(s), reference video URL, `--ref` to a prior TechniqueReport, and a scope hint (`editing | generation | both` — inferred by default; generation scope targets ComfyUI/Flux/WAN/LoRA territory). The director's toolset is read automatically from `user_knowledge` (`domain=editing_toolset`), not supplied per run.

**Outputs:**
- A **TechniqueReport** — an editable markdown file the director owns (`-o` path): the goal and grounded reference summary; prioritized techniques, each with description, why-it-matters for this goal, how-to-apply grounded in gathered material and the director's toolset (with a paid/Studio upgrade flag where relevant), and where-to-learn-more links to tutorial-research run reports; the gaps that triggered delegations; consumer-directed sections per scope
- **Per-technique findings** in `technique_research_outputs` — the canonical accumulating layer (text-embedded, `voyage-3-large`; the agent's own check step is the retrieval consumer that earns the collection)
- The standard run report to the agent-reports vault

**The gate.** Identification is cheap; delegations are the spend. After identification the director sees the technique list + delegation plan with estimated cost and prunes per-domain (interactive by default, `-y` to skip, `--plan-only` to stop at the gate with no writes). Declining all delegations isn't an abort — the run curates from existing knowledge only.

**Tools:** Claude (Sonnet, vision-capable) for grounding and identification; conditional Tavily for reference discovery; yt-dlp for URL metadata; the runtime memory layer (check across `technique_research_outputs`, `tutorial_research`, `user_knowledge`, thresholds recorded via `record_delegation_decision`); **delegation to Tutorial Research** on child budgets (this agent exercises the cross-agent delegation pattern most heavily). Default budget (unvalidated): `max_items=5, max_depth=1, max_cost_usd=5.00, max_wall_time_sec=2700`.

**Cross-agent dynamics — two consumption channels, both already wired.** *Knowledge channel (automatic):* delegated gathering lands in `tutorial_research`, which visual-generation's retrieval already queries on every `draft`/`explain`/`recall` — so generation-technique research makes visual-generation smarter with zero integration work. *Artifact channel (director-mediated):* the report feeds concept-script as seed material (`draft --seeds` accepts arbitrary markdown — no new contract) and gives the director the intent language for `visual-generation draft`; Edit Brief (unbuilt) gets no designed contract. The Orchestrator wraps `technique_recall` (free) and `technique_identify` (full run, child-budgeted — the `research_tutorials` precedent) and gains `technique_research_outputs` as a `search_knowledge` domain.

---

### Orchestrator Agent — `orchestrator`

**Status: Phase 2 first build slice + Phase 3 sub-agent surface + diagnose-only vector-DB diagnostics shipped.** 42 tests passing. Supersedes the previously-planned "Project Organizer Agent." That agent was scoped to file scaffolding and manifest/status tracking, and was flagged as largely redundant with Cowork — which the user does plan to use for project scaffolding. The remaining file-organization gap is small and stays with Cowork; what the user actually wants in this slot is a different kind of agent, specified below.

**What shipped (first slice).** A hand-rolled ReAct LangGraph loop on Sonnet (`MODEL_ORCHESTRATOR`, defined in `orchestrator/constants.py`): an `agent` node (`bind_tools`) + a custom `tools` node wrapping `ToolNode`, with a conditional edge that loops on tool calls and ends otherwise. A per-turn `BudgetEnvelope` guard runs before each tool step and short-circuits to a partial answer when exhausted (plus `record_tool_call` / `record_delegation_decision` tracing). A thread-keyed `AsyncSqliteSaver` checkpointer at `~/agent-data/agent-stack.db` (the library managing its own tables via `.setup()`) makes conversations resumable. The v1 tool set: `search_knowledge(query, domain)` over a domain registry (`tutorial_research`, `music_curation_memory`, `langgraph_mechanics`) — one embedding space per call, with the 1.25× `user_knowledge` boost + cap and graceful degradation, generalized from `tutorial-research/retrieval.py`; `read_file` + `grep` scoped to the repo (these also serve system-introspection); and four in-process sub-agent tools — `tutorial_retrieve` / `research_tutorials` and `music_recall` / `music_generate` — with derived child budgets. The surface is an `orchestrator chat [--thread <id>]` REPL with a soft per-session cost tally. Implementation detail lives in `packages/orchestrator/README.md` and `docs/architecture.md`.

**Still deferred (not yet built).** MCP (both wrapping agents and exposing the orchestrator); additional surfaces (Telegram / voice / web / scheduled); Haiku utility (tool-output compression, long-thread summarization); the per-session hard ceiling (v1 is a soft tally only); and the schema-migration runner/ledger. **Vector-DB diagnostics shipped diagnose-only** (read-only inspection + behavioral probe + a report to `~/obsidian/agent-reports/diagnostics/`, status `open → delegated → fixed`); the **remediation delegation seam** (a `RemediationHandler` protocol + registry + the report hand-off) is built but ships with an empty registry — **per-agent remediation entry points** (the owning-agent write paths) are deferred to `docs/v2-refinements-orchestrator.md`, so until an agent registers a handler each report is a manual work order. (The other three agents — `voiceover-direction`, `concept-script`, `visual-generation` — are now wrapped as tools alongside tutorial-research and music-curation; only their FREE / non-side-effecting ops are exposed, so the autonomous loop can never trigger paid generation.)

**Purpose:** A single conversational meta-agent that is an expert in *this* system. It knows what every agent does, answers questions about the system, retrieves from the shared knowledge bases, reads the live codebase and docs, remembers the conversation across sessions, and can invoke the other agents as tools. It is the "director's console" — one place to talk to the whole system rather than invoking each agent's CLI separately. New capabilities are added by registering a tool or wrapping a sub-agent, not by rewriting the orchestrator.

**Central design question (Phase 1):** what is the orchestration control-flow graph, and where does each kind of state live? The agent must keep two memories strictly separate — conflating them is the most common way to build this wrong:

- **Conversation memory (continuity)** — the running thread, so the agent knows what was said earlier and across sessions. This is a LangGraph checkpointer keyed by thread ID (SQLite locally; Postgres only if it ever needs sharing), **not** the vector DB. Embedding raw chat turns for continuity yields fuzzy semantic recall instead of accurate turn-by-turn history.
- **Long-term knowledge (semantic recall)** — the system's facts, docs, and distilled experience. This is the existing Qdrant layer, queried across the namespaced per-domain collections.

**Technology — LangGraph (chosen over the Claude Agent SDK).** This is the agent the rest of this spec anticipated when it said "bring in LangGraph if a genuine meta-orchestrator appears." The Claude Agent SDK was evaluated as the alternative — it ships session persistence, live file access, and MCP support out of the box, and would hand those three hard parts over for free. LangGraph is chosen deliberately anyway: the user wants explicit control over the orchestration graph (nodes, branching, looping, tool routing, checkpointer wiring) and provider portability, rather than an opinionated built-in loop. The accepted cost is that the code-access tools, checkpointer wiring, and retrieval plumbing are built here instead of inherited. This is consistent with the rest of the stack, which already reasons through `langchain-anthropic`.

**The layers it needs:**

- **Orchestration loop** — a LangGraph graph that reasons, retrieves, routes to tools, and loops. Carries a runtime `BudgetEnvelope` like every other agent; delegated calls derive child budgets against the parent (the existing delegation pattern). Its model slot is `MODEL_ORCHESTRATOR` (= `claude-sonnet-4-6`), defined in the orchestrator package (`orchestrator/constants.py`) per the per-package convention — not in `agent-runtime`.
- **Conversation store** — LangGraph checkpointer (SQLite locally), one thread per conversation, resumable across sessions.
- **Knowledge retrieval** — cross-collection reads over the existing Qdrant collections (`user_knowledge`, `tutorial_research`, each agent's `*_memory`, `technique_research_outputs`, `project_archive`), scoped per query by collection/metadata so domains don't blur. No new collection required; the orchestrator is a reader, not an owner.
- **Live codebase + docs access** — read + grep over the `agent-stack` packages and `docs/`, the way Claude Code itself works. The codebase is actively developed, so it is read live, never summarized-and-embedded — embedding code answers from stale snapshots and forces re-indexing on every change. Only stable prose (architecture docs, READMEs, design notes) is worth embedding, and that already lives in the knowledge layer where appropriate.
- **Capabilities as tools** — each existing agent is exposed to the orchestrator as a tool, via its library API now and its planned MCP server later. "Add a capability" = register a tool or wrap an agent, not rewrite the orchestrator. This is the extensibility seam.

**Inputs (starting points, not exhaustive):** a natural-language message from the user; the conversation thread ID (for continuity); and, implicitly, read access to the codebase, docs, and Qdrant collections. More to be discovered during the build.

**Outputs:**
- Conversational responses grounded in the system's knowledge and code
- Tool/agent invocations (delegated runs of the other agents) and their results
- Persisted, resumable conversation threads
- Diagnostic reports to `~/obsidian/agent-reports/diagnostics/` (see "Vector-DB diagnostics" below)
- Optionally, run reports to the agent-reports vault for substantive sessions

**Tools (starting points):** Claude (via `langchain-anthropic`) for reasoning; the runtime memory layer for cross-collection retrieval; a read-only Qdrant inspection tool (collection metadata, counts, payload sampling — wrapping the `AsyncQdrantClient` primitives the runtime's `MemoryStore` already holds) for diagnostics; filesystem read + grep tools for live code/doc access; and each agent (Tutorial Research, Music Curation, Voiceover Direction, Concept & Script, Visual Generation, and others as built) exposed as an invokable tool. Additional tools as they prove useful — the set is meant to grow.

**Cross-agent dynamics:** the Orchestrator sits *above* every other agent. Where Tutorial Research is the agent delegated *to* by many, the Orchestrator is the one agent that can delegate to *any* other. It does not replace direct CLI/library invocation of individual agents — those stay independently useful — it adds a conversational layer over the whole system for when the user wants to reach the system as a whole rather than one agent at a time.

**Vector-DB diagnostics (diagnose-only) — shipped (diagnose-only); remediation entry points deferred.** Built per the design below: read-only Qdrant inspection (`MemoryStore.get_collection_info` / `count_points` / `sample_points`), live code access (the existing `read_file` / `grep` tools), and a behavioral probe (`orchestrator/diagnostics.py`) surfaced as the `inspect_collection`, `probe_collection`, and `write_diagnostic_report` tools; reports land in `~/obsidian/agent-reports/diagnostics/`. The remediation delegation **seam** (`RemediationHandler` protocol + registry + `delegate_remediation`, status `open → delegated → fixed`) is built but the registry is empty — per-agent remediation entry points are deferred (`docs/v2-refinements-orchestrator.md`), so each report currently doubles as a manual work order. The Orchestrator can audit the Qdrant layer but never writes to it — it is a reader, not an owner, the same rule that governs its knowledge retrieval. Diagnosis combines three things it already has: the read-only Qdrant inspection tool (collection metadata, counts, payload sampling via `scroll`/`count`/`get_collection`); live code access (an agent's target collection, metadata filters, score threshold, and embedding model, read from source); and — where a structural read can't decide — a behavioral probe (embed a query that *should* hit and check whether the expected point returns above threshold). The probe is the only way to catch a cross-model embedding-space mismatch, since `voyage-3-large` and `voyage-multimodal-3` vectors are both 1024-dim and structurally valid but semantically incompatible, so the data is present yet never retrieves.

When it finds an issue it does two things and then stops: (1) it writes a **diagnostic report** to `~/obsidian/agent-reports/diagnostics/` — a markdown file with frontmatter naming the affected collection, the owning agent, the symptom, the root-cause diagnosis, the supporting evidence (filter/threshold/model read from code, plus the actual payloads/scores found in Qdrant), and a proposed fix, with a `status` field that moves `open → delegated → fixed`; and (2) it **delegates the fix to the owning agent**, invoking that agent's remediation path as a tool and handing it the report. The owning agent performs the actual write — re-embed, re-tag payload, move points — under its existing ownership, which preserves the rule that only an owner writes to its own collection (and only `UserKnowledgeStore` writes to `user_knowledge`, via propose→confirm). The Orchestrator diagnoses and documents; it does not fix.

**Dependency this surfaces:** delegating the fix assumes each owning agent exposes a remediation/maintenance entry point. Most agents don't have one yet — so until they do, the diagnostic report doubles as a human- or Claude-Code-actionable work order the user runs manually, and building per-agent remediation surfaces becomes a follow-up that this capability will drive out as it's used.

---

### Edit Brief Agent — `edit-brief` *(built)*

**Status: Phase 2 MVP-complete — `draft` runs end-to-end (three-layer brief + missing-input notations), the time engine is fully unit-tested, and the orchestrator wraps both ops.** Package suite green (50 passed); orchestrator integration adds 3 tool tests (44 passed, 1 skipped). Both edit-brief smoke runs recorded (degradation on `script-draft.md`; a synthetic VO-backed fixture) plus an orchestrator-path smoke (`edit_brief_discover` free + `edit_brief_draft` child-budgeted, $0.0884, brief written). Full reasoning in `docs/edit-brief-phase1-handoff.md`; Phase 2 record in `docs/edit-brief-phase2-handoff.md`; deferred items in `docs/v2-refinements-edit-brief.md`.

**Purpose:** Translates the creative artifacts (the approved `script.md`, the selected music, voiceover takes, available footage and generated assets, technique findings) into a director-owned, **time-ordered execution checklist** for the director's DaVinci Resolve free session. The director does the editing; this agent prepares the briefing. Its one distinct competence is **assembly and time-translation** — section timestamps from VO durations, beat-aligned cut points from BPM, retrieved findings placed against the computed grids. All knowledge is retrieved, never gathered; gaps are flagged naming the upstream agent.

**Critical caveat:** the agent does NOT use the DaVinci API or attempt automated editing. Tier 1 only — knowledge consultant. Translates a creative plan into a "here's what to do, in order, in DaVinci" document.

**Inputs (resolved):** the script (`script.md`), positional and the only required input; everything else is **discovered from existing collections by `project_id`** (default: script stem) with flags as overrides — VO takes from voiceover-direction's records (durations ffprobe-read from disk; positively-reacted take wins, else latest), music + BPM from `music_curation_memory` (`--music` override), generated assets from visual-generation's records (generation intent gives rich section mapping). Director-sourced footage is the one input with no record: `--footage DIR`, scanned and ffprobed, descriptions as optional enrichment. Technique findings are retrieved, never passed. Partial input degrades the corresponding layer with an explicit missing-input notation — never a failure, never a silent guess.

**Outputs:**
- Director-owned `edit-brief.md` written next to the script (supersedes the earlier vault-checklist plan; the vault gets only the standard run report). Frontmatter: `project_id`, `version`, discovered-input provenance; section anchors stable from the script's H1s for Feedback & Iteration.
- Three layers: timeline skeleton (computed section timestamps), beat grid (computed from BPM — arithmetic, never LLM-estimated), per-section ordered checkbox steps executable in Resolve free, grounded in retrieved findings with toolset fit and upgrade flags verbatim.
- **Decide vs. surface:** decides time arithmetic, work ordering, finding-to-moment application, asset-to-section mapping; surfaces creative footage selection (ranked candidates) and VO-grid/music-structure reconciliation (nearest-beat proposals).

**Memory:** stateless (passes the concept-script test); reads `user_knowledge` every run — stated director preferences land there via propose→confirm. Learning-from-feedback belongs to Feedback & Iteration.

**Tools:** Claude for brief synthesis; the runtime memory layer composing `technique_research_outputs`, `tutorial_research`, and `user_knowledge` (`editing_toolset` always loaded); ffprobe for durations. Read-only over knowledge in v1 — no delegation. No external APIs.

**CLI:** `edit-brief draft SCRIPT.md [--footage DIR] [--music FILE] [--gap SECONDS] [-o brief.md] [--project-id ID] [--max-cost N] [--dry-run]` — `--dry-run` is the free discovery-only preview of found/missing inputs; the orchestrator wraps `draft` child-budgeted and the discovery as the free op.

---

### Feedback & Iteration Agent — `feedback-iteration` *(built — Phase 2 complete)*

**Status: built — Phase 2 (Build to MVP) complete; the `revise` turn runs end to end and the orchestrator wraps both ops.** Design rationale in `docs/feedback-iteration-phase1-handoff.md`; build record + verification in `docs/feedback-iteration-phase2-handoff.md`.

**Purpose:** After the director produces a draft edit, accepts natural-language feedback and translates it into specific actionable changes — closing the iteration loop without requiring the director to learn precise DaVinci terminology. **Revision is the spine; learning hangs off it:** feedback → moment mapping → diagnosis → (always) a targeted, anchor-addressed revision of the live brief with a version log entry → (when the diagnosis generalizes) a proposed durable lesson via propose→confirm. Its distinct competences against a cheap stateless edit-brief regeneration: interpretation of perceptual reaction, state-preserving targeted revision (the director's checkboxes and hand edits survive), the version trail (its own next run's input), and lesson distillation. Tier 1 verbatim — no DaVinci API; every action Resolve-free-executable with upgrade flags, toolset facts retrieved never hardcoded.

**Inputs (resolved):** the live `edit-brief.md` (positional), feedback inline and/or `--feedback FILE` (batched — one run = one version bump), prior versions from the `versions/` subdir. Ambiguous moment references surface as unresolved, never guessed; mapping resolutions are logged visibly.

**Outputs:**
- The live brief revised **in place by targeted patch** (never re-rendered): `version` bumped, untouched director state preserved, modified/new steps unchecked, pre-patch snapshot to `versions/edit-brief.v{N}.md`
- A `## Version log` entry in the brief: version, date, feedback verbatim, anchors touched, changes, mapping resolutions, invalidated checked steps
- Specific change recommendations with Resolve-free actions, grounded in retrieved findings
- Lesson proposals (declarative preference + provenance) into `user_knowledge` domain `editing_preference` via propose→confirm — no owned collection (the concept-script test: the readers already exist)

**Mechanics:** the LLM never produces a number — timing shifts recomputed in code (time-shift engine); the LLM does diagnosis and step text only. Imports only `agent-runtime`; parses the brief as a foreign artifact by its anchors (the decoupling precedent — no edit-brief import). Knowledge grounding is edit-brief's line verbatim: composed retrieval over `technique_research_outputs` / `tutorial_research` / `user_knowledge` (1.25× boost, `editing_toolset` always loaded), feedback-driven queries, read-only v1 with gaps as named notations.

**CLI:** `feedback-iteration revise BRIEF.md "feedback" [--feedback FILE] [--max-cost N] [--dry-run]` — `--dry-run` is the free no-LLM parse/validate op.

**Orchestrator surface (built):** wrapped in `orchestrator.tools` per the `edit_brief_draft` / `edit_brief_discover` precedent — `feedback_revise` (child-budgeted; one Claude mapping/diagnosis call, no external money, patches the brief in place) and `feedback_inspect` (the free dry-run; no budget, spends nothing). Both record their delegation under the `feedback_iteration` label; no `search_knowledge` registry entry (owns no collection — lessons live in `user_knowledge`). The tool surface wraps brief path + feedback text; the orchestrator wraps but does not yet *chain* `edit-brief → feedback-iteration` (each tool is invoked independently — the chaining is on the v2 list).

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
Visual Generation   ──may delegate to──> Tutorial Research (for ComfyUI / Flux / WAN / LoRA technique)
Edit Brief          ──may delegate to──> Tutorial Research (for editing techniques)

Concept & Script / Technique Research ──inform──> Visual Generation (what to generate)
Visual Generation                     ──feeds───> Edit Brief (generated stills/clips as assets)
```

Tutorial Research is the only agent that gets delegated to by multiple others. It is the knowledge-acquisition arm of the system.

The map above is the *agent-to-agent* graph. The **Orchestrator Agent** (first slice built) sits above all of it: it can invoke any agent as a tool on the user's behalf, but no agent depends on it. It is an additional conversational entry point into the system, not a node in the production pipeline — so it is deliberately left out of the diagram above to keep that diagram about how the production agents relate to each other.

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

- **LangGraph.** No longer hypothetical or deferred — **now adopted** as the orchestration framework for the **Orchestrator Agent** (first slice built), which needs genuine stateful/branching/looping control flow and a conversation checkpointer. Scoped to that agent; the other five standalone agents stay on plain sequential LangChain, which suffices for them.
- **n8n.** Not used yet because CLI/library/MCP invocation covers current needs. A strong fit if integration-heavy or scheduled workflows arise, and a natural home if agents move to a Raspberry Pi. On the table.
- **Raspberry Pi deployment.** Everything runs on the M1 today, but porting some or all agents to a Pi — or running dedicated agents there — is a real future possibility. The architecture ports cleanly. Deferred, not foreclosed.
- **Google Sheets (or similar) as a logging/data layer.** Not used yet because Qdrant + filesystem covers it. For tabular, human-reviewable data (generation logs, project status) where Qdrant would be overkill, a spreadsheet is a reasonable choice. Open.
- **Hosted/cloud deployment.** Local-first today. Not planned, but not philosophically rejected either — a future need could justify it.
- **Additional invocation surfaces.** Telegram or other messaging triggers, voice input, web endpoints, scheduled triggers — any of these are fair game as ways to reach an agent when they're the better fit. CLI and library are just what exist now.

## Project Knowledge Storage

Each agent owns one or more Qdrant collections. The structure:

| Collection | Owned by | Contents |
|---|---|---|
| `user_knowledge` | `agent-runtime` (`UserKnowledgeStore`) | User-authored first-party knowledge: verified facts, doc distillations, hand-written experience. Shared across all agents. Seeded with Suno-mechanics facts (music-curation seed ingestion), ElevenLabs-mechanics facts (`domain=elevenlabs_mechanics`, via voiceover-direction's `knowledge ingest-docs` / `fact add`), and ComfyUI/RunPod-mechanics facts (`domain=comfyui_mechanics`, `domain=runpod_mechanics`) seeded from the Stable Diffusion / ComfyUI / WAN / Veo course documents. |
| `tutorial_research` | Tutorial Research | YouTube tutorial chunks + screenshot+caption multimodal points across all domains |
| `music_curation_memory` | Music Curation | Generation history (prompts + reactions + chains), taste lessons, templates, sound references |
| `voiceover_direction_memory` | Voiceover Direction | Takes (section text → voice/settings/reaction, section-scoped lineage) and direction lessons. The voice library is a local JSON registry, not a vector type; ElevenLabs-mechanics facts live in `user_knowledge` (`domain=elevenlabs_mechanics`). |
| `visual_generation_memory` | Visual Generation | Generation history (prompt + settings + workflow → result → reaction), settings/technique lessons, reusable ComfyUI workflow templates, reference notes. ComfyUI/RunPod-mechanics facts live in `user_knowledge` (`domain=comfyui_mechanics`, `domain=runpod_mechanics`). |
| `technique_research_outputs` | Technique Research | Curated per-technique findings (technique → description, why-it-matters, application notes, toolset fit, source refs; text-embedded) — designed, not yet created |
| `project_archive` | Cross-agent | Final artifacts and decisions from completed projects (planned, low priority) |

Cross-collection reads are fine. Tutorial Research's collection is *the* tutorial knowledge base; any agent can query it.

### Runtime-owned shared knowledge layer

`user_knowledge` is special: it is owned by the runtime, not by any single agent. Any agent can read from it; only `UserKnowledgeStore` writes to it (via a propose → confirm workflow for individual entries, or `bulk_load_verified` for seed ingestion). This prevents multiple agents from independently writing conflicting facts to the same shared collection. The propose/confirm workflow makes human review practical — entries can be inspected as drafts before committing to Qdrant. Drafts live in `~/agent-data/drafts/user_knowledge/` and expire after 7 days.

Ingesting a folder of local docs into `user_knowledge` is itself a **shared runtime mechanism** — `agent_runtime.knowledge.docs_ingest` (`ingest_docs`), domain-agnostic and parameterized by `domain` + source folder (no LLM; `##`+ heading → candidate → y/n/edit/defer → `bulk_load_verified`). voiceover-direction's `knowledge ingest-docs` command was refactored onto it (behavior-preserving), and visual-generation uses it for ComfyUI/RunPod docs.

### Schema migrations (planned)

**Status: not built.** A runtime-owned, domain-agnostic migration mechanism — same shape as `docs_ingest` and `UserKnowledgeStore` — that versions structural and data changes across *both* the Qdrant collections and the relational store the Orchestrator brings in (its LangGraph conversation checkpointer). It is the shared home for the migration-shaped work the system already does by hand today: the music-curation `approved → liked` one-shot, the `user_note → notes` shim, and the re-tag / re-embed fixes the Orchestrator's diagnostics flow will generate (this is the per-agent "remediation entry point" that diagnostics delegates to).

**Why a small custom runner, not Alembic.** Alembic only understands relational schemas; it has no concept of Qdrant collections, vectors, or payloads — and nearly all of this system's migrations live on the Qdrant side. So Alembic would manage only the relational slice, leaving the majority untracked or forcing a second system. A small custom runner speaks both stores and records applied migrations in one ledger. Alembic stays in reserve only if first-party relational tables are ever added beyond what LangGraph manages its own.

**Migrations are the source of truth for structure — by wrapping, not replacing, `ensure_collection`.** An idempotent `0001_baseline` brings a fresh environment (a new machine, the planned Raspberry Pi) to the current structure by calling the same `ensure_collection` each agent already calls, plus any standardized payload indexes. The existing populated DB is *stamped* as having `0001` applied without re-running it; future structural and data changes are `0002`, `0003`… on top. `ensure_collection` stays as a startup safety net in each agent — untouched — so this adds reproducibility and an audit trail without an invasive rewrite of the five built, tested agents.

Resolved design defaults (each open to revision):

- **Ledger storage — a single SQLite file (`~/agent-data/agent-stack.db`, table `schema_migrations`), recording migrations for both stores, each tagged by target.** It's the same SQLite file the Orchestrator's checkpointer already creates and uses (the orchestrator's first slice now calls LangGraph's `AsyncSqliteSaver.setup()` at startup, which manages its own `checkpoints`/`writes` tables in that file). The migration ledger remains unbuilt and is independent of the checkpointer's tables — when built it adds a `schema_migrations` table to the same file rather than introducing throwaway storage. The known cost is no cross-store atomicity — a migration can touch Qdrant and crash before the ledger row is written — so every migration must be idempotent/re-runnable. If the system ever goes multi-machine against one Qdrant, the ledger moves to Postgres (SQLite is single-writer).
- **Discovery — per-package, runner-discovered, with timestamp-prefixed IDs for a deterministic global order.** Agents own their migrations the same way they own their collections; cross-cutting migrations (the baseline, `user_knowledge`) live in `agent-runtime`. Timestamped IDs give total ordering without a central registry.
- **Execution — explicit `migrate status | up | stamp` CLI only; no auto-apply at agent startup.** Terminal-first, and Qdrant re-embeds can be expensive or destructive, so they must not fire silently on boot. (`ensure_collection` already covers "collection must exist" at startup; LangGraph's own checkpointer `.setup()` is the library managing its tables, separate from this.)
- **Reversibility — forward-only.** Matches the already-irreversible `approved → liked` migration; most Qdrant data migrations (re-embed, re-tag, drop) can't be cleanly reversed. Recovery is restore-from-backup then roll forward, not `down()`. An optional `down()` is permitted where it's genuinely cheap, never required.

## Build Order

A rough current order, subject to revision based on what the user wants to use next. This covers the agents identified so far; new agents will slot in wherever they make sense.

1. **Tutorial Research** — done (52 tests passing)
2. **Music Curation** — done (214 tests passing)
3. **Voiceover Direction** — done, Phase 2 MVP (145 tests passing). Built ahead of Concept & Script: it consumes a markdown-with-headings script, which a human can author directly, so it doesn't block on the scriptwriting agent existing yet.
4. **Concept & Script** — done, Phase 2 MVP (45 tests passing). Produces the `script.md` that Voiceover Direction consumes unchanged (and Edit Brief will consume later); the inline emotion-tag format aligns with the directed-script input contract already in place.
5. **Technique Research** — done, Phase 2 MVP (40 tests passing). Goal → prioritized technique domains → check existing knowledge → gate → delegate gaps to tutorial-research → curated `TechniqueReport` + accumulating `technique_research_outputs` findings; the heaviest exerciser of cross-agent delegation. Useful in parallel with the above; not blocking
6. **Visual Generation** — done, Phase 2 MVP (152 tests passing). ComfyUI-backed diffusion collaborator with multimodal own-memory (`voyage-multimodal-3`), the dual Claude/GPU budget separation, slot-map workflow templates, and a first-class tutor role (`explain`/`research`). Independently useful and not blocking on the editing-pipeline agents.
7. **Edit Brief** — needs the upstream agents to produce its inputs
8. **Feedback & Iteration** — needs Edit Brief to iterate on
9. **Orchestrator** — done, Phase 2 first build slice + Phase 3 sub-agent surface + diagnose-only diagnostics (42 tests passing). The conversational meta-agent over the whole system (LangGraph ReAct loop, SQLite checkpointer, knowledge + repo-access + all five built agents wrapped as tools — tutorial-research, music-curation, voiceover-direction, concept-script, visual-generation, exposing only their FREE / non-side-effecting ops; plus read-only vector-DB diagnostics that diagnose + report but never write); supersedes the old "Project Organizer" slot, whose file-scaffolding scope stays with Cowork. Remaining first-slice deferrals (per-agent remediation entry points, MCP, extra surfaces, Haiku utility, the hard ceiling) are tracked in its section above.

Beyond these, the roster is open — thumbnail design, social scheduling, analytics, and others will be added as the need becomes concrete (image generation, once on this list, is now the planned Visual Generation agent above).

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
| RunPod | Pay-per-hour GPU rental; content-permissive for legal adult content | GPU/compute platform for the Visual Generation agent; pod start/stop discipline tracked and advised |
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
