# Architecture

## Overview

`agent-stack` is a uv workspace containing a shared runtime library and several specialized packages. All packages are installed into a single `.venv` at the workspace root; they share dependencies and import each other as workspace members.

## Packages

### agent-runtime

The shared infrastructure layer. All other packages import from here. **Status: complete.** 158 tests passing.

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

#### Layer 4b — UserKnowledgeStore

Runtime-owned wrapper around `MemoryStore` that owns the `user_knowledge` Qdrant collection. Holds user-authored, first-party knowledge (verified Suno mechanics, documentation distillations, hand-written experience) across domains. Distinct from `tutorial_research` (third-party video-derived) and from any agent's personal memory collection (e.g. `music_curation_memory`).

**The `user_knowledge` collection is owned by `UserKnowledgeStore`**. Other code may query it (via `UserKnowledgeStore.search()` or directly via `MemoryStore.query_by_vector()`), but must not call `MemoryStore.upsert_points()` or `upsert_raw_points()` against it — those paths bypass the draft/confirm workflow and schema contract.

**Payload schema** for `user_knowledge` points:

| Field | Type | Notes |
|---|---|---|
| `statement` | str | The fact/assertion; also the vector source text |
| `domain` | str | e.g. `suno_mechanics`, `music_theory`, `voiceover`, `general` |
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

#### Layer 5 — Reporting

- **`render_run_report(run_id, agent_name)`** — loads JSONL trace, renders Obsidian-compatible Markdown to `$AGENT_REPORTS_VAULT/<agent_name>/<date> <title>.md`; template includes LLM usage by model, tool call counts, memory operations, delegation tree, notable events
- **`notify(title, message)`** — `osascript` on Darwin, no-op elsewhere
- **`notify_budget_threshold(agent, consumption, envelope)`** — fires above 75%
- **`notify_run_complete(agent, run_id, status, cost_usd)`**

---

### yt-intelligence-pipeline

The canonical YouTube ingestion capability. **Status: complete.** 40 tests passing. Designed to be called both from the CLI and programmatically by agents.

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

The tutorial research agent. Uses `yt-intelligence-pipeline` as a library to ingest videos, then retrieves relevant content from Qdrant to answer research questions. **Status: complete.** 50 tests passing.

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
7. **Retrieval** — `RetrievedChunk` carries `score`, `source_id`, `content`, `source_title`, `source_url`, `chunk_index`, and `collection_name`. Both `tutorial_research` and `user_knowledge` are queried in parallel via `asyncio.gather`. `user_knowledge` hits receive a 1.25× score multiplier (`USER_KNOWLEDGE_SCORE_MULTIPLIER`) and are capped at 30% of the requested limit. If the `user_knowledge` collection is absent or Qdrant is unreachable, that leg degrades silently to empty. Retrieved chunks are appended to the run report in separate "## Retrieved Content — Tutorial Research" and "## Retrieved Content — User Knowledge" sections when both are present.
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

```bash
uv run tutorial-research "python asyncio patterns"
uv run tutorial-research "python asyncio patterns" --plan-only
uv run tutorial-research "python asyncio patterns" --type retrieve --no-synthesize
```

#### Model constants

| Constant | Value | Used for |
|---|---|---|
| `MODEL_SCORER` | `claude-haiku-4-5` | Candidate scoring (tool-use) |
| `MODEL_SYNTHESIZER` | `claude-sonnet-4-6` | Research synthesis |
| `MODEL_ORCHESTRATOR` | `claude-sonnet-4-6` | (reserved) |
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

Music curation agent. **Status: complete.** 213 tests passing.

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
- **`TasteLesson`** — embed target: `statement`. Payload: `valence` (positive/negative), `scope` (genre/production/instrumentation/vocal/general), `confirmed`.
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
uv sync --all-packages && uv run pytest -v               # full suite (461 tests)
uv run pytest packages/agent-runtime/tests/ -v          # 158 tests
uv run pytest packages/yt-intelligence-pipeline/tests/ -v  # 40 tests
uv run pytest packages/tutorial-research/tests/ -v      # 50 tests
uv run pytest packages/music-curation/tests/ -v         # 213 tests
```

Tests that require Qdrant running on `localhost:6333` are marked with `@requires_qdrant` and skipped automatically if unreachable. No test requires real Voyage or Anthropic API keys.

**Monorepo pytest isolation:** `--import-mode=importlib` is set in the workspace root `pyproject.toml`. Packages do not have `tests/__init__.py` — this prevents namespace collisions when pytest collects from multiple packages.
