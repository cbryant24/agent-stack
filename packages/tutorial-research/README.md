# tutorial-research

Domain-agnostic agent that autonomously discovers, ingests, and synthesizes tutorial content into a queryable Qdrant knowledge base for other agents to consume. Uses Tavily for discovery, yt-intelligence-pipeline for ingestion, and Sonnet 4.6 for synthesis. Depends on `agent-runtime`.

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
print(result.retrieved)              # list of RetrievedChunk with source metadata
print(result.report_path)            # path to Obsidian run report
```

### `ResearchResult` fields

| Field | Type | Description |
|---|---|---|
| `request_type` | `"research" \| "ingest" \| "retrieve"` | Inferred or explicit mode |
| `status` | `"completed" \| "partial" \| "failed"` | `partial` if budget exhausted or any item fails silently |
| `plan` | `IngestionPlan \| None` | Candidates scored and selected |
| `ingested` | `list[IngestedVideo]` | Videos actually ingested this run |
| `retrieved` | `list[RetrievedChunk]` | Chunks retrieved for synthesis context |
| `synthesis` | `str \| None` | Sonnet-generated summary with source attribution |
| `report_path` | `Path \| None` | Obsidian-compatible Markdown report |
| `cost_usd` | `float` | Total spend this run |
| `items_processed` | `int` | Items processed (works even on partial runs) |

### `RetrievedChunk` fields

| Field | Type | Description |
|---|---|---|
| `score` | `float` | Cosine similarity score from Qdrant |
| `source_id` | `str` | e.g. `"youtube:abc123"` |
| `content` | `str` | Text content of the chunk |
| `source_title` | `str \| None` | Video title (populated from MemoryPoint at ingest time) |
| `source_url` | `str \| None` | Original YouTube URL |
| `chunk_index` | `int \| None` | Position of this chunk within its source video |

## CLI

```bash
# NOTE: the CLI is a command group — the bare `tutorial-research "<query>"` form
# is gone. Use the `research` subcommand.

# Research mode (default)
uv run tutorial-research research "python asyncio patterns"

# Plan only — scores candidates but skips ingestion
uv run tutorial-research research "python asyncio patterns" --plan-only

# Explicit type override / skip synthesis
uv run tutorial-research research "python asyncio patterns" --type retrieve --no-synthesize

# Budget overrides
uv run tutorial-research research "python asyncio patterns" --max-items 10 --max-cost 5.00

# Bulk-ingest local course markdown into tutorial_research (course_doc chunks)
uv run tutorial-research ingest-docs ~/agent-data/<course-docs-folder> --dry-run
uv run tutorial-research ingest-docs ~/agent-data/<course-docs-folder> --yes
```

## Course-doc ingest (`ingest-docs`)

`ingest-docs <folder>` bulk-loads local course markdown into the `tutorial_research` collection as `course_doc` chunks — one `MemoryPoint` per kept H2 section — so course material is retrievable alongside the YouTube-derived chunks (and by `visual-generation explain`). A file is ingested only if its frontmatter `course` matches `--course` (default: the Diffusion Mastery course); within a file only the keep-set H2s are kept (Quick Review / Key Concepts / Practical Applications / Important Details), empty bodies skipped. `source_id` is `course:diffusion-mastery/<file-stem>`. Re-runs are idempotent — chunks already present under that `source_id` are skipped. It embeds via Voyage, so the store must be reachable: wrap in `op run --env-file=".env"` for the keys, and `--dry-run` first to see the per-section breakdown.

Course docs are tutorial-derived *technique* — intentionally **not** `user_knowledge` (platform facts, via visual-generation's `fact ingest-docs`) or `technique_lesson` (learned-by-doing).

## Default budget

```
max_items=5, max_cost_usd=2.00, max_wall_time_sec=900
```

Wall-time budget absorbs Whisper fallback cost on videos without captions. A `partial` result is a valid outcome — it occurs when the budget is exhausted mid-run or when one or more `process_video` calls fail silently (ingested fewer items than planned).

## Observability

Each run emits a JSONL trace and an Obsidian Markdown report. The report includes:
- LLM usage by model (Haiku scoring + Sonnet synthesis)
- Ingestion plan with scored candidates
- **Coverage assessment**: after ingestion, retrieved chunks are evaluated for `empty` / `sparse` / `thin` / `adequate` coverage and appended to the report
- **Retrieved content**: top-10 retrieved chunks with similarity scores and source titles, appended after the coverage assessment

Coverage thresholds:
- `empty` — no chunks retrieved
- `sparse` — max similarity score < 0.55
- `thin` — fewer than 3 distinct source IDs
- `adequate` — all thresholds met

## Running tests

```bash
uv run pytest packages/tutorial-research/tests/ -v   # 58 tests
```

Tests that require Qdrant on `localhost:6333` are skipped automatically if it's not running.

## FAQ

Common questions and knowledge gaps about this agent. Add entries as they come up — capture anything that surprised you about its capabilities, flags, costs, or where its outputs land.

<!-- Template for a new entry:
### Q: <the question, as you'd actually ask it>
<the answer, with the exact command/flag/path where relevant>
-->

### Where do this agent's files go?
`-o` outputs are director-owned working files — put them in your per-project folder (`~/agent-projects/<project-slug>/`). Machine-managed outputs (sources, audio, stills, qdrant) go under `~/agent-data/`, and run reports auto-write to `~/obsidian/agent-reports/`. Canonical, single-source-of-truth detail: [File organization](../../README.md#where-should-project-files-live) in the repo root README.
