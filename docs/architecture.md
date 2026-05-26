# Architecture

## Overview

`agent-stack` is a uv workspace containing a shared runtime library and several specialized packages. All packages are installed into a single `.venv` at the workspace root; they share dependencies and import each other as workspace members.

## Packages

### agent-runtime

The shared infrastructure layer. All other packages import from here. **Status: complete.** 167 tests passing.

#### Layer 1 — Config & Models

- **`RuntimeConfig`** (`pydantic-settings`) — reads `.env`, validates required API keys, silently creates `~/agent-data/{sources,runs,qdrant}/` and `~/obsidian/agent-reports/` on startup
- **`get_config()` / `reset_config()`** — `lru_cache`'d singleton; `reset_config()` clears it for test isolation
- **Models** — `BudgetEnvelope`, `BudgetConsumption`, `BudgetRemaining`, `DelegationRequest`, `DelegationResult`, `TraceEvent`
- **Exceptions** — `AgentRuntimeError`, `BudgetExhaustedError`, `ConfigurationError`, `DelegationError`

#### Layer 2 — Tracing

- **`@traced`** decorator — handles sync and async, records span attributes from args, captures exceptions
- **`span(name)`** — context manager for manual OTel spans
- **Record helpers** — `record_llm_call`, `record_tool_call`, `record_delegation`, `record_memory_query`, `record_memory_write`; all emit OTel span attributes and, if a `TracePersister` is active, append `TraceEvent` JSONL lines
- **`TracePersister`** — sync context manager (`__enter__`/`__exit__`); writes `~/agent-data/runs/<date>/<agent>/<run_id>/trace.jsonl` using `threading.Lock`; exposes via `_current_persister` ContextVar so record helpers find it without being passed explicitly
- **`init_tracing(service_name)`** — configures OTLPSpanExporter pointing at `get_config().otel_endpoint`

#### Layer 3 — Budget & Delegation

- **`BudgetTracker`** — async context manager; tracks cost (USD), tool calls, items processed, wall time; raises `BudgetExhaustedError` when any dimension is exceeded; emits summary `TraceEvent` on exit
- **Pricing table** (2026-05-26): `claude-opus-4-7/4-6` $15/$75, `claude-sonnet-4-6` $3/$15, `claude-haiku-4-5` $0.80/$4 per 1M tokens
- **`_current_tracker`** ContextVar — lets nested code access the active `BudgetTracker` without explicit passing
- **`register_agent` / `get_agent` / `list_agents`** — module-level agent registry
- **`delegate(target, request, budget)`** — derives child `BudgetEnvelope`, guards depth, wraps handler in child `BudgetTracker`, auto-debits parent

#### Layer 4 — Memory

