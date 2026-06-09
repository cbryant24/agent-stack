# agent-stack

A uv workspace for a multi-agent AI system. Specialized agents share a common runtime layer, a Qdrant vector store, and OpenTelemetry-based observability.

## Packages

| Package | Description | Status |
|---|---|---|
| `agent-runtime` | Shared base types, clients, and utilities used by all agents (incl. the shared `docs_ingest` knowledge mechanism) | Complete (178 tests) |
| `yt-intelligence-pipeline` | YouTube tutorial ingestion — Obsidian notes for humans, Qdrant vectors for agents | Complete (45 tests) |
| `tutorial-research` | Domain-agnostic agent that discovers, ingests, and synthesizes tutorial content; queries both `tutorial_research` and `user_knowledge` collections | Complete (52 tests) |
| `music-curation` | Music-theory expert with persistent memory for crafting Suno prompts | Complete (214 tests) |
| `voiceover-direction` | Director for ElevenLabs voiceover — free LLM direction, deliberate paid generation, persistent takes + direction lessons | Complete (145 tests) |
| `concept-script` | Structural/craft scriptwriting collaborator — seeds or a dictation transcript → an editable `script.md` that `voiceover-direction` consumes unchanged | Complete (45 tests) |
| `visual-generation` | ComfyUI-backed diffusion collaborator + platform tutor — free offline prompt-craft, deliberate warm-session GPU generation, persistent generations/technique-lessons/workflow-templates | Complete (152 tests) |

## Setup

**1. Install dependencies**
```bash
uv sync
```

**2. Copy and fill environment variables**
```bash
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, VOYAGE_API_KEY, OBSIDIAN_OUTPUT_PATH at minimum
# (set ELEVENLABS_API_KEY too if using voiceover-direction)
```

**3. Start infrastructure (Qdrant + Jaeger)**
```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

**4. Verify**
```bash
curl http://localhost:6333/healthz    # Qdrant
open http://localhost:16686           # Jaeger UI
```

## Workspace Structure

```
agent-stack/
├── pyproject.toml                  # workspace root + pytest config
├── .env                            # API keys and paths (not committed)
├── .env.example                    # template
├── packages/
│   ├── agent-runtime/              # shared runtime (config, tracing, budget, memory, reporting)
│   ├── yt-intelligence-pipeline/   # YouTube ingestion pipeline
│   ├── tutorial-research/          # tutorial agent
│   ├── music-curation/             # music agent
│   ├── voiceover-direction/        # ElevenLabs voiceover director
│   ├── concept-script/             # scriptwriting collaborator (→ script.md)
│   └── visual-generation/          # ComfyUI diffusion collaborator
├── infrastructure/                 # docker-compose.yml (Qdrant + Jaeger)
└── docs/
    └── architecture.md             # detailed design and API reference
```

## Running Tests

```bash
uv sync --all-packages && uv run pytest -v   # full suite (831 tests)
```

Tests that require Qdrant on `localhost:6333` are skipped automatically if it's not running. No tests require real Voyage, Anthropic, or ElevenLabs API keys.

## YouTube Pipeline

**Human mode** (Obsidian note):
```bash
uv run yt-pipeline "https://www.youtube.com/watch?v=..." --output human
```

**Agent mode** (Qdrant ingestion):
```bash
uv run yt-pipeline "https://www.youtube.com/watch?v=..." --output agent
```

**Both:**
```bash
uv run yt-pipeline "https://www.youtube.com/watch?v=..." --output both
```

**As a library:**
```python
from yt_intelligence_pipeline import process_video

result = await process_video(
    "https://www.youtube.com/watch?v=...",
    human_output=True,
    agent_output=True,
    collection_name="tutorial_research",
)
```

## Tutorial Research Agent

**Research mode** (Tavily discovery → ingestion → synthesis):
```bash
uv run tutorial-research "suno prompt structures"
```

**Plan only** (score candidates, no ingestion):
```bash
uv run tutorial-research "suno prompt structures" --plan-only
```

**Retrieve mode** (query existing knowledge base):
```bash
uv run tutorial-research "suno meta tags for vocal control" --type retrieve
```

**As a library:**
```python
from tutorial_research import research_sync

result = research_sync("suno prompt structures")
print(result.synthesis)       # Sonnet-generated summary
print(result.retrieved)       # list of RetrievedChunk (score, content, source_title, source_url)
print(result.plan)            # scored candidates
print(result.report_path)     # Obsidian run report
```

## Data Directories

| Directory | Contents |
|---|---|
| `~/agent-data/` | Run artifacts, source files, Qdrant storage |
| `~/agent-data/sources/youtube-tutorials/<id>/` | Transcripts, metadata, screenshots per video |
| `~/agent-data/runs/<date>/<agent>/<run_id>/` | JSONL trace files |
| `~/agent-data/drafts/user_knowledge/` | Pending `UserKnowledgeStore` entries awaiting confirmation (7-day expiry) |
| `~/obsidian/agent-reports/` | Agent-generated Markdown reports |

## Music Curation Agent

**Generate Suno prompts:**
```bash
music-curation generate "lo-fi hip-hop for late-night studying"

