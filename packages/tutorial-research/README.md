# tutorial-research

Agent that autonomously researches and synthesizes programming tutorials. Uses Tavily for discovery, yt-intelligence-pipeline for ingestion, and Sonnet 4.6 for synthesis. Depends on `agent-runtime`.

## Request modes

| Mode | When | What happens |
|------|------|-------------|
| `research` | Default for open-ended topics | Tavily discovery → Haiku 4.5 scoring → `process_video` ingestion → Sonnet synthesis |
| `ingest` | Request contains a YouTube URL | Skips Tavily; scores and ingests URLs directly |
| `retrieve` | Request contains "find", "show me what", etc. | Qdrant retrieval only; no new ingestion |

Mode is inferred automatically; override with `request_type=` or `--type`.

## Library API

```python
from tutorial_research import research_sync, research, ResearchResult

# Sync
result = research_sync("python asyncio patterns")

# Async
result = await research("python asyncio patterns")

# With options
result = research_sync(
    "python asyncio patterns",
    synthesize=True,           # default True for research mode
    dry_run=True,              # plan only, no ingestion
    collection="my_collection",
)

print(result.plan.estimated_items)   # how many videos selected
print(result.synthesis)              # Sonnet-generated synthesis text
print(result.report_path)            # path to Obsidian run report
```

### `ResearchResult` fields

| Field | Type | Description |
|---|---|---|
| `request_type` | `"research" \| "ingest" \| "retrieve"` | Inferred or explicit mode |
| `status` | `"completed" \| "partial" \| "failed"` | `partial` when budget exhausted mid-run |
| `plan` | `IngestionPlan \| None` | Candidates scored and selected |
| `ingested` | `list[IngestedVideo]` | Videos actually ingested this run |
| `retrieved` | `list[RetrievedChunk]` | Chunks retrieved for synthesis context |
| `synthesis` | `str \| None` | Sonnet-generated summary with source attribution |
| `report_path` | `Path \| None` | Obsidian-compatible Markdown report |
| `cost_usd` | `float` | Total spend this run |
| `items_processed` | `int` | Items processed (works even on partial runs) |

## CLI

```bash
# Research mode (default)
uv run tutorial-research "python asyncio patterns"

# Plan only — scores candidates but skips ingestion
uv run tutorial-research "python asyncio patterns" --plan-only

# Explicit type override
uv run tutorial-research "python asyncio patterns" --type retrieve

# Skip synthesis
uv run tutorial-research "python asyncio patterns" --no-synthesize

# Budget overrides
uv run tutorial-research "python asyncio patterns" --max-items 10 --max-cost 5.00
```

## Default budget

```
max_items=5, max_cost_usd=2.00, max_wall_time_sec=900
```

Wall-time budget absorbs Whisper fallback cost on videos without captions. A `partial` result with 3 of 5 items processed is a valid outcome.

## Observability

Each run emits a JSONL trace and an Obsidian Markdown report. The report includes:
- LLM usage by model (Haiku scoring + Sonnet synthesis)
- Ingestion plan with scored candidates
- **Coverage assessment**: after ingestion, retrieved chunks are evaluated for `empty` / `sparse` / `thin` / `adequate` coverage and appended to the report

Coverage thresholds:
- `empty` — no chunks retrieved
- `sparse` — max similarity score < 0.55
- `thin` — fewer than 3 distinct source IDs
- `adequate` — all thresholds met

## Running tests

```bash
uv run pytest packages/tutorial-research/tests/ -v   # 35 tests
```

Tests that require Qdrant on `localhost:6333` are skipped automatically if it's not running.