- **`MemoryPoint`** — Pydantic model for a vector payload; fields include `source_id`, `source_type`, `content_type` (`"text"` or `"image_with_caption"`), `image_path`, `caption`, `chunk_index`, `domain_tags`, `topic_tags`. `to_qdrant_point(vector)` converts to `PointStruct`. `from_qdrant_payload()` handles missing `content_type` for backward compat (defaults to `"text"`).
- **`MultimodalInput`** — Pydantic model for embedding inputs; validates image existence and extension (`.png .jpg .jpeg .webp .gif`); `to_voyage_content()` returns `list[str | PIL.Image.Image]` (the format the Voyage Python SDK's `multimodal_embed` actually expects — NOT REST API dict format)
- **`EmbeddingClient`** — wraps `voyageai.AsyncClient`
  - `embed(texts, input_type)` — `voyage-3-large`, 128-item batches → 1024-dim vectors
  - `embed_multimodal(inputs, input_type)` — `voyage-multimodal-3`, 10-item batches → 1024-dim vectors
- **`chunk_document(text, *, target_tokens, overlap_tokens)`** — tiktoken `cl100k_base`; splits on `\n\n` paragraph boundaries, then `.!?` sentence boundaries, then hard-cut; builds overlap by prepending previous chunk tail
- **`chunk_document_with_structure(text, headings)`** — same chunking, each chunk prefixed with nearest ancestor heading
- **`MemoryStore`** — single Qdrant interaction point for all packages; wraps `AsyncQdrantClient`
  - `ensure_collection(name, vector_size=1024)` — idempotent
  - `upsert_points(collection, points)` — embeds text via `EmbeddingClient.embed`, upserts in 100-item batches
  - `upsert_multimodal_points(collection, points, inputs)` — parallel lists; validates lengths match; embeds via `EmbeddingClient.embed_multimodal`, upserts in 100-item batches
  - `upsert_mixed(collection, text_points, mm_points, mm_inputs)` — convenience wrapper; calls both methods; returns `{"text": N, "multimodal": M}`
  - `search(collection, query_text, *, limit, filters)` — text-query search via `embed`
  - `search_multimodal(collection, query_text, query_image_path, *, limit, filters)` — multimodal-query search via `embed_multimodal`
  - `delete_by_source(collection, source_id)` — filter delete on `source_id` payload field
  - Filter helpers: `filter_by_source_type`, `filter_by_domain_tags`, `filter_after`

#### Layer 5 — Reporting

- **`render_run_report(run_id, agent_name)`** — loads JSONL trace, renders Obsidian-compatible Markdown to `$AGENT_REPORTS_VAULT/<agent_name>/<date> <title>.md`; template includes LLM usage by model, tool call counts, memory operations, delegation tree, notable events
- **`notify(title, message)`** — `osascript` on Darwin, no-op elsewhere
- **`notify_budget_threshold(agent, consumption, envelope)`** — fires above 75%
- **`notify_run_complete(agent, run_id, status, cost_usd)`**

---

### yt-intelligence-pipeline

The canonical YouTube ingestion capability. **Status: complete.** Designed to be called both from the CLI and programmatically by agents.

**Two modes of operation:**

| Mode | Output | When to use |
|------|--------|-------------|
| Human | Obsidian `.md` note with summary, takeaways, screenshots | You want to read and annotate the content yourself |
| Agent | Qdrant vector points (text chunks + multimodal screenshot embeddings) | An agent needs to retrieve the content semantically |

Both modes can be combined with `--output both` or `process_video(human_output=True, agent_output=True)`.

**Pipeline steps:**

1. Metadata fetch (yt-dlp)
2. Transcript — YouTube captions primary, local Whisper fallback
3. Cleanup — Claude removes filler, normalizes punctuation
4. Summary — Claude produces summary, key takeaways, Obsidian tags
5. Timestamps — Claude identifies screenshot moments *(screenshots only)*
6. Frame extraction — ffmpeg *(screenshots only)*
7. Output — Obsidian note and/or Qdrant ingestion

**Library API:**
```python
from yt_intelligence_pipeline import process_video, PipelineResult

result = await process_video(
    "https://www.youtube.com/watch?v=...",
    use_screenshots=True,
    human_output=True,
    agent_output=True,
    collection_name="tutorial_research",
)
# result.text_points_upserted, result.multimodal_points_upserted, etc.
```

Sync wrapper: `process_video_sync(url, **kwargs)` — calls `asyncio.run()`.

**CLI:**
```bash
uv run yt-pipeline <url>                     # human mode (default)
uv run yt-pipeline <url> --output agent      # Qdrant only
uv run yt-pipeline <url> --output both       # Obsidian + Qdrant
uv run yt-pipeline <url> --collection my_col # custom collection name
```

**Agent-mode data layout:**
```
~/agent-data/sources/youtube-tutorials/<video_id>/
├── transcript.txt        # cleaned transcript for re-embedding
├── metadata.json         # title, channel, url, tags, source_id
└── screenshots/
    ├── screenshot_001.png
    └── screenshot_002.png
```

**Multimodal graceful degradation:** if `upsert_multimodal_points` raises (e.g., Voyage rate limit), the pipeline logs a warning but does not crash. Text chunks and the Obsidian note are already written; screenshots are already copied to `agent-data`. Re-run with `--output agent` once the issue is resolved.

**Voyage AI rate limits:** free-tier accounts are limited to 3 RPM. Add a payment method at `https://dashboard.voyageai.com/` to unlock standard limits (200M free tokens still apply).

**Qdrant payload schema** for `tutorial_research` points:

| Field | Value |
|---|---|
| `source_type` | `"youtube_tutorial"` |
| `content_type` | `"text"` or `"image_with_caption"` |
| `source_id` | `"youtube:<video_id>"` |
| `image_path` | path in `~/agent-data/...` (multimodal points only) |
| `caption` | screenshot label (multimodal points only) |

---

### tutorial-research

The tutorial research agent. Uses `yt-intelligence-pipeline` as a library to ingest videos, then retrieves relevant content from Qdrant to answer research questions. **Status: under development.**

### music-curation

Music curation agent. **Status: under development.**

---

## Storage Layer (Qdrant)

- Runs locally via Docker Compose on `localhost:6333`
- All vector data lives in `~/agent-data/qdrant/` (bind-mounted in `infrastructure/docker-compose.yml`)
- Collections are created on-demand and named by domain
- Vector size: 1024 dimensions (Voyage AI models)
- Distance: Cosine

Key collections:

| Collection | Content | Created by |
|-----------|---------|------------|
| `tutorial_research` | YouTube tutorial transcripts + screenshots | `yt-intelligence-pipeline` agent mode |

---

## Observability (OTel + Jaeger)

- Jaeger all-in-one runs locally via Docker Compose on `localhost:16686` (UI) / `localhost:4318` (OTLP)
- `init_tracing(service_name)` configures the OTel SDK and returns a `Tracer`
- `@traced` decorator wraps any function; `span()` for manual spans
- Per-event JSONL traces written to `~/agent-data/runs/<date>/<agent>/<run_id>/trace.jsonl`
- Record helpers bridge tracing layer to JSONL via `_current_persister` ContextVar — no explicit passing needed

---

## Agent-to-Agent Delegation

```python
from agent_runtime import register_agent, delegate, BudgetEnvelope

@register_agent("my-agent")
async def handler(request: dict, budget: BudgetEnvelope) -> dict:
    ...

result = await delegate("my-agent", request, parent_envelope, parent_tracker=tracker)
```

The `delegate()` function:
1. Derives a child `BudgetEnvelope` (caps cost/items/time at parent values, decrements depth)
2. Raises `DelegationError` if `max_depth <= 0`
3. Wraps the child in a `BudgetTracker` context (auto-debits parent on completion)
4. Maps outcomes to `DelegationResult` with statuses: `completed`, `partial`, `failed`

---

## Reporting

`render_run_report(run_id, agent_name)` reads the JSONL trace and renders an Obsidian-compatible Markdown report to `$AGENT_REPORTS_VAULT/<agent_name>/<date> <title>.md`. The report includes LLM usage by model, tool call counts, memory operations, and delegation tree.

---

## Testing

All tests run from the workspace root:

```bash
uv run pytest -v                   # full suite (167 tests)
uv run pytest packages/agent-runtime/tests/ -v
uv run pytest packages/yt-intelligence-pipeline/tests/ -v
```

Tests that require Qdrant running on `localhost:6333` are marked with `@requires_qdrant` and skipped automatically if unreachable. No test requires real Voyage or Anthropic API keys.

**Monorepo pytest isolation:** `--import-mode=importlib` is set in the workspace root `pyproject.toml`. Packages do not have `tests/__init__.py` — this prevents namespace collisions when pytest collects from multiple packages.