# For longer, repeated requests, keep a markdown file per genre and pipe it in
# (see packages/music-curation/cli-prompts/TEMPLATE.md for a commented starting point):
music-curation generate "$(cat packages/music-curation/cli-prompts/blues.md)"
```

Length is controlled by song structure, not a duration slider — a target like "around 2
minutes" is mapped to a concrete section count, and an explicit section list is reproduced
exactly. A one-off spec in the request overrides saved taste for that song without changing
it; to set a durable length/structure preference use `taste add ... --scope arrangement`.

**Record your reaction after running in Suno:**
```bash
music-curation report <gen_id> --reaction loved
```

**Search your generation history:**
```bash
music-curation recall "phonk with heavy bass"
```

**Review pending generations:**
```bash
music-curation review-pending
```

**Seed from session files:**
```bash
music-curation seed ingest ~/path/to/session-files/    # interactive confirmation
music-curation seed ingest ~/path/to/file.md --dry-run # preview without writing
music-curation seed review-taste                       # review deferred taste lessons
```

**As a library:**
```python
from music_curation import curate_sync, MusicResult

result = curate_sync("atmospheric jazz with French café vibes")
for prompt in result.prompts:
    print(prompt.style_field)     # paste into Suno
    print(prompt.lyrics_field)    # optional lyrics structure
print(result.theory_reasoning)    # why these choices work
```

## Voiceover Direction Agent

Direction is free LLM iteration; generation spends a scarce monthly ElevenLabs character
budget. So you direct freely, then generate as a deliberate commitment, then react after
listening.

**Direct a script** (free, re-runnable — writes an editable directed-script file):
```bash
voiceover-direction direct script.md
```

**Generate audio** (spends ElevenLabs characters — soft-inform cost gate, folds in `report`
notes as a section re-direction):
```bash
voiceover-direction generate script.directed.md --section intro   # one section
voiceover-direction generate script.directed.md --all             # every section
```

**React after listening** (flips the take pending → complete):
```bash
voiceover-direction report <take_id> --reaction loved --rating 5
```

**Inspect and direct-write:**
```bash
voiceover-direction review-pending                        # takes awaiting a reaction
voiceover-direction recall "energetic intro narration"    # search prior takes + lessons
voiceover-direction lesson add "Rachel reads calm intros well" --scope voice
voiceover-direction fact add "eleven_v3 reads inline audio tags"
```

**Knowledge + voices:**
```bash
voiceover-direction knowledge ingest-docs ~/elevenlabs-docs/   # local docs → user_knowledge
voiceover-direction voice sync                                 # pull voices from ElevenLabs
```

**As a library:**
```python
from voiceover_direction import direct_sync, generate_sync

result = direct_sync("script.md")                                 # DirectionResult
print(result.output_path)                                         # the directed-script file
result = generate_sync("script.directed.md", all_sections=True)   # GenerationResult (no gate)
```

## Concept & Script Agent

A structural/craft scriptwriting collaborator. It proposes section breakdown, pacing, and
candidate per-section emotion direction, and **surfaces, never decides** the creative core —
you own every decision by editing the file. Both modes emit a single editable `script.md`
that `voiceover-direction direct` consumes unchanged.

**Generative — sparse seeds → script.md** (optionally anchored to a prior script):
```bash
concept-script draft --seeds seeds.md -o script.md
concept-script draft --seeds seeds.md --ref prior-script.md -o script.md
concept-script draft "focus, calm, ~2 min, video essay"          # inline seeds
```

`packages/concept-script/cli-prompts/SEEDS_TEMPLATE.md` is a fill-in-the-blanks starting point.

**Curation — a verbatim dictation transcript → script.md:**
```bash
concept-script shape transcript.txt -o script.md
concept-script shape transcript.txt --clean      # resolve self-corrections away
```

`shape` strips disfluencies and resolves an in-band command channel: `director note, delete
that last portion` is executed and removed, with each executed cut listed in a trailer (a
global note like "remove every 'young' descriptor" is one summarizing entry). Natural
stumbles/self-corrections are **kept as content by default** — authentic texture the voiceover
agent narrates; pass `--clean` to resolve them into final prose instead (`--clean` is
shape-only and affects only self-corrections). The logline, optional `Music:` hint, and the
cut trailer live in the pre-heading preamble, which the voiceover parser skips — so the file
hands off to `voiceover-direction direct` with nothing leaking into narration.

**As a library:**
```python
from concept_script import draft_sync, shape_sync

