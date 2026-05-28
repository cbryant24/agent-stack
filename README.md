# agent-stack

A uv workspace for a multi-agent AI system. Specialized agents share a common runtime layer, a Qdrant vector store, and OpenTelemetry-based observability.

## Packages

| Package | Description | Status |
|---|---|---|
| `agent-runtime` | Shared base types, clients, and utilities used by all agents | Complete (133 tests) |
| `yt-intelligence-pipeline` | YouTube tutorial ingestion — Obsidian notes for humans, Qdrant vectors for agents | Complete (40 tests) |
| `tutorial-research` | Domain-agnostic agent that discovers, ingests, and synthesizes tutorial content into a queryable knowledge base for other agents | Complete (41 tests) |
| `music-curation` | Agent that curates and organizes music recommendations | Under development |

## Setup

**1. Install dependencies**
```bash
uv sync
```

**2. Copy and fill environment variables**
```bash
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, VOYAGE_API_KEY, OBSIDIAN_OUTPUT_PATH at minimum
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
│   └── music-curation/             # music agent
├── infrastructure/                 # docker-compose.yml (Qdrant + Jaeger)
└── docs/
    └── architecture.md             # detailed design and API reference
```

## Running Tests

```bash
uv run pytest -v                   # full suite (214 tests)
```

Tests that require Qdrant on `localhost:6333` are skipped automatically if it's not running. No tests require real Voyage or Anthropic API keys.

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
| `~/obsidian/agent-reports/` | Agent-generated Markdown reports |

## Required Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `VOYAGE_API_KEY` | Voyage AI key (text + multimodal embeddings) |
| `OBSIDIAN_OUTPUT_PATH` | Path to your Obsidian vault folder for pipeline notes |
| `TAVILY_API_KEY` | Optional — web search for research agents |
| `LANGSMITH_API_KEY` | Optional — LangSmith tracing for pipeline chains |
