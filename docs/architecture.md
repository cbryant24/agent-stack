# Architecture

## Overview

`agent-stack` is a uv workspace containing a shared runtime library and several specialized packages. All packages are installed into a single `.venv` at the workspace root; they share dependencies and import each other as workspace members.

## Packages

### agent-runtime

The shared infrastructure layer. All other packages import from here. **Status: complete.** 184 tests passing.

#### Layer 1 — Config & Models

- **`RuntimeConfig`** (`pydantic-settings`) — reads `.env`, validates required API keys, silently creates `~/agent-data/{sources,runs,qdrant,drafts/user_knowledge}/` and `~/obsidian/agent-reports/` on startup
- **`get_config()` / `reset_config()`** — `lru_cache`'d singleton; `reset_config()` clears it for test isolation
- **Models** — `BudgetEnvelope`, `BudgetConsumption`, `BudgetRemaining`, `DelegationRequest`, `DelegationResult`, `TraceEvent`
- **Exceptions** — `AgentRuntimeError`, `BudgetExhaustedError`, `ConfigurationError`, `DelegationError`

#### Layer 2 — Tracing

- **`@traced`** decorator — handles sync and async, records span attributes from args, captures exceptions
- **`span(name)`** — context manager for manual OTel spans
- **Record helpers** — `record_llm_call`, `record_tool_call`, `record_delegation`, `record_delegation_decision`, `record_memory_query`, `record_memory_write`; all emit OTel span attributes and, if a `TracePersister` is active, append `TraceEvent` JSONL lines. `record_tool_call` additionally bridges to `BudgetTracker.add_tool_call()` via a lazy import (avoiding the circular dependency where `budget.py` imports `record_llm_call` at module level). This means tool calls from any package — including external wrappers like yt-pipeline or Voyage — correctly increment the tracker's `tool_calls` counter. `record_delegation_decision(trigger_type, collection, query, local_max_score, threshold, decision)` (added 2026-05-29, Session 2) emits an `event_type="info"` / `event_subtype="delegation_decision"` `TraceEvent` recording each delegation-trigger check so thresholds can be tuned against real usage; music-curation is its first caller.
- **`TracePersister`** — sync context manager (`__enter__`/`__exit__`); writes `~/agent-data/runs/<date>/<agent>/<run_id>/trace.jsonl` using `threading.Lock`; exposes via `_current_persister` ContextVar so record helpers find it without being passed explicitly
- **`init_tracing(service_name)`** — configures OTLPSpanExporter pointing at `get_config().otel_endpoint`

#### Layer 3 — Budget & Delegation

