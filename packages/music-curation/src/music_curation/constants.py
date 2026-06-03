from __future__ import annotations

from agent_runtime import BudgetEnvelope

COLLECTION_NAME = "music_curation_memory"

# Memory type discriminators (stored as payload field on every Qdrant point).
MEMORY_TYPE_GENERATION = "generation"
MEMORY_TYPE_TEMPLATE = "template"
MEMORY_TYPE_TASTE = "taste"
MEMORY_TYPE_SOUND_REFERENCE = "sound_reference"

# Reaction vocabulary for generation entries.
REACTION_PENDING = "pending"
REACTION_LOVED = "loved"
REACTION_LIKED = "liked"  # kept, would use (was: approved)
REACTION_LIKED_WITH_CHANGES = "liked_with_changes"
# disliked: Suno rendered the prompt correctly but the result isn't to taste (aesthetic).
REACTION_DISLIKED = "disliked"
# prompt_failed: Suno didn't render the prompt's intent (prompt-engineering issue, not aesthetic).
REACTION_PROMPT_FAILED = "prompt_failed"
REACTION_COPYRIGHT_BLOCKED = "copyright_blocked"
REACTION_NEVER_RAN = "never_ran"
REACTION_LOST_TRACK = "lost_track"

# Positive reactions — the ones for which a 1-5 rating is meaningful.
POSITIVE_REACTIONS = {REACTION_LOVED, REACTION_LIKED, REACTION_LIKED_WITH_CHANGES}

STATUS_PENDING = "pending"
STATUS_COMPLETE = "complete"

MODEL_GENERATOR = "claude-sonnet-4-6"
MODEL_SCORER = "claude-haiku-4-5"

MAX_GENERATION_TOKENS = 4096

# Suno's documented style-field character limit.
STYLE_FIELD_MAX_CHARS = 1000

DEFAULT_BUDGET = BudgetEnvelope(
    max_items=1,
    max_depth=2,  # music-curation → tutorial-research → (further) must be permitted
    max_cost_usd=1.50,
    max_wall_time_sec=300,
)

# Cross-collection retrieval.
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25

# ── Delegation thresholds ────────────────────────────────────────────────────
# IMPORTANT: These are unvalidated starting values.
# They were chosen based on intuition about semantic similarity score
# distributions, not measured against real query data.
#
# How to tune: after building usage history, query delegation_decision trace
# events from ~/agent-data/runs/.../trace.jsonl and compare local_max_score
# distributions for cases where delegation was correct vs. unnecessary.
# Lower = more aggressive delegation; higher = more local-answer confidence.
#
# Applied in: chains.py _check_delegation_trigger()

# Minimum local search score before delegating for a Suno feature/syntax query.
DELEGATION_SUNO_FEATURE_THRESHOLD = 0.70

# Minimum local score before delegating for a "why does X work" music-theory query.
DELEGATION_MUSIC_THEORY_THRESHOLD = 0.65

# Minimum local score before delegating for an artist/genre reference query.
DELEGATION_ARTIST_REF_THRESHOLD = 0.50
