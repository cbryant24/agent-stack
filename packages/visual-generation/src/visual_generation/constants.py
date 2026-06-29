"""Constants for the visual-generation agent.

The Qdrant collection `visual_generation_memory` holds three memory types
discriminated by the `memory_type` payload field. The model/LoRA registry is NOT
a memory type — it is a local JSON file (see model_registry.py). GPU/pod spend is
tracked on a separate axis (Step 4) and never enters BudgetEnvelope; only the
per-run GPU cost is recorded in the `generation` payload.
"""

from __future__ import annotations

COLLECTION_NAME = "visual_generation_memory"

# Memory type discriminators (stored as a payload field on every Qdrant point).
MEMORY_TYPE_GENERATION = "generation"
MEMORY_TYPE_TECHNIQUE_LESSON = "technique_lesson"
MEMORY_TYPE_WORKFLOW_TEMPLATE = "workflow_template"

# Generation lifecycle status (derived from reaction).
STATUS_PENDING = "pending"
STATUS_COMPLETE = "complete"

# Reaction vocabulary (closed set). A generation is born `pending` (rendered, not
# yet reacted to); `report` (Step 4) flips it to a settled reaction.
#
# The load-bearing distinction (handoff, mirrors voiceover's aesthetic/technical split):
#   disliked      — ComfyUI rendered the spec faithfully, but the result isn't to taste
#                   (AESTHETIC). Weighs AGAINST the settings/direction.
#   render_failed — the intent did NOT render (artifacts, ignored prompt, bad anatomy).
#                   The direction was fine, so the territory stays OPEN; the prior
#                   generation is surfaced as structure to learn from.
REACTION_PENDING = "pending"
REACTION_LOVED = "loved"
REACTION_LIKED = "liked"
REACTION_LIKED_WITH_CHANGES = "liked_with_changes"
REACTION_DISLIKED = "disliked"
REACTION_RENDER_FAILED = "render_failed"

# Settable reactions (what `report` accepts — excludes the `pending` sentinel).
# Order is the display order.
REACTIONS = [
    REACTION_LOVED,
    REACTION_LIKED,
    REACTION_LIKED_WITH_CHANGES,
    REACTION_DISLIKED,
    REACTION_RENDER_FAILED,
]

# Ratings are meaningful only for positive reactions.
POSITIVE_REACTIONS = {REACTION_LOVED, REACTION_LIKED, REACTION_LIKED_WITH_CHANGES}

# Technique-lesson scope (one of these four).
LESSON_SCOPE_PROMPT = "prompt"
LESSON_SCOPE_SETTINGS = "settings"
LESSON_SCOPE_WORKFLOW = "workflow"
LESSON_SCOPE_MODEL = "model"

# Model/LoRA registry asset kinds.
ASSET_KIND_CHECKPOINT = "checkpoint"
ASSET_KIND_LORA = "lora"
ASSET_KIND_VAE = "vae"
ASSET_KIND_CONTROLNET = "controlnet"
ASSET_KIND_CLIP = "clip"
ASSET_KIND_EMBEDDING = "embedding"

# Embedding dimension. Both surfaces are 1024-dim: generation points use
# voyage-multimodal-3 (image+caption); technique_lesson/workflow_template use
# voyage-3-large (text). They coexist in one collection because every search
# filters by memory_type and never compares vectors across types.
EMBEDDING_DIM = 1024

# Sibling collections composed during retrieval (runtime-owned / external). Read
# generically by name — visual-generation owns none of them, so it imports no
# sibling package (the same reader discipline edit-brief follows).
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"
TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION = "technique_research_outputs"

# user_knowledge hits are user-verified, so they outrank tutorial hits on a tie.
USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25
# Project canon is locked authority — it outranks even user-verified mechanics.
CANON_SCORE_MULTIPLIER = 1.5
# The domains under which this agent's platform-mechanics facts live in
# user_knowledge (backend vs. platform — distinct concerns).
COMFYUI_MECHANICS_DOMAIN = "comfyui_mechanics"
RUNPOD_MECHANICS_DOMAIN = "runpod_mechanics"
MECHANICS_DOMAINS = [COMFYUI_MECHANICS_DOMAIN, RUNPOD_MECHANICS_DOMAIN]

