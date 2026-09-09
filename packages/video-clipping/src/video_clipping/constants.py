"""Constants for the video-clipping agent.

The Qdrant collection `video_clipping_memory` (unused in Phase 0) will hold three
memory types discriminated by the `memory_type` payload field: `run`, `segment`,
`lesson`.

The Sonnet input price used by the projected-cost estimate in `clip draft` is
NOT mirrored here — `draft.py` reads it directly from `agent_runtime.budget._PRICING`
so there is one source of truth.
"""

from __future__ import annotations

import uuid

AGENT_NAME = "video-clipping"
AGENT_SUBDIR = "video-clipping"  # under RuntimeConfig.agent_data_dir

# ── Qdrant collection + memory-type discriminator (Phase 2+) ─────────────────
COLLECTION_NAME = "video_clipping_memory"
MEMORY_TYPE_RUN = "run"
MEMORY_TYPE_SEGMENT = "segment"
MEMORY_TYPE_LESSON = "lesson"

# Embedding dim (matches sibling agents; text via voyage-3-large).
EMBEDDING_DIM = 1024

# ── Deterministic point-id namespace (Phase 2) ───────────────────────────────
# Sibling agents use uuid4 entry_ids because they never re-run against the
# same identity. video-clipping's `clip generate` can be re-run for the same
# plan (retry, resume) so points MUST be idempotent — we derive deterministic
# uuid5 ids from run_id (+ segment_id) instead. Namespace value is fixed for
# the lifetime of the collection; do not change it without a migration.
NAMESPACE_VIDEO_CLIPPING = uuid.uuid5(uuid.NAMESPACE_DNS, "video-clipping.agent-stack")

# ── LLM pricing lookup (draft-time cost projection) ──────────────────────────
# The model whose input price is used to project cost from candidate frames.
# The actual price is read from agent_runtime.budget._PRICING at draft time so
# there is exactly one source of truth for token pricing.
COST_PROJECTION_MODEL_ID = "claude-sonnet-4-6"

# Estimated input tokens per frame sent to Claude vision. Re-verify against
# Anthropic's vision-token guidance — this is a starting estimate for Phase 0.
IMAGE_TOKENS_PER_FRAME_ESTIMATE = 1600

# Text overhead per decision call (prompt + spec + transcript prose): rough estimate.
TEXT_TOKENS_PER_SEGMENT_ESTIMATE = 800

# ── Vision frame sampling (masterplan §"Recommendations on the open choices") ─
FRAME_SAMPLE_INTERVAL_SEC = 2.0
MAX_FRAMES_PER_SEGMENT = 8

# ── ffmpeg silencedetect ─────────────────────────────────────────────────────
SILENCE_NOISE_DB = -30.0            # noise floor in dB
SILENCE_MIN_DURATION_SEC = 0.5      # minimum silence length to report

# ── ffmpeg scdet post-processing ─────────────────────────────────────────────
# scdet outputs per-frame scores 0..100; treat frames above threshold as cuts,
# and merge cuts closer together than the merge window into a single event.
SCDET_THRESHOLD = 10.0
SCDET_MERGE_WINDOW_SEC = 0.5

# ── Length filter tolerance band (masterplan: "do not hard-drop near-misses") ─
LENGTH_TOLERANCE_SEC = 3.0

# ── Phase 1: paid stages ─────────────────────────────────────────────────────
# Sonnet is the workhorse for both vision summary (Stage 3) and decision (Stage 4).
PHASE1_MODEL_ID = "claude-sonnet-4-6"

# Similarity dedupe: cosine (== dot product for L2-normalized Voyage vectors).
SIMILARITY_THRESHOLD = 0.88

# faster-whisper local transcription.
WHISPER_MODEL_DEFAULT = "small.en"
WHISPER_MODEL_CHOICES = ("small.en", "medium.en")
WHISPER_MAX_ATTEMPTS = 2
WHISPER_BACKOFF_SEC = 3.0

# Per-invocation cost cap for `clip generate`; overridable via --max-usd.
MAX_USD_DEFAULT = 5.00

# Wall-time cap for the whole generate run.
GENERATE_MAX_WALL_TIME_SEC = 3600

# LLM max_tokens caps for Phase-1 calls.
VISION_MAX_TOKENS = 400
DECIDE_MAX_TOKENS = 600

# ── Phase 2: lesson accrual thresholds ───────────────────────────────────────
# Starter values — revisit after 5–10 real runs.
LESSON_CLUSTER_MIN = 3           # exclude-reason clustering: n segments per reason
LESSON_CROSS_RUN_MIN = 2         # cross-run repeats: n segments matching same prior run
LESSON_SURFACE_THRESHOLD = 0.7   # min cosine to surface a lesson into the decide prompt
LESSON_SURFACE_TOP_K = 3

# ── Phase 2: clip explain ────────────────────────────────────────────────────
EXPLAIN_MAX_USD_DEFAULT = 0.50
EXPLAIN_TOP_K_DEFAULT = 8
EXPLAIN_MAX_TOKENS = 1024
EXPLAIN_INCLUDE_TYPES_DEFAULT = "segment,run,lesson"
# Preflight cost estimate: tokens ≈ 4 chars/token + snippet overhead + system prompt.
EXPLAIN_TOKENS_PER_SNIPPET = 200
EXPLAIN_SYSTEM_PROMPT_TOKENS = 400
EXPLAIN_TYPICAL_OUTPUT_TOKENS = 600
