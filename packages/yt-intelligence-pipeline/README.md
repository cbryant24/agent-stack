# yt-intelligence-pipeline

YouTube tutorial ingestion for the agent-stack workspace. Converts YouTube videos into two kinds of output:

- **Human mode** — Obsidian Markdown notes with a structured summary, key takeaways, and optional screenshots. Same as the standalone pipeline.
- **Agent mode** — Chunks the cleaned transcript and embeds it into Qdrant via the `agent-runtime` memory layer, making the content retrievable by AI agents through semantic search.

Both modes can run together. The `tutorial-research` agent is the first consumer of agent mode.

## Installation

This is a workspace member — no separate install needed:

```bash
cd ~/projects/agent-stack
uv sync
```

The CLI becomes available as `yt-pipeline`.

## CLI Usage

```bash
# Human note only (default)
yt-pipeline <url>

# Skip screenshots (faster, no ffmpeg/yt-dlp video download)
yt-pipeline <url> --no-screenshots

# Agent mode only (Qdrant ingestion, no Obsidian note)
yt-pipeline <url> --output agent

# Both modes at once
yt-pipeline <url> --output both

# Custom Qdrant collection
yt-pipeline <url> --output agent --collection my_collection

# Playlist (human mode, skipping already-processed videos)
yt-pipeline <playlist_url> --skip-existing

# Playlist into Qdrant
yt-pipeline <playlist_url> --output both --no-screenshots
```

## Library Usage

The pipeline is designed to be imported by agents:

```python
from yt_intelligence_pipeline import process_video, PipelineResult

# Human note only
result: PipelineResult = await process_video(
    "https://www.youtube.com/watch?v=...",
    use_screenshots=False,
    human_output=True,
    agent_output=False,
)
print(result.human_output_path)

# Agent ingestion only (no Obsidian note required)
result = await process_video(
    "https://www.youtube.com/watch?v=...",
    use_screenshots=False,
    human_output=False,
    agent_output=True,
    collection_name="tutorial_research",
)
ao = result.agent_output
print(f"{ao.text_points_upserted} text chunks + {ao.multimodal_points_upserted} images → {ao.collection_name}")

# Both
result = await process_video(url, human_output=True, agent_output=True)
```

### MultimodalInput

When screenshots are present (`use_screenshots=True`), agent mode automatically embeds them alongside their caption labels using `voyage-multimodal-3`:

```python
from agent_runtime import MultimodalInput

# Supported image formats: .png, .jpg, .jpeg, .webp, .gif
m = MultimodalInput(text="caption text", image_path=Path("screenshot.png"))
```

The pipeline copies screenshots to `~/agent-data/sources/youtube-tutorials/<video_id>/screenshots/` for agent access. The Obsidian vault is never read by agents.

### Sync wrapper

```python
from yt_intelligence_pipeline import process_video_sync

result = process_video_sync("https://...", agent_output=True)
```

## Environment Variables

All variables are read from the workspace `.env` at `~/projects/agent-stack/.env`.

| Variable | Required | Description |
|----------|----------|-------------|
| `PRODUCTION_AGENTS_ANTHROPIC_API_KEY` | Yes | Claude API key for transcript cleanup, summary, and timestamp chains |
| `LANGSMITH_API_KEY` | Yes | LangSmith tracing key |
| `OBSIDIAN_OUTPUT_PATH` | Human mode | Absolute path to your Obsidian vault folder |
| `VOYAGE_API_KEY` | Agent mode | Voyage AI key for embeddings |
| `QDRANT_URL` | Agent mode | Qdrant URL (default: `http://localhost:6333`) |
| `LANGSMITH_PROJECT` | Optional | LangSmith project name (default: `youtube-tutorial-pipeline`) |
| `LANGCHAIN_TRACING_V2` | Optional | Enable LangChain tracing (default: `true`) |

See `.env.example` at the workspace root for a template.

## Output Destinations

### Human mode
- Note: `$OBSIDIAN_OUTPUT_PATH/<slug>.md`
- Screenshots: `$OBSIDIAN_OUTPUT_PATH/<slug>/screenshot_NNN.png`

### Agent mode
- Transcript: `~/agent-data/sources/youtube-tutorials/<video_id>/transcript.txt`
- Metadata: `~/agent-data/sources/youtube-tutorials/<video_id>/metadata.json`
- Screenshots: `~/agent-data/sources/youtube-tutorials/<video_id>/screenshots/screenshot_NNN.png`
- Vectors: Qdrant collection `tutorial_research` (or `--collection` value)

## Pipeline Steps

1. **Metadata** — yt-dlp fetches title, channel, duration
2. **Transcript** — YouTube captions (primary) → Whisper local model (fallback)
3. **Cleanup** — Claude removes filler, adds punctuation, preserves technical terms
4. **Summary** — Claude produces a structured summary, key takeaways, and Obsidian tags
5. **Timestamps** — Claude identifies screenshot-worthy moments *(screenshots only)*
6. **Frame extraction** — ffmpeg extracts PNG frames at selected timestamps *(screenshots only)*
7. **Output** — Obsidian note written *(human mode)* / chunks embedded and upserted to Qdrant *(agent mode)*

## Relationship to agent-runtime

The pipeline uses `agent-runtime` for all memory infrastructure:

| Capability | agent-runtime symbol |
|-----------|---------------------|
| Chunking | `chunk_document(text, target_tokens=512, overlap_tokens=64)` |
| Text embedding | `EmbeddingClient.embed()` — `voyage-3-large`, 1024-dim |
| Multimodal embedding | `EmbeddingClient.embed_multimodal()` — `voyage-multimodal-3`, 1024-dim |
| Vector storage | `MemoryStore.upsert_points()`, `MemoryStore.search()` |
| Config | `get_config()` for `agent_data_dir` and `qdrant_url` |

Chunking, embedding, and Qdrant operations are not reimplemented here.

## FAQ

Common questions and knowledge gaps about this agent. Add entries as they come up — capture anything that surprised you about its capabilities, flags, costs, or where its outputs land.

<!-- Template for a new entry:
### Q: <the question, as you'd actually ask it>
<the answer, with the exact command/flag/path where relevant>
-->

### Where do this agent's files go?
`-o` outputs are director-owned working files — put them in your per-project folder (`~/agent-projects/<project-slug>/`). Machine-managed outputs (sources, audio, stills, qdrant) go under `~/agent-data/`, and run reports auto-write to `~/obsidian/agent-reports/`. Canonical, single-source-of-truth detail: [File organization](../../README.md#where-should-project-files-live) in the repo root README.