result = draft_sync("late-night focus, contemplative, ~2 min")    # ConceptResult
print(result.script_path)                                         # the written script.md
print(result.brief.logline, [s.heading for s in result.brief.sections])
result = shape_sync(open("transcript.txt").read())               # preserve corrections (default)
result = shape_sync(open("transcript.txt").read(), clean=True)   # resolve corrections away
print(result.brief.cut_trailer)                                  # executed director-note cuts
```

concept-script is **stateless** — it owns no Qdrant collection; prior work is reused via
`--ref`. See `packages/concept-script/README.md` and `docs/v2-refinements-concept-script.md`.

## Visual Generation Agent

A ComfyUI-backed diffusion collaborator and platform tutor. It inherits voiceover-direction's
cost inversion, more extreme: **prompt-craft is free, infinitely iterable LLM work; GPU is the
scarce, paid step.** So a turn is **settle the specs offline (free), spin up the pod, drain a
batch in one warm session, spin down** — `draft` → `generate` → `report`. Two budgets stay
orthogonal: per-run Claude cost rides agent-runtime's `BudgetEnvelope`; **GPU/pod spend lives on
a separate agent-local tracker** and is *advised, never enforced* (soft-inform gate, optional
`--max-session-cost` ceiling). v1 holds **no RunPod credential** — you spin the pod up and pass
the agent your ComfyUI `--endpoint`; it advises stop-on-drain. Stills-first (Flux); video (WAN)
is a fast-follow on the same path.

**Craft offline** (free — Claude only, no GPU; appends to an editable batch file):
```bash
visual-generation draft "<intent>" [-o batch.md] [--template <name>]
```

**Generate in one warm session** (spends GPU — soft-inform gate; you spin the pod up):
```bash
visual-generation generate batch.md --section <id> --endpoint <url>   # one spec
visual-generation generate batch.md --all --endpoint <url> [--max-session-cost N] [-y]
```

**React after viewing** (flips the generation pending → complete):
```bash
visual-generation report <gen_id> --reaction <loved|liked|liked_with_changes|disliked|render_failed> [--rating 1-5]
```

**Backend + templates:**
```bash
visual-generation model sync --endpoint <url>        # registry from ComfyUI /object_info
visual-generation model list
visual-generation workflow register <exported-api.json>   # infer slot map, propose→confirm
visual-generation workflow list
```

**Inspect, direct-write, and tutor:**
```bash
visual-generation review-pending                          # generations awaiting a reaction
visual-generation recall "<query>"                        # search your own generations + lessons + templates
visual-generation chain show <root_id>                    # a lineage tree
visual-generation lesson add "<statement>" --scope settings --valence negative
visual-generation fact add "<statement>" --domain comfyui_mechanics
visual-generation explain "<concept>" [--level full|concise|quiet]   # grounded deep-dive (Claude)
visual-generation research "<topic>"                      # delegate to tutorial-research (Claude)
```

**As a library:**
```python
from visual_generation import draft_sync, generate_sync

result = draft_sync("a cinematic neon wolf in the rain")          # DraftResult (.spec, .batch_path)
result = generate_sync("batch.md", all_sections=True, endpoint="http://pod:8188")  # GenerationResult
```

## Qdrant Collections

| Collection | Contents |
|---|---|
| `user_knowledge` | Runtime-owned user-authored knowledge (Suno-mechanics + ElevenLabs-mechanics facts + other verified knowledge) |
| `tutorial_research` | YouTube tutorial transcripts + screenshots (populated by tutorial-research) |
| `music_curation_memory` | Generation history, taste lessons, templates, sound references (music-curation) |
| `voiceover_direction_memory` | Takes (text → voice/settings/reaction) and direction lessons (voiceover-direction) |
| `visual_generation_memory` | Generations (image+caption multimodal), technique lessons, workflow templates (visual-generation) |

## Required Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `VOYAGE_API_KEY` | Voyage AI key (text + multimodal embeddings) |
| `OBSIDIAN_OUTPUT_PATH` | Path to your Obsidian vault folder for pipeline notes |
| `ELEVENLABS_API_KEY` | Required for voiceover-direction (voice sync, usage query, TTS generation) |
| `TAVILY_API_KEY` | Optional — web search for research agents |
| `LANGSMITH_API_KEY` | Optional — LangSmith tracing for pipeline chains |

visual-generation needs no new key: it talks to a user-supplied ComfyUI `--endpoint` (the pod
you spin up) and holds no RunPod credential in v1.