- **`BudgetTracker`** — async context manager; tracks cost (USD), tool calls, items processed, wall time; raises `BudgetExhaustedError` when any dimension is exceeded; emits summary `TraceEvent` on exit. `check_budget()` should be called at the **start** of each loop iteration (before doing work), not after — calling it after the last `add_item_processed()` would spuriously mark a fully-successful run as `partial`. Accepts optional `time_source: Callable[[], float]` (default: `time.monotonic`) for clock injection in tests.
  - `check_budget()` automatically fires `notify_budget_threshold` the first time usage crosses 75% on any of three dimensions: `max_cost_usd`, `max_items`, `max_wall_time_sec`. Fires once per dimension per run (no repeat). There is no `max_tool_calls` dimension in `BudgetEnvelope`, so tool calls are not threshold-checked.
  - **Resolved (zero-ceiling guard):** the 75% threshold check (`_maybe_notify_threshold`) now short-circuits when a `max_*` ceiling is falsy/`<= 0` instead of computing `current / maximum`, so a `BudgetEnvelope` with any dimension set to `0` no longer raises `ZeroDivisionError` inside `check_budget()` — a `0` ceiling is treated as "no headroom" and the hard checks still raise `BudgetExhaustedError`. Covered by `max_items=0` / `max_cost_usd=0` regression tests.
  - **LLM-cost accounting — agent-author note.** An agent that makes its own LLM calls must route cost through `tracker.add_llm_cost(model, input_tokens, output_tokens)` (which computes cost, increments `consumption.cost_usd` / `consumption.llm_calls`, and calls `record_llm_call` internally). Calling `record_llm_call` directly emits the per-call trace event but does **not** touch the tracker's consumption, so every aggregate read (run-report frontmatter, summary line, LLM-usage total, CLI cost line) shows `$0.0` while the per-model table shows the real cost. music-curation hit exactly this trap (Session 2, Bugs A/C) and fixed it with a `_record_llm` bridge in `chains.py` that routes through the active tracker via the `_current_tracker` ContextVar (mirroring how `record_tool_call` bridges to `add_tool_call`), falling back to a direct `record_llm_call` only when no tracker is active.
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
  - `search(collection, query_text, *, limit, filters)` — text-query search via `embed`; returns `list[SearchResult]` (MemoryPoint schema)
  - `search_multimodal(collection, query_text, query_image_path, *, limit, filters)` — multimodal-query search via `embed_multimodal`
  - `delete_by_source(collection, source_id)` — filter delete on `source_id` payload field
  - Filter helpers: `filter_by_source_type`, `filter_by_domain_tags`, `filter_after`
  - **Low-level surface** (for components with custom payload schemas, e.g. `UserKnowledgeStore`):
    - `embedding_client` (property) — returns shared `EmbeddingClient`
    - `upsert_raw_points(collection, points: list[PointStruct])` — upserts pre-built points without embedding
    - `set_payload(collection, point_id, payload)` — partial payload update without re-embedding
    - `retrieve_points(collection, point_ids)` — fetch by ID; returns raw qdrant `Record` objects
    - `query_by_vector(collection, vector, *, limit, filters)` — search with a pre-computed vector; returns `list[tuple[str, float, dict]]` (point_id, score, payload)
  - **Read-only inspection surface** (used by the orchestrator's diagnose-only vector-DB diagnostics; never writes):
    - `get_collection_info(name)` — structural metadata (status, point/indexed counts, vector size, distance) or `None` if absent
    - `count_points(name, *, filters)` — exact point count
    - `sample_points(name, *, limit, filters)` — sampled `(id, payload)` pairs via `scroll`, payload-only

#### Layer 4b — UserKnowledgeStore

Runtime-owned wrapper around `MemoryStore` that owns the `user_knowledge` Qdrant collection. Holds user-authored, first-party knowledge (verified Suno mechanics, documentation distillations, hand-written experience) across domains. Distinct from `tutorial_research` (third-party video-derived) and from any agent's personal memory collection (e.g. `music_curation_memory`).

**The `user_knowledge` collection is owned by `UserKnowledgeStore`**. Other code may query it (via `UserKnowledgeStore.search()` or directly via `MemoryStore.query_by_vector()`), but must not call `MemoryStore.upsert_points()` or `upsert_raw_points()` against it — those paths bypass the draft/confirm workflow and schema contract.

**Payload schema** for `user_knowledge` points:

| Field | Type | Notes |
|---|---|---|
| `statement` | str | The fact/assertion; also the vector source text |
| `domain` | str | e.g. `suno_mechanics`, `elevenlabs_mechanics`, `music_theory`, `voiceover`, `general` |
| `topic_tags` | list[str] | e.g. `["style_field", "copyright_filter"]` |
| `source_type` | str | `user_verified`, `documentation`, `forum_distilled`, `manual` |
| `source_ref` | str \| None | URL, doc citation, or `file://...` for seed-loaded entries |
| `examples` | list[str] | Optional concrete examples |
| `created_at` | str (ISO) | UTC |
| `updated_at` | str (ISO) | UTC |
| `confidence` | str | `high`, `medium`, `low` |
| `superseded_by` | str | `""` = active; UUID string = replaced by that entry |
| `entry_id` | str | UUID, used as Qdrant point ID |

**Public API:**

- `__init__(memory_store, collection_name="user_knowledge")` — composes MemoryStore; optional `collection_name` for test isolation
- `await ensure_collection()` — idempotent, 1024-dim cosine
- `await propose_entry(statement, domain, source_type, *, ...)` → `Draft` — persists draft to `~/agent-data/drafts/user_knowledge/<draft_id>.json`; no Qdrant write
- `await confirm_entry(draft_id)` → `str` (entry_id) — embeds, upserts, deletes draft
- `await reject_entry(draft_id)` — deletes draft; raises `FileNotFoundError` if not found
- `await list_drafts()` → `list[Draft]` — returns active drafts; prunes files older than 7 days; skips corrupt files with a warning (preserves them for inspection)
- `await bulk_load_verified(entries, source_ref)` → `list[str]` — `source_ref` required; no propose/confirm cycle; returns entry_ids
- `await search(query, *, domain, current_only, limit, confidence_min)` → `list[KnowledgeHit]`
- `await supersede(old_entry_id, new_statement, **fields)` → `str` (new entry_id) — writes new entry, links old via `superseded_by`
- `await get_entry(entry_id)` → `KnowledgeEntry | None` — direct fetch including superseded entries

**Exported types:** `UserKnowledgeStore`, `Draft`, `KnowledgeEntry`, `KnowledgeHit` — all available from `agent_runtime`.

**Draft persistence:** `~/agent-data/drafts/user_knowledge/<draft_id>.json`; 7-day expiry enforced lazily by `list_drafts()`.

#### Layer 4c — Shared docs-ingest mechanism

`agent_runtime.knowledge.docs_ingest` — `ingest_docs(folder, *, domain, ...)` / `ingest_docs_sync`. A domain-agnostic, no-LLM flow for turning a folder of local markdown docs into verified `user_knowledge` entries: each `##`+ heading becomes a candidate (`statement` = body, `topic_tags` = heading hierarchy, `source_ref` = `file://` or a frontmatter `url`), confirmed at end of run via a y/n/edit/defer pass, then loaded through `UserKnowledgeStore.bulk_load_verified` under the caller-supplied `domain` (`source_type="documentation"`, `confidence="high"` by default). The **`domain` tag and the source folder are the only domain-specific inputs**; everything else is generic. The docs folder is the durable queue — deferred/skipped sections reappear on the next run — and a re-run dedups against existing active entries keyed on `source_ref + topic_tags + statement` (`bulk_load_verified` itself is not idempotent).

Promoted to the runtime once a second consumer appeared: **voiceover-direction's `knowledge ingest-docs` command calls this** (a behavior-preserving refactor — its CLI is unchanged), and visual-generation uses it for ComfyUI/RunPod docs. The deferred `--decisions` / `--url` refinements, now that the flow is shared, land here once for every agent.

#### Layer 5 — Reporting

- **`render_run_report(run_id, agent_name)`** — loads JSONL trace, renders Obsidian-compatible Markdown to `$AGENT_REPORTS_VAULT/<agent_name>/<date> <title>.md`; template includes LLM usage by model, tool call counts, memory operations, delegation tree, notable events
- **`notify(title, message)`** — `osascript` on Darwin, no-op elsewhere
- **`notify_budget_threshold(agent, consumption, envelope)`** — fires above 75%
- **`notify_run_complete(agent, run_id, status, cost_usd)`**

#### Layer 6 — Schema migrations *(planned, not built)*

A runtime-owned, domain-agnostic migration runner versioning structural and data changes across both Qdrant and the relational checkpointer. Applied migrations are recorded in a single SQLite ledger (`~/agent-data/agent-stack.db`, table `schema_migrations`), tagged by target store. Migrations are per-package and runner-discovered with timestamp-prefixed IDs for deterministic global ordering; cross-cutting ones (the `0001_baseline`, `user_knowledge`) live in `agent-runtime`. The baseline wraps the existing `ensure_collection` calls rather than replacing them — a fresh environment runs it to reach current structure, while the already-populated DB is stamped as applied. Forward-only, idempotent (no cross-store atomicity), explicit CLI (`migrate status | up | stamp`) with no startup auto-apply. Full design and rationale: the "Schema migrations (planned)" section of `ai-director-agent-system.md`.

The `~/agent-data/agent-stack.db` file already exists: the orchestrator's checkpointer creates and uses it via LangGraph's own `AsyncSqliteSaver.setup()` (managing its `checkpoints`/`writes` tables), called at startup. That is the library managing its own tables — **independent of** this (unbuilt) migration runner, which will add a `schema_migrations` table to the same file when built.

---

### yt-intelligence-pipeline

The canonical YouTube ingestion capability. **Status: complete.** 45 tests passing. Designed to be called both from the CLI and programmatically by agents.

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
| `source_type` | `"youtube_tutorial"` (video chunks) or `"course_doc"` (course-doc chunks) |
| `content_type` | `"text"` or `"image_with_caption"` |
| `source_id` | `"youtube:<video_id>"` |
| `image_path` | path in `~/agent-data/...` (multimodal points only) |
| `caption` | screenshot label (multimodal points only) |

---

### tutorial-research

The tutorial research agent. Uses `yt-intelligence-pipeline` as a library to ingest videos, then retrieves relevant content from Qdrant to answer research questions. **Status: complete; course-doc bulk ingest (`ingest-docs`) added.** 58 tests passing.

#### Request modes

Mode is inferred from the request string (`classify_request()`) or set explicitly via `request_type=`:

| Mode | Trigger | Pipeline |
|------|---------|----------|
| `research` | Default | Tavily → Haiku scoring → `process_video` × N → retrieve → Sonnet synthesis |
| `ingest` | URL in request | Skips Tavily; fetches metadata → scores → ingests URLs directly |
| `retrieve` | "find", "show me what", etc. | Qdrant retrieval only; no ingestion |

#### Pipeline stages (research mode)

1. **Discovery** — `search_for_tutorials(topic, max_results=20)` — Tavily web search filtered to `youtube.com/watch` URLs. On failure, degrades gracefully to retrieve-only (emits `event_subtype="tavily_degradation"` TraceEvent).
2. **Metadata filter** — `fetch_video_metadata(url) → CandidateEntry | None` — yt-dlp fetch. Drops only: fetch failure (private/deleted/unavailable/region-locked), `is_live`/`was_live`, members-only/paywalled. No view count threshold. `has_captions` is informational only (yt-intelligence-pipeline has local Whisper fallback).
3. **Scoring** — `score_candidates(topic, candidates, tracker, client) → list[ScoredCandidate]` — Haiku 4.5 via tool-use, one call per candidate. Scores 1–5 on topical fit; `has_captions` as soft tiebreaker only. Emits `event_subtype="candidate_scoring"` TraceEvent.
4. **Ingestion plan** — top-N candidates (≤ `max_items`) sorted by score. `estimated_cost_usd` is informational. Emits `event_subtype="ingestion_plan"` TraceEvent.
5. **Ingestion** — `process_video(url, human_output=False, agent_output=True, collection_name=...)` for each selected candidate. `check_budget()` runs at the top of each iteration (before calling `process_video`) so the loop exits cleanly when the budget is reached without falsely marking the run partial. Non-budget exceptions log a warning and continue; if fewer items are ingested than `plan.estimated_items`, the run is marked `partial` after the loop.
6. **Coverage assessment** — after post-ingestion retrieval, emits `event_subtype="coverage_assessment"` TraceEvent with labels `empty / sparse / thin / adequate` (thresholds: sparse < 0.55 max score; thin ≤ 2 distinct sources). Appended to the Obsidian run report as a "## Coverage Assessment" section.
7. **Retrieval** — `RetrievedChunk` carries `score`, `source_id`, `content`, `source_title`, `source_url`, `chunk_index`, and `collection_name`. Both `tutorial_research` and `user_knowledge` are queried in parallel via `asyncio.gather`. `user_knowledge` hits receive a 1.25× score multiplier (`USER_KNOWLEDGE_SCORE_MULTIPLIER`) and are capped at 30% of the requested limit. If the `user_knowledge` collection is absent or Qdrant is unreachable, that leg degrades silently to empty. Retrieved chunks are appended to the run report in separate "## Retrieved Content — Tutorial Research" and "## Retrieved Content — User Knowledge" sections when both are present. Retrieval over `tutorial_research` filters `source_type ∈ {youtube_tutorial, course_doc}` (`MatchAny`), so video-derived and course-derived chunks surface together (and reach `visual-generation explain`, which already filters nothing).
8. **Synthesis** — Sonnet 4.6 synthesis with source attribution, capped at `MAX_SYNTHESIS_TOKENS` (8192) output tokens. Default on for `research` mode; off for `ingest` and `retrieve`. The cap matches Sonnet 4.6's output ceiling to prevent mid-sentence truncation. The synthesis system prompt instructs Sonnet to treat `[USER-KNOWLEDGE: ...]`-prefixed chunks as authoritative (prefer over tutorial chunks on conflict) and cite them with provenance-aware language ("per the user's verified notes" / "per verified knowledge").

#### Run lifecycle

```python
async with BudgetTracker(effective_budget, "tutorial-research") as tracker:
    tracker_ref = tracker
    run_id = tracker.run_id
    # ... mode-specific work ...
except BudgetExhaustedError:
    status = "partial"

# Partial guard: silent process_video failures produce fewer ingested items than planned
if status == "completed" and not dry_run and plan and len(ingested) < plan.estimated_items:
    status = "partial"

# Always after context exit — trace is finalized
snap = tracker_ref._consumption
report_path = render_run_report(run_id, "tutorial-research")
_append_coverage_to_report(run_id, "tutorial-research", report_path)
if retrieved:
    _append_retrieved_to_report(report_path, retrieved)
notify_run_complete("tutorial-research", run_id, status, cost_usd)
```

Stats (`cost_usd`, `items_processed`, `wall_time_sec`) are read from `tracker_ref._consumption` after the context exits so they're accurate even on partial runs.

#### Library API

```python
from tutorial_research import research, research_sync, ResearchResult

result = research_sync("python asyncio patterns")
result = research_sync("python asyncio patterns", synthesize=False, dry_run=True)
```

#### CLI

The CLI is a `click.group()` — the old bare `tutorial-research "<query>"` form was dropped (nothing imports it programmatically; a bare positional and subcommands can't coexist). Research now lives under the `research` subcommand:

```bash
uv run tutorial-research research "python asyncio patterns"
uv run tutorial-research research "python asyncio patterns" --type retrieve --no-synthesize
uv run tutorial-research ingest-docs <folder> [--course "<frontmatter course>"] [--dry-run] [--yes]
```

#### Course-doc bulk ingest (`ingest-docs`)

The document analogue of video ingestion: `ingest-docs <folder>` turns each kept H2 section of a course markdown note into one `MemoryPoint` (`source_type="course_doc"`, `content_type="text"`) in the `tutorial_research` collection — so course material is retrievable alongside the YouTube-derived chunks and by `visual-generation explain`. A file is ingested only if its frontmatter `course` matches `--course` (default `DIFFUSION_MASTERY_COURSE`); within a file only the keep-set H2s are taken (Quick Review / Key Concepts / Practical Applications / Important Details), empty bodies skipped. `source_id` is `course:diffusion-mastery/<file-stem>` (stems are unique where lecture titles collide). Re-runs are idempotent — a scroll skips chunks already present under that `source_id` (keyed on `topic_tags` + text), so re-ingesting the folder writes zero. Embeds via Voyage inside `upsert_points`, so the store must be reachable (run under `op run` for the keys). Course docs are tutorial-derived **technique** — deliberately not `user_knowledge` (platform facts) or `technique_lesson` (learned-by-doing).

#### Model constants

| Constant | Value | Used for |
|---|---|---|
| `MODEL_SCORER` | `claude-haiku-4-5` | Candidate scoring (tool-use) |
| `MODEL_SYNTHESIZER` | `claude-sonnet-4-6` | Research synthesis |
| `MAX_SYNTHESIS_TOKENS` | `8192` | Output token ceiling for synthesis calls (Sonnet 4.6 max); scoring calls are not affected |

#### Default budget

```
max_items=5, max_depth=0, max_cost_usd=2.00, max_wall_time_sec=900
```

#### Known runtime gaps (follow-ups)

**Anthropic client construction — all agents:** `pydantic-settings` loads `.env` into config fields but does **not** inject values into `os.environ`. The Anthropic SDK (`AsyncAnthropic()`) reads `os.environ` directly, so calling `AsyncAnthropic()` with no arguments will fail to authenticate even when the key is set in `.env`. Every agent package must construct the client as:

```python
from agent_runtime.config import get_config
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=get_config().anthropic_api_key)
```

The same applies to any other SDK that reads credentials from `os.environ` (Tavily, Voyage AI, etc.) — check their constructors and pass the key explicitly from `get_config()` rather than relying on environment variable injection.

### music-curation

Music curation agent. **Status: complete.** 214 tests passing.

A music-theory expert and creative partner with persistent memory, helping craft Suno prompts grounded in real musical understanding.

#### Where the music-creation domain knowledge lives

There is intentionally **no static "music-creation" reference doc.** The domain expertise the agent reasons over is curated into queryable stores and the generation prompt, not hardcoded into Markdown, so it stays current as the user's taste and Suno itself evolve. If you're looking for "the music knowledge," it lives in four places:

- **`user_knowledge`** (`domain=suno_mechanics`) — verified, first-party Suno-mechanics facts (character limits, vocal-control syntax, copyright-filter behavior, etc.). Authoritative; boosted on retrieval.
- **`music_curation_memory`** — the user's taste lessons, prior generations (prompt → reaction → outcome), templates, and sound references.
- **`tutorial_research`** — third-party music-theory and Suno-feature knowledge (chord progressions, genre conventions, mixing), refreshed by delegating to tutorial-research.
- **The generation system prompt** (`music_curation/chains.py`) — the baseline music-theory expertise and Suno prompt-construction rules the model always carries.

The user's own hand-written domain reference (`seed/music-curation/AI-Music-Generation-README.md`) is an *input* to this system — it is ingested into the stores above, not maintained as a parallel doc. A docs/ copy would drift from both the seed file and live memory, which is the exact failure mode the "curated, not hardcoded" design avoids.

#### Collections

- **`music_curation_memory`** — owned by music-curation, 1024-dim cosine. Holds four memory types discriminated by `memory_type` payload field:
  - `generation` — prior Suno prompt entries with reactions and evolution chains
  - `template` — reusable parameterized prompt scaffolds
  - `taste` — confirmed user taste lessons
  - `sound_reference` — verbal descriptions of specific sounds

#### Data models (`music_curation/models.py`)

- **`Generation`** — embed target: `style_field`. Payload: `lyrics_field`, `reaction` (pending/loved/liked/liked_with_changes/disliked/prompt_failed/copyright_blocked/never_ran/lost_track), `status` (pending/complete), `session_id`, `chain_root_id`, `parent_id`, `bpm`, `language`, `suggested_track_title`, `change_summary`, `goal`, `rating` (optional 1-5), `notes` (action-oriented), `context` (reasoning-oriented). `disliked` = Suno rendered correctly but not to taste (aesthetic); `prompt_failed` = Suno didn't render the prompt's intent (prompt-engineering issue). The `notes` field was previously `user_note`: legacy entries written before this change carry `user_note` in their payload, and `from_payload` maps it to `notes` transparently on read (only when `notes` is absent). Writes always emit `notes`. **This dual-key read is intentional and permanent — not a transitional state**; there is no migration, because writes already converged on `notes` and the read shim costs nothing.
- **`Template`** — embed target: `descriptor`. Payload: `style_pattern`, `swap_variables`, `domain_tags`.
- **`TasteLesson`** — embed target: `statement`. Payload: `valence` (positive/negative), `scope` (genre/production/instrumentation/vocal/arrangement/general), `confirmed`. The `arrangement` scope holds standing **length / song-structure / section-layout** preferences (e.g. "compact ~2 min blues, single verse"); it is applied as a default when a request is silent on length or structure. `parser._infer_taste_scope` routes length/structure keywords (length, duration, minute, section, verse, chorus, intro, outro, bridge, hook) to it during seed ingestion.
- **`SoundReference`** — embed target: `description`. Payload: `source_track`, `qualities`, `linked_generation_ids`, `linked_suno_tags`.
- **`SunoPrompt`** — output type: `style_field` (validated ≤ 1000 chars, truncated on output), `lyrics_field`.
- **`MusicResult`** — returned by `curate()`: `prompts: list[SunoPrompt]`, `theory_reasoning`, `cross_references: list[GenerationRef]`, `generation_ids`, `run_id`, `status`, `cost_usd`, `items_processed`, `wall_time_sec`, `report_path`.

#### MusicCurationStore (`music_curation/store.py`)

Wraps `MemoryStore`; all four memory types share `music_curation_memory`, discriminated by `memory_type` filter on search.

Key methods: `upsert_generation`, `upsert_generations_bulk`, `upsert_template`, `upsert_templates_bulk`, `upsert_taste`, `upsert_taste_bulk`, `upsert_sound_ref`, `update_generation_reaction` (no re-embed), `search_generations(*, exclude_pending=True)`, `search_taste(*, confirmed_only=True)`, `search_templates`, `search_sound_refs`, `list_pending`, `get_chain(chain_root_id)`, `to_generation_ref`.

#### Retrieval (`music_curation/retrieval.py`)

`retrieve_context(query, curation_store, memory_store, ...)` runs parallel `asyncio.gather` across music_curation_memory (generations, taste, templates), user_knowledge (suno_mechanics, 1.25× score boost), and tutorial_research. Returns `RetrievedContext` with typed buckets. Degrades silently on per-collection failures. `build_context_prompt(ctx)` formats typed buckets with source prefixes (`[PRIOR GENERATION: reaction=LOVED, rating=5, context="..."]`, `[USER FACT: suno_mechanics]`, `[TUTORIAL KNOWLEDGE]`, `[TASTE: positive/genre]`) for injection into the generation system prompt.

**Rating tiebreaker.** Prior generations are ordered by similarity score first; `rating` (1-5) breaks ties within equal-score matches, so a `loved + rating=5` outranks a `loved + rating=3` on an otherwise equal match. Similarity always dominates — rating only reorders exact ties.

**`prompt_failed` vs `disliked` in retrieval.** These two negative reactions are treated differently when a prior generation surfaces for a similar future request. `disliked` (Suno rendered the prompt accurately, the user rejects the aesthetic) weighs against the *territory* — the model should read it as "avoid this direction." `prompt_failed` (Suno mis-rendered the prompt's intent) does **not** weigh against the territory: `build_context_prompt` annotates the block with an explicit note that the territory is still open and the prior prompt is a *structure to learn from*, not a direction to avoid. This keeps a prompt-engineering miss from being mistaken for taste feedback. The distinction lives entirely in the formatted-context annotation; no separate scoring penalty is applied.

**`notes` vs `context` in formatting.** A generation's `context` (reasoning — *why* the user reacted) is included in the formatted prior-generation block so the model sees the user's reasoning. Its `notes` (action — *what to change next time*) is **not** included in standing retrieval context; notes inform iteration from a specific prior (reserved for the Group-B `--continue` / `--iterate-from` flows, not yet implemented), not general pattern-matching.

#### Generation chain (`music_curation/chains.py`)

- `generate_prompts(request, ctx, client)` → `(list[SunoPrompt], theory_reasoning, suggested_titles)` — Sonnet 4.6, JSON output, 4096 output tokens.
- **Length & structure control (system prompt).** Suno exposes no duration parameter — length is an emergent property of the lyrics field. `_SYSTEM_PROMPT` carries an explicit length→structure mapping (~1–1.5 min ≈ intro+verse+chorus; ~2 min ≈ intro+verse+chorus+verse/chorus+outro; ~3 min ≈ two cycles + bridge) so a stated target is translated into a concrete section count instead of being dropped, and instructs the model to reproduce an explicitly listed section structure exactly (no added/dropped/reordered sections). **Request-over-context precedence:** an explicit request dimension (length, structure, key, BPM, language, instrumentation) overrides a conflicting retrieved template or prior generation — framed as precedence, not an exception, so a one-off spec never has to fight or pollute retrieval. Retrieved entries (including `[TASTE: .../arrangement]`) act as defaults only for dimensions the request leaves open. This closed the gap where requests like "around 2 minutes / one intro-chorus-verse-chorus-outro" were silently dropped and an extra verse was generated.
- `check_for_question(request, ctx, client)` — one targeted clarifying question if it would materially change output; returns `None` to proceed without asking.
- `DelegationTrigger.check(request, ctx)` → `"local"`, `"retrieve"`, or `"ingest"` — concrete trigger conditions (suno feature, music-theory why-question, artist reference) checked against thresholds in `constants.py`. Each decision emits a `record_delegation_decision` trace event with `local_max_score`, `threshold`, and `decision` for post-hoc tuning.

#### Delegation thresholds

Defined in `constants.py` as `DELEGATION_SUNO_FEATURE_THRESHOLD = 0.70`, `DELEGATION_MUSIC_THEORY_THRESHOLD = 0.65`, `DELEGATION_ARTIST_REF_THRESHOLD = 0.50`. These are unvalidated starting values; see the comment block in constants.py for tuning guidance.

#### Seed ingestion (`music_curation/parser.py`, `music_curation/seed_ingestion.py`)

`parse_file(path)` handles both the README (taste + suno_facts + explicit templates) and session files (generations + inferred taste + inferred templates). Handles three prompt-section layouts: flat code blocks, H3 sub-field (file 1 style), and H4 recursion (file 7 style). Reaction detection checks `**Status:** ✅/❌/⚠️` fields, inline emoji, text phrases, and section-level framing. Evolution chains inferred from "Iteration N" heading patterns and explicit "Key Changes from Version N" references.

`ingest_seed(path, *, dry_run, auto_confirm)` orchestrates confirmation: suno_facts → bulk confirm; explicit taste/templates → auto-write; inferred taste → individual y/n/edit/defer; inferred templates → single y/n. Deferred taste queued to `~/agent-data/drafts/music-curation/taste-pending/` for `music-curation seed review-taste`.

#### CLI subcommands

```bash
music-curation generate "<request>" [--skip-question] [--dry-run] [--max-cost N]
music-curation report <gen_id> --reaction <X> [--rating 1-5] [--notes "..."] [--context "..."]
music-curation review-pending
music-curation recall "<query>" [--limit N]
music-curation taste add "<lesson>" --valence <pos|neg> --scope <genre|...>
music-curation fact add "<statement>" [--domain suno_mechanics]
music-curation chain show <chain_root_id>
music-curation seed ingest <path> [--dry-run] [--yes]
music-curation seed review-taste
```

#### Default budget

```
max_items=1, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300
```

`max_depth=2` allows music-curation → tutorial-research → further delegation.

#### Known runtime additions (Session 2 of music-curation arc, 2026-05-29)

- `record_delegation_decision(trigger_type, collection, query, local_max_score, threshold, decision)` added to `agent_runtime.tracing` — records delegation trigger decisions as `event_type="info"` / `event_subtype="delegation_decision"` TraceEvents for post-hoc threshold tuning.

---

### voiceover-direction

ElevenLabs voiceover director. **Status: Phase 2 complete (MVP).** 145 tests passing.

A director for voice work that inverts music-curation's cost structure: *direction* (choosing
text, emotion tags, voice, pacing) is free LLM iteration, while *generation* (the ElevenLabs
TTS call) burns a scarce monthly character budget. The turn is **direct freely until the
direction is settled, then spend characters on generation as a deliberate commitment**;
iteration lives in direction, never in generation. The lifecycle is split — `generate` writes
audio + a `pending` take and exits; the user listens, then `report`s a reaction.

#### Two orthogonal budgets

The per-run Claude cost (for `direct` and the `generate` re-direction fold-in) stays in
agent-runtime's `BudgetEnvelope`. The **monthly ElevenLabs character budget never enters
`BudgetEnvelope`** — it is queried from the vendor at generation time (source of truth, not a
local counter that drifts when you also generate in the ElevenLabs UI), displayed at a
**soft-inform** gate, and recorded only as a span attribute (`elevenlabs.characters_consumed`).
ElevenLabs already hard-enforces the quota, so the agent informs rather than gatekeeps.

#### Collection & memory model

`voiceover_direction_memory` (1024-dim cosine), two memory types discriminated by `memory_type`:

- **`take`** — embed target: the section text sent to ElevenLabs. Payload: `voice_id`, `model`,
  `settings` (model-agnostic dict), `emotion_tags`, `character_count`, `audio_path` (relative to
  `agent_data_dir`, portable), `reaction`, `rating`, `status` (pending/complete, derived),
  `section_id`, `project_id`, `domain`, `parent_take_id`, `chain_root_id`. Lineage is
  **section-scoped** (music-curation's chain concept reshaped per section).
- **`direction_lesson`** — embed target: the statement. Payload: `valence` (positive/negative),
  `scope` (voice/pacing/tone/general), `confirmed`.

The **voice registry** is *not* a vector type: a local JSON file
(`<agent_data_dir>/voiceover/voices.json`) rewritten wholesale on each `voice sync`. Voices are
enumerated/looked-up by `voice_id`, never semantically searched. **ElevenLabs mechanics facts**
live in the runtime-owned `user_knowledge` collection (`domain=elevenlabs_mechanics`).

#### Reaction vocabulary (`constants.py`)

`loved`, `liked`, `liked_with_changes`, `disliked`, `render_failed` (a take is born `pending`).
The load-bearing distinction adapts music-curation's `disliked`/`prompt_failed` split to TTS:

- **`disliked`** — ElevenLabs rendered the direction faithfully, but the result isn't to taste
  (aesthetic). Weighs **against** the direction/territory.
- **`render_failed`** — ElevenLabs did **not** render the intent (tags ignored, mispronunciation,
  wrong emphasis). The direction was fine, the territory stays **open**, and the prior take
  surfaces as structure to learn from.

Dropped from music-curation (don't apply to TTS — a take always has saved audio):
`copyright_blocked`, `never_ran`, `lost_track`. `rating` (1–5) is meaningful only for the
positive reactions.

#### Retrieval (`retrieval.py`)

`retrieve_context(query, store, memory_store, ...)` composes three collections in parallel via
`asyncio.gather`: `voiceover_direction_memory` (prior takes, exclude-pending; direction lessons),
`user_knowledge` (`domain=elevenlabs_mechanics`, 1.25× score boost — `USER_KNOWLEDGE_SCORE_MULTIPLIER`),
and `tutorial_research`. Each leg degrades silently to an empty bucket, so `direct` stays useful
from a cold start with every collection empty. Mirrors music-curation's composition.

#### Direction (`agent.py`, `chains.py`)

`direct` parses the input script (sections split at the shallowest heading level present, so
`#`- and `##`-headed scripts both work; deeper headings stay in the body; regex/heuristic — no
LLM extraction), composes retrieval, runs the whole-script direction chain (Sonnet 4.6, `MODEL_DIRECTOR`,
`MAX_DIRECTION_TOKENS=8192` — every section in one pass), and writes an **editable
directed-script file**. Direction never triggers research inline (it would break the fast free
loop). LLM-only: no ElevenLabs call, no character spend, free and re-runnable.

**Directed-script format** (`directed_script.py`): markdown with headings preserved (section
identity), audio tags literal inline in the prose, and per-section metadata in invisible
HTML-comment JSON so the arbitrary `settings` dict round-trips losslessly. Load-bearing
invariant: `read_directed_script(write_directed_script(s)) == s`. The `section_id` is carried
in the per-section metadata, so the round-trip is exact even for duplicate headings.

#### Generation (`generation.py`)

Split into two phases so the soft-inform gate can show the *revised* markup before any spend:

1. **`plan_generation`** — resolves each target section to the exact text that will be spoken.
   If a section's last take carries a `report` note (and not `--raw`), the note is folded into a
   **section-scoped re-direction** (a Claude call from the last take — option B, the compounding
   chain) and the revised markup is shown. This phase carries the Claude cost, guarded by
   `GENERATE_BUDGET`'s cost cap.
2. **`spend_generation`** — drives the resolved plan: TTS → audio file + a `pending` take per
   section. No LLM call; the character spend is recorded only as a span attribute, never in the
   budget.

The CLI runs plan → interactive gate → spend; `generate` is a prompt-free combined entry (plan +
auto-spend) for library use. `--raw` skips the fold-in and speaks the file's markup verbatim
(the hand-edit branch).

#### ElevenLabs client (`elevenlabs_client.py`) — stability mode→float at the boundary

`ElevenLabsClient` wraps the official async SDK. `list_voices()` and `get_usage()` are read-only
(vendor is source of truth; nothing cached); `synthesize()` is the paid TTS call.

`eleven_v3` expresses stability as a discrete **mode** (`creative`/`natural`/`robust`), which the
direction chain emits and the directed-script `settings` dict carries — but the API's
`voice_settings.stability` is a **float** (0.0–1.0): lower = broader emotional range, higher =
more consistent/monotonous. The client translates the mode to its float **at the vendor boundary
only** (`_normalise_stability`): `creative → 0.0`, `natural → 0.5`, `robust → 1.0`. A numeric
stability passes through unchanged (v2-style settings stay valid); an unknown mode string raises a
clear `ValueError` naming the valid modes rather than re-triggering the opaque 422 the SDK returns
for a non-numeric stability. The chain output and directed-script format are unchanged — only the
adapter coerces. (Mapping confirmed against the ElevenLabs Python SDK `VoiceSettings` docs.)

#### CLI subcommands

```bash
voiceover-direction direct <script.md> [-o out] [--project-id ID] [--domain D] [--max-cost N] [--dry-run]
voiceover-direction generate <script.directed.md> (--section <id> | --all) [--raw] [-y] [--max-cost N]
voiceover-direction report <take_id> --reaction <X> [--rating 1-5] [--notes ...] [--context ...]
voiceover-direction review-pending
voiceover-direction recall "<query>" [--limit N]
voiceover-direction lesson add "<statement>" [--valence ...] [--scope ...]
voiceover-direction fact add "<statement>" [--domain elevenlabs_mechanics] [--confidence ...]
voiceover-direction knowledge ingest-docs <folder> [--dry-run] [--yes]
voiceover-direction voice sync
```

`knowledge ingest-docs` mirrors music-curation's seed-ingest pattern applied to local ElevenLabs
docs: each `##`+ heading becomes a candidate (heading hierarchy → `topic_tags`, body →
`statement`), confirmed via y/n/edit/defer (no LLM), loaded through `bulk_load_verified`
(`domain=elevenlabs_mechanics`, `source_type=documentation`, `confidence=high`, `source_ref`
`file://` or `url://` from frontmatter). The docs folder is the durable queue (deferred/skipped
sections reappear next run); a re-run dedups against existing entries keyed on
source_ref + topic_tags + statement.

#### Library API

```python
from voiceover_direction import (
    direct, direct_sync, generate, generate_sync,
    plan_generation, spend_generation, read_directed_script, write_directed_script,
)

result = direct_sync("script.md")                                  # DirectionResult
result = generate_sync("script.directed.md", all_sections=True)    # GenerationResult (plan + auto-spend)
```

#### Default budgets (`constants.py`)

```
DEFAULT_BUDGET  (direct):    max_items=1,    max_depth=1, max_cost_usd=1.50, max_wall_time_sec=300
GENERATE_BUDGET (generate):  max_items=None, max_depth=0, max_cost_usd=2.00, max_wall_time_sec=600
```

`GENERATE_BUDGET` has no item cap (a `--all` run processes many sections); the real limiter on
spend is the vendor character quota, which is orthogonal and never in the envelope. The cost cap
guards the option-B re-direction Claude path.

---

### concept-script

Structural/craft scriptwriting collaborator. **Status: Phase 2 complete (MVP).** 45 tests passing.

Turns sparse creative seeds or a verbatim dictation transcript into a single editable `script.md`
that `voiceover-direction direct` consumes unchanged. It proposes craft scaffolding (section
breakdown, pacing, an emotional arc, candidate per-section emotion direction) and **surfaces, never
decides** the creative core — the user owns every decision by editing the file. The load-bearing
claim: v1's output **is** the Voiceover-Direction-ready script, not an abstract brief adapted later.

#### Stateless by design — no collection

concept-script owns **no Qdrant collection** and writes no memory. The `report --reaction` feedback
loop that earns a collection for music-curation/voiceover-direction does not exist here (brief
quality only surfaces many steps downstream and attribution back is muddy), so a collection would be
storage without a learning mechanism. Prior work is reused via file reference (`--ref @prior-script.md`),
since outputs are files. Reading `user_knowledge` / `tutorial_research` to fill a gap is deferred (see
`docs/v2-refinements/concept-script-v2-refinements.md`). The only side effect of a run is writing the script file;
runtime wiring (budget, tracing, run report) mirrors the rest of the stack minus the stateful parts.

#### Two modes → one artifact (`agent.py`, `chains.py`)

- **`draft` (generative)** — `generate_brief(seeds, client, prior_script=...)` takes sparse seeds
  (theme, mood, duration or a musical reference implying it, stylistic references, project type) plus
  an optional prior-script reference, and asks Sonnet 4.6 (JSON) for a `VideoBrief`.
- **`shape` (curation)** — `shape_brief(transcript, client, *, clean=False)` resolves an in-band
  command channel inside a verbatim dictation transcript (see below) and returns a `VideoBrief`
  plus a cut trailer.

Both share `_record_llm` (the cost-routing bridge through the active `BudgetTracker`, same pattern as
music-curation) and a JSON→`VideoBrief` validator. `MODEL = claude-sonnet-4-6`, `MAX_TOKENS = 8192`.

#### Curation command channel (`shape`)

The dictation tool captures verbatim; `_shape_system(clean)` builds the system prompt that resolves
the channel across four distinct categories. (1) Strip disfluencies (uh/um/dead-air/false starts).
(2) Self-corrections ("no actually it was more like…", "I'm wrong about that…"): **preserved
verbatim by default** as content — authentic texture the voiceover agent narrates — and this is the
**only** category the `clean` flag affects (`clean=True` resolves them into final prose: keep the
corrected version, drop the abandoned phrasing). (3) The **`director note` wake phrase** — the one
deliberate edit signal, legitimate because it originates in the user's own dictation — is executed
and removed (phrase + instruction). A note can be a single deletion, a global/repeated change, a
replacement, or a reorder; the prompt mandates one `cuts` entry per executed note (a global change
is one summarizing entry), so the trailer is reliable even for transform-style notes. (4) Sectioning
+ inline emotion direction. Categories 1, 3, 4 are identical regardless of `clean`. Every executed
cut lands in `VideoBrief.cut_trailer`; a deterministic safety net logs a warning if the wake phrase
is present in the transcript but no cut was recorded. Provenance rule: nothing other than a
`director note` is ever treated as a command.

#### The script.md format (`models.py`, `serialize.py`)

`VideoBrief(logline, sections: list[BriefSection(heading, prose)], music_hint, cut_trailer)` serializes
via `to_script_md`. The format is dictated by the consumer, `voiceover_direction.parser.parse_script_text`:

- **Each section is an H1.** The voiceover parser splits at the shallowest heading level present and
  slugifies the heading into the `section_id`; concept-script never authors ids.
- **Emotion direction is inline** as literal ElevenLabs-style `[tag]`s in the prose (no separate
  field) — the parser passes them through and `direct` refines them.
- **The logline, optional `Music:` hint, and the cut trailer (an HTML comment) all live in the
  preamble before the first `#`.** The voiceover parser skips everything before the first heading
  (logging a harmless warning), so none of it leaks into narration. This is the invariant that makes
  the file "consumed unchanged." Verified end-to-end by `tests/test_integration.py`, which feeds
  serialized output through the real voiceover parser.

`from_script_md` is a best-effort inverse used for round-trip tests and re-reads.

#### CLI (`cli.py`)

```bash
concept-script draft --seeds seeds.md [--ref prior-script.md] [-o script.md] [--max-cost N] [--dry-run]
concept-script draft "inline seed text" [-o script.md]
concept-script shape transcript.txt [-o script.md] [--clean] [--max-cost N] [--dry-run]
```

#### Library API

```python
from concept_script import draft, draft_sync, shape, shape_sync, ConceptResult

result = draft_sync("focus, calm, ~2 min", prior_script=None)   # ConceptResult (.script_path, .brief, ...)
result = shape_sync(open("transcript.txt").read())              # preserve self-corrections (default)
result = shape_sync(open("transcript.txt").read(), clean=True)  # resolve them into final prose
```

#### Default budget (`constants.py`)

```
max_items=1, max_depth=0, max_cost_usd=1.00, max_wall_time_sec=300
```

`max_depth=0` — v1 never delegates. The `voiceover-direction` package is a **test-only** dependency
(the integration test imports its parser); there is no runtime coupling.

---

### visual-generation

ComfyUI-backed diffusion image/video collaborator with a first-class platform-tutor role. **Status: Phase 2 complete (MVP); img2img + inpaint refinement (edit-mode) shipped; user_knowledge doc-ingestion wired.** 191 tests passing. **Video (WAN 2.2): Phase 1 discovery complete + pod/ComfyUI setup verified manually; agent video code is the next Phase 2 build** (see "Video (WAN 2.2)" below).

A standalone, domain-agnostic generation agent modeled on voiceover-direction (cost inversion) and music-curation (curated memory). It inherits by reasoning, not template — three genuine differences (an extreme two-axis cost inversion, a running pod that costs money during otherwise-free prompt-craft, and a node-graph backend plus a tutor role) shaped the decisions below.

#### The turn shape (cost inversion, more extreme than voiceover)

A generation turn is **settle offline (free) → spin up → drain a batch in one warm session → spin down**: `draft` → `generate` → `report`. Prompt-craft (`draft`) is free, infinitely iterable Claude work that appends settled specs to an **editable batch file** (the voiceover `.directed.md` pattern extended to hold multiple specs, lossless round-trip via per-spec HTML-comment JSON). The deliberate paid act is opening and holding the **warm session**; runs inside it are expected iteration. Session-granularity (not per-run) is the deliberate choice because diffusion iteration needs renders to settle a prompt, and RunPod bills per-second of uptime *including* cold-start — so the discipline is "minimize spin-ups," which is exactly draft-offline → drain-a-batch.

#### Two orthogonal budgets

Per-run **Claude** cost stays in agent-runtime's `BudgetEnvelope`. **GPU/pod spend is a separate, agent-local tracker** (`GpuLedger` / `SessionMeter`) — a different currency (GPU-seconds × user-supplied rate + standing storage; nothing caps it underneath beyond RunPod's global default). It is **soft-inform only**: a gate at spin-up estimates session cost from the batch, a running total accrues, and a stop-prompt fires on drain — advise, never block, with an optional `--max-session-cost` hard ceiling. GPU cost is recorded as span attributes and as per-run `cost_usd` in the `generation` payload; it **never enters `BudgetEnvelope`**. v1 holds **no RunPod credential** — pod lifecycle is *advisory*: the user spins the pod up and passes the agent its ComfyUI `--endpoint`; the agent issues no RunPod calls, prompts to stop on batch-drain, and surfaces idle warnings.

#### Collection & memory model

`visual_generation_memory` (1024-dim cosine), three memory types discriminated by `memory_type`:

- **`generation`** — embed target: the image/keyframe at `asset_path` **plus** the caption, via the **multimodal `voyage-multimodal-3`** surface. This is the first agent to lean on multimodal embedding for its own memory. Payload: full `settings` (model-agnostic dict), `model`/checkpoint, `lora_stack` + strengths, `workflow_ref`, `seed`, dimensions, `asset_path`, per-run `cost_usd`, `identity_bearing`, `reaction`, `rating`, `status`, chain lineage (`chain_root_id`/`parent_id`), `project`.
- **`technique_lesson`** — embed target: the `statement`. A lesson learned by doing ("CFG>7 washed skin on this checkpoint"); `scope` ∈ `prompt|settings|workflow|model`, `valence`, `confirmed`.
- **`workflow_template`** — embed target: the `descriptor`. A reusable parameterized ComfyUI graph: the API-format `graph`, a **`slot_map`** (semantic param → `{node_id, input_key}`), and `required_models`.

The text-embedded types coexist with the multimodal `generation` type in one collection because every search filters by `memory_type` and never compares vectors across types (a text-query for generations is embedded through the multimodal surface text-only, so it shares the same vector space). **Reaction vocabulary** mirrors voiceover-direction's aesthetic/technical split: `loved` / `liked` / `liked_with_changes` / `disliked` (ComfyUI rendered the spec faithfully but it's not to taste — weighs against the settings) / `render_failed` (the intent didn't render — artifacts/ignored prompt; the direction stays open, the prior generation surfaces as structure to learn from) / `pending`.

#### Model/LoRA registry (not a vector type)

The voice-registry analog: a local JSON file holding checkpoints, LoRAs, VAEs, etc., enumerated and looked up **by name, never semantically searched**. `model sync` reconciles the registry from a pod's ComfyUI `/object_info` (merge-aware: manual metadata — chiefly the `identity_bearing` flag — survives a sync; a manually-registered asset absent from a given pod is kept and flagged, a previously-synced asset gone absent is dropped); `model rm` unregisters one asset by name (registry-only) to retire scratch (e.g. bake-off checkpoint alternates) so `draft` stops surfacing it. Character LoRAs live here; the `identity_bearing` flag drives the opsec storage decision below **and the LoRA-stack guardrails** (`lora_guard.py`): because **canon owns identity**, `draft` auto-prunes any identity LoRA that duplicates a canon-pinned character (exact file or a stem-sharing checkpoint variant, either direction), and `draft`/`redraft`/`generate` emit a warn-loudly-allow **strength advisory** when a LoRA is at/above a universal ceiling (default 1.5) — the failure mode being that an over-strength LoRA overrides prompt adherence and bleeds identity onto other figures (canonically caused by running a Base-trained LoRA on distilled Turbo, whose fix is to retrain on Turbo so it applies near 1.0).

#### ComfyUI backend + templates

`ComfyUIClient` speaks the native pod API: POST `/prompt` → `prompt_id` → poll `/history/{id}` for outputs → fetch assets from `/view`; `/object_info` enumerates installed models. Workflows are in **API format** (node id → `{class_type, inputs}`). `workflow register` walks an exported graph to **infer a candidate slot map** and required models, then **propose → confirm** (you correct once). The slot map is the right primitive because parameterizing a graph is literally writing values into node inputs by id, and positive vs. negative prompts are distinguishable only by which sampler input they feed. **v1 scope line: consume graphs the user builds in ComfyUI, don't author them** (graph authoring deferred). Flux's parameterization differs from SDXL (CFG≈1.0, a separate flux-guidance slot, no negative prompt) — a per-template slot-map detail the draft chain honors.

#### Video (WAN 2.2) — designed (Phase 1 complete), Phase 2 build pending

Video is **not a new agent** — it's the largest deferred item inside visual-generation,
which the Phase 2 architecture was built to accept ("one path, not two": lineage spans
output types, so an I2V clip's parent can be a prior still). Phase 1 discovery is
complete and the WAN environment is set up + verified manually in ComfyUI on the pod;
the *agent code* for video is the next build. Design rationale:
`docs/handoffs/visual-generation-video-phase1-handoff.md`; captured recipes + slot maps:
`docs/handoffs/visual-generation-video-phase1-research-signals.md`; reference graphs:
`packages/visual-generation/workflows/`; deferred items:
`docs/v2-refinements/visual-generation-v2-refinements.md`.

**Model:** WAN 2.2 14B (open-weights — runs self-hosted on RunPod; WAN 2.5/2.6 rejected
as closed APIs). Modes for v1: **T2V + I2V** (VACE deferred). The 14B is a Mixture-of-
Experts split by denoising stage — a high-noise then a low-noise expert across two
`KSamplerAdvanced` passes with a boundary step; the registered graph loads two model
files. The ComfyUI default templates ship with lightx2v 4-step LoRAs baked in, and the
I2V graph exposes a toggle between the 4-step (cfg 1, steps 4, boundary 2) and 20-step
(cfg 3.5, steps 20, boundary 10) recipes — so one graph covers both fast and quality.

**Planned Phase 2 code deltas (all additive — they keep the "one path" primitives):**

- `VisualSpec` gains an explicit `output: "image" | "video"` field (default `image`);
  `WorkflowTemplate` declares its kind for a cross-check. The marker also tells the
  sanity check which recipe ranges apply and the cost estimator which kind to segment.
- `VisualGeneration` gains an optional `keyframe_path`; `_generation_input` uses
  `keyframe_path or asset_path` so the multimodal embed gets a still even when the asset
  is an `.mp4`. The keyframe is the clip's **middle frame** (extracted via ffmpeg, from
  the produced clip — for I2V, never the seed). Contact-sheet keyframe deferred.
- `generate.py` branches source-provisioning on `output`: image → img2img (denoise
  applies); video → I2V seed frame (no denoise; written to the I2V graph's load-image
  slot, reusing the built `/upload/image` + `VisualSource` path). After writing an mp4,
  extract the middle-frame keyframe.
- `gpu_tracker.estimate_per_run_cost` segments the learned estimate by `output` kind
  (video clips average against video, with a video cold-start default). Size-aware
  bucketing deferred. A **thin WAN-aware sanity check** at the gate echoes the resolved
  recipe and flags out-of-range values (ranges conditional on the LoRA stack) before
  spending — motivated by the cost asymmetry (minutes of GPU per clip).
- `report` gains an optional `composition | motion | both` aspect on video reactions
  (threaded into the note/lesson plumbing) so a `disliked` distinguishes a bad look from
  bad motion. Finer temporal taxonomy deferred.
- Registry + slot map: two WAN expert entries; slot map targets both loaders + the WAN
  settings. ffmpeg becomes a runtime dependency (already used elsewhere in the workspace).

#### Refinement (img2img / inpaint, edit-mode)

`draft --from <gen_id>` (or `--image <path>`, plus `--mask` for inpaint) refines an existing image instead of generating from scratch. The source attaches as a `VisualSource` on the spec; at `generate` the parent's asset is uploaded to the pod and written into the template's `init_image` (and `mask`) slot, and the child records `parent_id`/`chain_root_id` lineage. Refinement drafts are **edit-mode**: `craft_spec` seeds the new prompt from the parent's prompt (edit, not rewrite), inherits the parent's model/LoRA/dimensions, and **deterministically strips `settings` to `{}`** so the template's own recipe stands (the caller's `--denoise` is the only authored setting — enforced in code, not just by instruction). A draft-time `inert_inheritance` advisory warns when inherited attributes (LoRAs/dims) have no slot in the resolved template. `workflow register` is idempotent (replace-by-name), so re-registering a template name overwrites it rather than duplicating. **The `visual-workflow-inpaint` path is proven end-to-end through the CLI** (a masked single-region edit — repainting one TV screen inside a stop-motion bar plate): mask PNG marks white = repaint, masked inpaint uses a higher denoise (≈0.8) than whole-image img2img (≈0.65) since only the masked region is regenerated, and the mask should cover the target region only (masking a surrounding frame lets the model reinterpret the whole prop). Note: draft-time template *retrieval* runs through the Voyage embeddings API; a transient outage degrades to no template, which for inpaint silently leaves the `mask`/`init_image` slots unwired — pass `--template visual-workflow-inpaint` to bypass retrieval. Tracked rough edges: `draft` does not create the batch parent dir (KI-6) and the default batch file is `batch.batch.md` (KI-7). **`redraft` is the text2img directed-revise complement to `--from`:** it inherits the parent's recipe *and seed* in code, records `revised_from` lineage, and keeps `source=None` (no image uploaded) — so `generate` renders it as plain text2img, where `--from` attaches a `VisualSource` and refines the pixels.

#### Retrieval (`retrieval.py`)

`retrieve_context(query, store, memory_store, ...)` composes three collections in parallel via `asyncio.gather`, mirroring music/voiceover: own `visual_generation_memory` (generations through the multimodal query-space, technique_lessons, workflow_templates) + `user_knowledge` (`comfyui_mechanics` and `runpod_mechanics`, 1.25× score boost — `USER_KNOWLEDGE_SCORE_MULTIPLIER`) + `tutorial_research`. Each leg degrades silently to an empty bucket, so the agent stays useful from a cold start. The standing distinction: `user_knowledge` = documented platform/vendor facts; `technique_lesson` = lessons learned by doing; `tutorial_research` = tutorial-derived technique. `user_knowledge` is seeded two ways: single facts via `fact add`, and whole doc folders via `fact ingest-docs` — a CLI wrapper over `agent_runtime.knowledge.docs_ingest` (the shared, domain-agnostic pipeline: H2+-section chunking, `source_ref` from frontmatter `url:`, idempotent re-ingest, `bulk_load_verified` under the chosen domain).

#### Asset storage + identity opsec

Assets are **disk files referenced by `asset_path`, never stored in Qdrant and never in the obsidian vault** — the vector point embeds the image/keyframe + caption and references the file by path. Non-identity assets live under `~/agent-data/visual-generation/assets/`; **identity-bearing assets (and the generations that use them) live in a secured, isolated path, write-guarded** against the vault, `agent-reports`, and any synced location (extending the clean-directory-separation rule). Encryption-at-rest for identity artifacts is deferred. Distinct from this is the **content hard line** — no nude generation, no clothed→unclothed transformation of real people — enforced at the capability level (not a capability the agent builds).

#### Tutor role (`explain`, `research`)

- **`explain <concept> [--level full|concise|quiet]`** — a grounded Sonnet deep-dive (`MODEL_DIRECTOR`, Claude budget, **no GPU**). It always runs the three-collection retrieval and **always surfaces the user's own relevant `technique_lesson`s back to them**; the `--level` dial (config-defaulted to `concise`) changes only how much *generic* explanation rides along, never whether own-lessons appear.
- **`research <topic>`** — the explicit, deliberate path `draft` only offers on a gap. A standard `delegate()` to tutorial-research with a **Claude-cost-only child budget** (research touches no GPU — it never enters the agent-local tracker). Two-step with a cheap fallback: tutorial-research writes to the `tutorial_research` collection, already one of the three retrieval legs, so subsequent `draft`/`explain`/`recall` retrieve it cheaply with no re-delegation. (visual-generation registers the tutorial-research delegate handler at its own CLI bootstrap, guarded against double-registration.)

Inline tutoring also rides the free `draft` call (a concise rationale citing retrieved own-lessons).

#### CLI subcommands

```bash
visual-generation draft "<intent>" [-o batch.md] [--template <name>] [--from <gen_id> | --image <path>] [--mask <path>] [--denoise N] [--model {sonnet|opus}]
visual-generation redraft <gen_id> "<change>" [-o batch.md] [--project P] [--model {sonnet|opus}]
visual-generation generate <batch.md> (--section <id> | --all) --endpoint <url> [--gpu-rate N] [--max-session-cost N] [-y]
visual-generation report <gen_id> --reaction <loved|liked|liked_with_changes|disliked|render_failed> [--rating 1-5] [--notes ...] [--context ...]
visual-generation model sync --endpoint <url>;  visual-generation model list
visual-generation workflow register <exported-api.json>;  visual-generation workflow list
visual-generation review-pending;  visual-generation recall "<query>";  visual-generation chain show <root_id>
visual-generation batch list <batch.md>;  visual-generation batch rm <batch.md> <spec_id> [--yes]
visual-generation lesson add "<statement>" --scope <prompt|settings|workflow|model> --valence <positive|negative>
visual-generation fact add "<statement>" --domain <comfyui_mechanics|runpod_mechanics>
visual-generation fact ingest-docs <folder> --domain <comfyui_mechanics|runpod_mechanics> [--dry-run] [--yes]
visual-generation explain "<concept>" [--level full|concise|quiet]
visual-generation research "<topic>"
```

#### Default budgets (`constants.py`)

```
DRAFT_BUDGET    (draft):    max_items=1,    max_depth=1, max_cost_usd=1.50, max_wall_time_sec=300
GENERATE_BUDGET (generate): max_items=None, max_depth=0, max_cost_usd=0.50, max_wall_time_sec=1800
EXPLAIN_BUDGET  (explain):  max_items=1,    max_depth=1, max_cost_usd=1.00, max_wall_time_sec=300
RESEARCH_BUDGET (research): max_items=3,    max_depth=2, max_cost_usd=2.00, max_wall_time_sec=600
```

These are the **Claude** axis only. `generate`'s envelope is tiny because the spend phase makes no LLM call — GPU spend is orthogonal and tracked separately. `research` hands tutorial-research a Claude-only child budget derived from `RESEARCH_BUDGET`.

#### Deferred (the path is built to accept them)

video/WAN (a fast-follow on the same turn shape — a generation already embeds a representative keyframe + caption and lineage spans output types) · LoRA training (ai-toolkit — a separate subsystem) · RunPod stop-automation (Tier-2: the agent holds a key and auto-stops on drain/idle) · encryption-at-rest for identity artifacts · the `reference` memory type · the shared `ingest-docs` `--decisions`/`--url` refinements · graph authoring.

---

### technique-research

Technique **discovery**, not clip discovery. **Status: Phase 2 MVP complete.** 40 tests passing. Given a creative goal (optionally a reference image, a reference video URL, or a prior report) it reasons to a prioritized set of technique *domains*, checks what the system already knows, delegates only the genuine gaps to `tutorial-research`, and curates the result. It is the heaviest exerciser of cross-agent delegation in the stack and adds no gathering of its own (no tutorial discovery, no ingestion, no yt-pipeline calls — ever).

#### The Mode A turn (`agent.py`)

`identify(IdentificationInput, *, budget, approval, plan_only, output_path)` runs inside one `BudgetTracker`:

1. **Toolset read** (`retrieval.read_editing_toolset`) — `UserKnowledgeStore.search(query, domain="editing_toolset")`. The director's toolset is **never hardcoded**; this run-level read is its only source, so it tracks the seeded toolset (Resolve free + constraints, ffmpeg, mpv, Topaz Video AI) as it evolves.
2. **Ground** (`grounding.py`) — yt-dlp metadata/description for a `--url` (no frame extraction); a conditional, Claude-triggered Tavily *reference* search (exemplars/commentary, **not** tutorials) only when a named reference is under-specified. A well-specified goal costs zero searches.
3. **Identify** (`chains.identify_techniques`) — Sonnet (vision-capable) takes goal + base64 image blocks + grounded context + prior findings + toolset → prioritized `TechniqueDomain`s, a grounded-reference summary, and the scope (`--scope` authoritative; otherwise inferred — "video like X" → editing, "images like X" → generation).
4. **Check** (`retrieval.check_domain`) — per domain, parallel query of `technique_research_outputs` (own), `tutorial_research` (reusing `tutorial_research.retrieval.retrieve_chunks` verbatim, boosted `user_knowledge` co-query included), and `user_knowledge`; any leg clearing its `CHECK_*_THRESHOLD` answers locally, else the domain is a gap. Each leg emits `record_delegation_decision` for tuning.
5. **Gate** — interactive by default (CLI `click.confirm` per gap); `-y` auto-approves; `--plan-only` stops with a preview (no delegation, no writes); declining all is **not** an abort (curate from local). The gate is supplied as an `approval` callback so the library/orchestrator paths auto-approve.
6. **Delegate** — each approved gap `delegate("tutorial-research", {request, request_type="research", synthesize=True}, _delegation_budget(...), parent_tracker=tracker)`. `max_items` caps **delegations**, not findings: `check_budget()` runs at the top of the loop, `add_item_processed()` after each delegation. `register_delegate_handlers()` is the idempotent bootstrap (mirrors `visual_generation/research.py`).
7. **Curate + write** (`chains.curate_findings`) — one Sonnet call over all domains and their resolved material → `TechniqueFinding`s with how-to-apply grounded in the toolset and a `upgrade_flag` only where a technique is materially faster/only-possible in a paid tool. Findings → `technique_research_outputs` (not item-counted); the `TechniqueReport` markdown → `-o` (a directory writes the default filename into it; `cli.py` validates the path at parse time so a bad `-o` can never cost a run); the standard run report → the vault.

#### Collection & memory model

Owns **`technique_research_outputs`** (1024-dim cosine, text / `voyage-3-large` — same space as `tutorial_research`/`user_knowledge`, so the orchestrator reads it with no cross-space mismatch). The stored unit is the per-technique **finding**, not the report (`TechniqueFinding.to_memory_point` → `source_type="agent_summary"`, structured fields in the point `metadata`). The agent's own `check` step is the retrieval consumer that earns the collection. `recall(query)` searches it; `_record_llm` (copied from music-curation) bridges Anthropic cost into the tracker.

#### Default budget (`constants.py`)

```
DEFAULT_BUDGET: max_items=5, max_depth=1, max_cost_usd=5.00, max_wall_time_sec=2700
```

`max_items` caps techniques gathered (delegations); `max_depth=1` permits exactly the one hop to tutorial-research (`delegate()` derives a depth-0 child, so tutorial-research cannot delegate further). Per-delegation caps (`DELEGATION_CHILD`) and check thresholds (`CHECK_*_THRESHOLD = 0.70 / 0.65 / 0.70`) are unvalidated starting values.

#### Cross-agent dynamics

*Knowledge channel (automatic):* delegated gathering lands in `tutorial_research`, which visual-generation already queries — generation-technique research lands where visual-generation looks, zero integration. *Artifact channel:* the report feeds `concept-script draft --seeds` and supplies intent language for `visual-generation draft`. The orchestrator wraps `technique_recall` (free) and `technique_identify` (full run, child-budgeted; the per-turn `max_depth=2` accommodates orchestrator → technique-research → tutorial-research) and gains `technique_research_outputs` as a `search_knowledge` domain. Deferred items: `docs/v2-refinements/technique-research-v2-refinements.md`.

---

### orchestrator

The conversational meta-agent over the whole system — the "director's console." **Status: Phase 2 first build slice + Phase 3 sub-agent surface + diagnose-only vector-DB diagnostics shipped.** 42 tests passing. The first agent in the stack to use **LangGraph** (hand-rolled ReAct loop) over `langchain-anthropic`, with a thread-keyed SQLite checkpointer for resumable conversations; the other five agents remain on plain sequential LangChain. It is a reader/router over the rest of the system — it owns no Qdrant collection.

#### Graph (hand-rolled ReAct, `graph.py`)

One `agent` node (Sonnet, all tools bound via `bind_tools`) + one custom `tools` node (wraps LangGraph's `ToolNode` for execution), joined by a conditional edge: an AI message with tool calls routes to `tools` and loops back to `agent`; no tool calls ends the turn. Hand-rolled rather than the prebuilt `create_react_agent` so the runtime hooks are explicit insertion points. `MessagesState`-style state (`messages` via the `add_messages` reducer) extended with a `budget_exhausted` flag. The `BudgetTracker` is **not** stored in state (the checkpointer must serialize state) — nodes reach the active tracker via the runtime `get_current_tracker()` ContextVar; each turn re-seeds `budget_exhausted=False` on input (last-write-wins) while messages accumulate through the reducer.

#### Per-turn budget guard + tracing hooks

One turn = one top-level `graph.ainvoke`, governed by a per-turn `BudgetEnvelope`/`BudgetTracker` (the **parent** for any in-turn sub-agent delegation via `derive_child`). The custom `tools` node runs `tracker.check_budget()` **before** executing the step's tool calls; on `BudgetExhaustedError` it short-circuits — appends a skip `ToolMessage` per pending call, sets `budget_exhausted`, and the conditional edge ends the turn with a partial answer rather than letting the exception escape. Per executed tool it calls `record_tool_call` (which bridges to `BudgetTracker.add_tool_call()`) **and** `tracker.add_item_processed()` — so `max_items` is the per-turn tool-call ceiling. Sub-agent tools additionally emit `record_delegation_decision` and `tracker.add_delegation(child_cost)`. Agent-node LLM cost is routed through `tracker.add_llm_cost` from the response's `usage_metadata`.

#### Checkpointer

LangGraph `AsyncSqliteSaver` (`langgraph.checkpoint.sqlite.aio`) at `~/agent-data/agent-stack.db`, thread-keyed and resumable across sessions; `.setup()` is called at startup. This is the library managing its own `checkpoints`/`writes` tables — **not** the (unbuilt) schema-migration runner, which will later add its ledger table to the same file (see Layer 6).

#### Tools (v1 set, `tools.py`)

- **`search_knowledge(query, domain)`** (`retrieval.py`) — domain-scoped semantic retrieval over a registry (`tutorial_research`, `music_curation_memory`, `voiceover_direction_memory`, `visual_generation_memory`, `langgraph_mechanics`). Each call targets exactly **one embedding space** (text / `voyage-3-large`) so scores never merge across spaces, and co-queries `user_knowledge` with the 1.25× boost (`USER_KNOWLEDGE_SCORE_MULTIPLIER`) capped at 30%, degrading gracefully to `[]` when a collection is absent. Generalized from `tutorial-research/retrieval.py` (the `tutorial_research` domain reuses `retrieve_chunks` verbatim; the `langgraph_mechanics` domain *is* `user_knowledge`, queried by domain filter with no separate co-query). Concept-script is stateless and owns no collection, so it has no domain here.
- **`read_file` + `grep`** — live repo access scoped to `packages/` and `docs/` (Claude-Code style), sandboxed to the workspace root (path-escape guarded; `grep` shells to `rg` with a Python-walk fallback). Also how the orchestrator answers system-introspection questions ("what does agent X do / how is it built / how do I use it") — by reading source and `ai-director-agent-system.md`.
- **In-process sub-agent tools**, each calling the agent's existing async library entry point with a child budget derived from the per-turn envelope and recording the delegation. Only **FREE / non-side-effecting** ops are wrapped — the costly paid ops (visual-generation `generate` = GPU/RunPod spend; voiceover-direction TTS = ElevenLabs money) are deliberately kept out of the autonomous tool set:
  - `tutorial_retrieve` / `research_tutorials` (tutorial-research retrieve vs. research)
  - `music_recall` / `music_generate` (music-curation dry-run recall vs. prompt generation)
  - `voiceover_direct` / `voiceover_recall` (voiceover-direction free LLM direction over a `script.md` vs. embedding-only context recall)
  - `concept_draft` / `concept_shape` (concept-script draft-from-seeds vs. shape-from-transcript; stateless agent, no recall)
  - `visual_draft` / `visual_recall` (visual-generation free prompt-craft vs. embedding-only own-memory recall)
- **Vector-DB diagnostics (diagnose-only, `diagnostics.py`)** — the orchestrator audits the Qdrant layer but **never writes to it**. Three tools the Sonnet loop composes with `read_file`/`grep` (which it uses to read an agent's collection / filter / score-threshold / embedding model from source):
  - `inspect_collection(collection)` — read-only structural metadata (existence, point count, vector size/distance, sampled payload keys) via the new `MemoryStore.get_collection_info` / `count_points` / `sample_points`.
  - `probe_collection(collection, query, expected_point_id?, multimodal?, threshold?)` — a **behavioral probe**: embeds a query that *should* hit (text `voyage-3-large`, or `voyage-multimodal-3` when `multimodal=True`) and checks whether the expected point returns above threshold. The only way to catch a **cross-model embedding-space mismatch** — when the expected point exists in the collection but the probe can't surface it, the stored vectors were written in a different Voyage space.
  - `write_diagnostic_report(...)` — writes a markdown report (YAML frontmatter: collection, owning agent, symptom, diagnosis, evidence = filter/threshold/model-from-code + payloads/scores-from-Qdrant, proposed fix, `status`) to `~/obsidian/agent-reports/diagnostics/`, status `open`.
  The **remediation delegation seam** (`RemediationHandler` protocol + registry + `delegate_remediation`, status `open → delegated → fixed`) is built and tested with a stub, but **ships with an empty registry**: no agent exposes a remediation write path yet, so reports stay `open` as manual work orders. Per-agent remediation entry points are deferred to `docs/v2-refinements/orchestrator-v2-refinements.md` — keeping the orchestrator a pure reader and the autonomous loop unable to trigger any Qdrant write.

#### CLI (`cli.py`) + library API

```bash
orchestrator chat [--thread <id>]   # checkpointed REPL: read → run the graph for the thread → print → loop
```

A new thread per launch unless `--thread` resumes a checkpointed one. The per-session cumulative cost is surfaced as a **soft tally** (informational, never a hard cap — a checkpointed thread is meant to resume across sessions).

```python
from orchestrator import build_app, run_turn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async with AsyncSqliteSaver.from_conn_string("agent-stack.db") as saver:
    await saver.setup()
    graph = build_app(saver)
    result = await run_turn(graph, "what does the music-curation agent do?", thread_id="t1")
    # result.response, result.status ("completed"|"partial"), result.consumption
```

#### Model constants (`constants.py`) & default budget

`MODEL_ORCHESTRATOR = claude-sonnet-4-6` — defined here per the per-package convention, **not** in agent-runtime. `MODEL_UTILITY = claude-haiku-4-5` is reserved (the Haiku utility roles — tool-output compression, long-thread summarization — are not wired in for v1).

```
DEFAULT_BUDGET (per turn): max_items=12, max_depth=2, max_cost_usd=1.50, max_wall_time_sec=300
```

`max_items` is the per-turn tool-call ceiling; `max_depth=2` permits orchestrator → sub-agent → tutorial-research.

#### Tests

```bash
uv run pytest packages/orchestrator/tests/ -v   # 42 tests
```

Covers the graph loop (a tool call routes to `tools` and loops back; no tool call ends the turn), the budget guard (an exhausted per-turn envelope short-circuits to a partial answer before the next tool runs), `search_knowledge` (user-knowledge boost applied + graceful degradation when a collection is absent), and the checkpointer (two turns on one `thread_id` resume accumulated state, surviving across saver instances). Stubs the chat model (injected into `build_graph`) so no real LLM/Qdrant is required.

#### Deferred (first slice)

per-agent remediation entry points (the owning-agent write paths the diagnostics delegation seam will call — see `docs/v2-refinements/orchestrator-v2-refinements.md`) · MCP (wrapping agents and exposing the orchestrator) · additional surfaces (Telegram/voice/web/scheduled) · Haiku utility (output compression, thread summarization) · the per-session hard ceiling (v1 is a soft tally) · the schema-migration runner/ledger. *(Now shipped: all five built agents wrapped as tools — free/non-side-effecting ops only — and diagnose-only vector-DB diagnostics.)*

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
| `user_knowledge` | User-authored first-party knowledge (verified facts, doc distillations) | `UserKnowledgeStore` (agent-runtime) |
| `music_curation_memory` | Generation history, taste lessons, templates, sound references | `MusicCurationStore` (music-curation) |
| `voiceover_direction_memory` | Takes (text → voice/settings/reaction, section-scoped lineage) and direction lessons | `VoiceoverDirectionStore` (voiceover-direction) |
| `visual_generation_memory` | Generations (image+caption multimodal), technique lessons, workflow templates | `VisualGenerationStore` (visual-generation) |

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
uv sync --all-packages && uv run pytest -v               # full suite (879 tests)
uv run pytest packages/agent-runtime/tests/ -v          # 184 tests
uv run pytest packages/yt-intelligence-pipeline/tests/ -v  # 45 tests
uv run pytest packages/tutorial-research/tests/ -v      # 52 tests
uv run pytest packages/music-curation/tests/ -v         # 214 tests
uv run pytest packages/voiceover-direction/tests/ -v    # 145 tests
uv run pytest packages/concept-script/tests/ -v         # 45 tests
uv run pytest packages/visual-generation/tests/ -v      # 152 tests
```

Tests that require Qdrant running on `localhost:6333` are marked with `@requires_qdrant` and skipped automatically if unreachable. No test requires real Voyage, Anthropic, or ElevenLabs API keys.

**Monorepo pytest isolation:** `--import-mode=importlib` is set in the workspace root `pyproject.toml`. Packages do not have `tests/__init__.py` — this prevents namespace collisions when pytest collects from multiple packages.