# Locked visual-generation canon lives in user_knowledge under its own domain so
# the mechanics-domain filter never hides it. Ingest with
# `ingest_user_knowledge.py … --domain visual_generation_canon`.
VISUAL_GENERATION_CANON_DOMAIN = "visual_generation_canon"
CANON_DOMAINS = [VISUAL_GENERATION_CANON_DOMAIN]

# Tags that mark a chunk as visually relevant. Used to bias the tutorial_research
# leg (a shared, cross-domain pool) toward image work — so z-image/diffusion
# knowledge isn't crowded out by music/langgraph chunks. Matched against BOTH
# `domain_tags` and `topic_tags`. New ingests that carry any of these tags are
# auto-surfaced. NOTE: these are tutorial_research's `_tagify`'d heading tags;
# technique_research_outputs uses a different vocabulary (see below).
VISUAL_TUTORIAL_TAGS = [
    "z-image-turbo",
    "image-generation",
    "comfyui",
    "diffusion",
    "inpaint",
    "lora",
    "flux",
    "wan",
    "stable-diffusion",
    "img2img",
]

# technique_research_outputs is tagged by the technique-research agent's own
# scope vocabulary: TechniqueReport.scope ∈ {editing, generation, both} is written
# verbatim to `topic_tags` (and `domain_tags` holds the freeform technique title,
# not a controlled tag). So the technique-reports leg must filter on SCOPE, not on
# VISUAL_TUTORIAL_TAGS — the latter matches zero rows here and strands every
# visual report. Visual-relevant = image creation ("generation") or both.
TECHNIQUE_VISUAL_SCOPES = ["generation", "both"]

# ── The turn: draft (Phase A, free) → generate (Phase B, GPU spend) → report ──

from agent_runtime import BudgetEnvelope  # noqa: E402

AGENT_NAME = "visual-generation"

# Prompt-craft chain (Sonnet). draft is the free, infinitely-iterable loop.
MODEL_DIRECTOR = "claude-sonnet-4-6"
MODEL_OPUS = "claude-opus-4-8"
MAX_DRAFT_TOKENS = 4096

# `--model {sonnet|opus}` aliases → API strings. Constrained (CLI uses click.Choice);
# an omitted alias resolves to MODEL_DIRECTOR (Sonnet). Each target must have a row in
# agent_runtime.budget._PRICING or its cost falls back to $0.
MODEL_ALIASES = {"sonnet": MODEL_DIRECTOR, "opus": MODEL_OPUS}


def resolve_model(alias: str | None) -> str:
    """Resolve a `--model` alias to its API string; None → MODEL_DIRECTOR."""
    if alias is None:
        return MODEL_DIRECTOR
    return MODEL_ALIASES[alias]

# Per-run Claude budget for a `draft` (BudgetEnvelope = the Claude axis only; the
# GPU axis NEVER enters it). draft never delegates inline (research is offered,
# run separately in Step 5), so depth is moot.
DRAFT_BUDGET = BudgetEnvelope(max_items=1, max_depth=1, max_cost_usd=1.50, max_wall_time_sec=300)

# `generate` spends GPU, not Claude — its Claude axis is ~0 (no LLM in the spend
# phase). A tiny envelope keeps the spend run traced; the GPU cost is orthogonal.
GENERATE_BUDGET = BudgetEnvelope(max_items=None, max_depth=0, max_cost_usd=0.50, max_wall_time_sec=1800)

# ── Tutor: explain (Q6, grounded Claude deep-dive — Claude axis only, no GPU) ──

