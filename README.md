# agent-stack

A uv workspace for a multi-agent AI system. Specialized agents share a common runtime layer, a Qdrant vector store, and OpenTelemetry-based observability.

## Packages

| Package | Description | Status |
|---|---|---|
| `agent-runtime` | Shared base types, clients, and utilities used by all agents | Complete (168 tests) |
| `yt-intelligence-pipeline` | YouTube tutorial ingestion — Obsidian notes for humans, Qdrant vectors for agents | Complete (45 tests) |
| `tutorial-research` | Domain-agnostic agent that discovers, ingests, and synthesizes tutorial content; queries both `tutorial_research` and `user_knowledge` collections | Complete (52 tests) |
| `music-curation` | Music-theory expert with persistent memory for crafting Suno prompts | Complete (213 tests) |
| `voiceover-direction` | Director for ElevenLabs voiceover — free LLM direction, deliberate paid generation, persistent takes + direction lessons | Complete (145 tests) |

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
│   └── voiceover-direction/        # ElevenLabs voiceover director
├── infrastructure/                 # docker-compose.yml (Qdrant + Jaeger)
└── docs/
    └── architecture.md             # detailed design and API reference
```

## Running Tests

```bash
uv sync --all-packages && uv run pytest -v   # full suite (623 tests)
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
```

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

## Qdrant Collections

| Collection | Contents |
|---|---|
| `user_knowledge` | Runtime-owned user-authored knowledge (Suno-mechanics + ElevenLabs-mechanics facts + other verified knowledge) |
| `tutorial_research` | YouTube tutorial transcripts + screenshots (populated by tutorial-research) |
| `music_curation_memory` | Generation history, taste lessons, templates, sound references (music-curation) |
| `voiceover_direction_memory` | Takes (text → voice/settings/reaction) and direction lessons (voiceover-direction) |

## Required Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `VOYAGE_API_KEY` | Voyage AI key (text + multimodal embeddings) |
| `OBSIDIAN_OUTPUT_PATH` | Path to your Obsidian vault folder for pipeline notes |
| `ELEVENLABS_API_KEY` | Required for voiceover-direction (voice sync, usage query, TTS generation) |
| `TAVILY_API_KEY` | Optional — web search for research agents |
| `LANGSMITH_API_KEY` | Optional — LangSmith tracing for pipeline chains |