# Verbosity dial. The level changes ONLY how much GENERIC explanation rides along;
# the user's own technique lessons are always surfaced regardless of level.
EXPLAIN_LEVEL_FULL = "full"
EXPLAIN_LEVEL_CONCISE = "concise"
EXPLAIN_LEVEL_QUIET = "quiet"
EXPLAIN_LEVELS = [EXPLAIN_LEVEL_FULL, EXPLAIN_LEVEL_CONCISE, EXPLAIN_LEVEL_QUIET]
# Config default (env override: VISUALGEN_EXPLAIN_LEVEL); concise per Q6.
DEFAULT_EXPLAIN_LEVEL = EXPLAIN_LEVEL_CONCISE
EXPLAIN_LEVEL_ENV_VAR = "VISUALGEN_EXPLAIN_LEVEL"
# Per-level Claude max_tokens — the dial's mechanical lever on gloss volume.
EXPLAIN_MAX_TOKENS = {
    EXPLAIN_LEVEL_FULL: 1500,
    EXPLAIN_LEVEL_CONCISE: 500,
    EXPLAIN_LEVEL_QUIET: 150,
}
# Claude-cost envelope for an `explain` deep-dive. GPU is never a dimension here.
EXPLAIN_BUDGET = BudgetEnvelope(max_items=1, max_depth=1, max_cost_usd=1.00, max_wall_time_sec=300)

# ── Tutor: research (Q9 — explicit delegation to tutorial-research) ───────────

# Parent envelope for a `research` run. Claude-cost only — research touches no GPU,
# so the agent-local GPU tracker is never entered on this path. max_depth=2 leaves
# room for delegate() to derive a depth-1 child for tutorial-research.
RESEARCH_BUDGET = BudgetEnvelope(max_items=3, max_depth=2, max_cost_usd=2.00, max_wall_time_sec=600)
# The child budget handed to delegate() (Claude-only). delegate() derives a further
# child from this, so max_depth>=1 keeps the depth check satisfied.
RESEARCH_CHILD_BUDGET = BudgetEnvelope(max_items=3, max_depth=1, max_cost_usd=1.50, max_wall_time_sec=400)
# The delegation target (its tutorial_research collection is already a retrieval leg,
# which makes research two-step with a cheap fallback).
DELEGATE_TARGET_TUTORIAL_RESEARCH = "tutorial-research"

# ── GPU cost axis (agent-local; Q3 — never a BudgetEnvelope dimension) ─────────

# The agent can't read RunPod pricing; the user supplies the rate (--gpu-rate),
# falling back to this default.
DEFAULT_GPU_RATE_USD_PER_HR = 0.69
# Cold-start per-run estimate (no recorded history yet): minutes × rate.
DEFAULT_PER_RUN_MINUTES = 1.0
# How many recent recorded per-run costs feed the learned per-run estimate.
RECENT_COST_SAMPLE = 20

# Span attributes for GPU spend (trace-only; never budget dimensions).
GPU_SECONDS_SPAN_ATTR = "visualgen.gpu_seconds"
GPU_COST_SPAN_ATTR = "visualgen.gpu_cost_usd"
SESSION_COST_SPAN_ATTR = "visualgen.session_cost_usd"

# ── Research-gap trigger (draft only OFFERS; it never runs research) ──────────
RESEARCH_GAP_THRESHOLD = 0.35

# ── History poll loop (bounded; interval/timeout injectable for tests) ────────
DEFAULT_POLL_INTERVAL_SEC = 2.0
DEFAULT_POLL_TIMEOUT_SEC = 600.0

# ── Refinement (img2img / inpaint) denoise ────────────────────────────────────
# A source spec with no explicit `denoise` defaults to this at runtime only (the
# saved batch file is never rewritten). Z-Image-Turbo's coherent working range is
# ~0.4–0.7; past DENOISE_COHERENCE_WARN the model loses coherence — warn, never block.
DEFAULT_DENOISE = 0.5
DENOISE_COHERENCE_WARN = 0.85

# Canonical img2img workflow template name. A refinement (source) spec needs an
# `init_image` slot, which only the img2img graph exposes — a txt2img template
# silently cannot apply the source (graph_build.apply_source_filenames warns and
# drops it). So an anchored `batch` defaults its template to this when a source is
# set and no --template is given, ensuring every scene actually img2img's the anchor.
IMG2IMG_TEMPLATE_NAME = "visual-workflow-img2img"

# ── Asset write paths + Q8 opsec (under agent_data_dir / AGENT_SUBDIR) ────────
AGENT_SUBDIR = "visual-generation"
ASSETS_SUBDIR = "assets"          # non-identity assets
IDENTITY_SUBDIR = "identity"       # secured, isolated identity-bearing assets
GPU_LEDGER_FILENAME = "gpu_ledger.json"
DEFAULT_ASSET_EXT = "png"
