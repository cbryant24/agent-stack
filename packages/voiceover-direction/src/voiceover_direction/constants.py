"""Constants for the voiceover-direction agent.

The Qdrant collection holds two memory types discriminated by the `memory_type`
payload field. The voice registry is NOT a memory type — it is a local JSON file
(see voice_registry.py). The monthly ElevenLabs character budget is never stored
here; it is queried from the vendor at generation time (Step 3).
"""

from __future__ import annotations

from agent_runtime import BudgetEnvelope

COLLECTION_NAME = "voiceover_direction_memory"

# Memory type discriminators (stored as a payload field on every Qdrant point).
MEMORY_TYPE_TAKE = "take"
MEMORY_TYPE_DIRECTION_LESSON = "direction_lesson"

# Take lifecycle status (derived from reaction).
STATUS_PENDING = "pending"
STATUS_COMPLETE = "complete"

# Reaction vocabulary. A take is born `pending` (generated, not yet listened to);
# `report` (Step 4) flips it to a settled reaction.
#
# The load-bearing distinction (handoff): `disliked` vs `render_failed`.
#   disliked      — ElevenLabs rendered the direction faithfully, but the result isn't to
#                   taste (AESTHETIC). Weighs AGAINST the direction/territory (voice/pacing/tone).
#   render_failed — ElevenLabs did NOT render the direction's intent (tags ignored,
#                   mispronunciation, wrong emphasis). The direction was fine, so the territory
#                   stays OPEN; the prior take is surfaced as structure to learn from.
# Dropped from music-curation (don't apply to TTS — a take always has saved audio):
#   copyright_blocked, never_ran, lost_track.
REACTION_PENDING = "pending"
REACTION_LOVED = "loved"
REACTION_LIKED = "liked"
REACTION_LIKED_WITH_CHANGES = "liked_with_changes"
REACTION_DISLIKED = "disliked"
REACTION_RENDER_FAILED = "render_failed"

# Settable reactions (what `report` accepts — excludes the `pending` sentinel). Order is
# the display order.
REACTIONS = [
    REACTION_LOVED,
    REACTION_LIKED,
    REACTION_LIKED_WITH_CHANGES,
    REACTION_DISLIKED,
    REACTION_RENDER_FAILED,
]

# Ratings are meaningful only for positive reactions.
POSITIVE_REACTIONS = {REACTION_LOVED, REACTION_LIKED, REACTION_LIKED_WITH_CHANGES}

# Embedding dimension — voyage-3-large, matches MemoryStore's default vector size.
EMBEDDING_DIM = 1024

# ── Direction (Step 2) ───────────────────────────────────────────────────────

# The whole-script direction chain runs on Sonnet. eleven_v3 is the default
# generation model the directed script targets (the expressive, audio-tag-capable
# one — Step 3 spends on it).
MODEL_DIRECTOR = "claude-sonnet-4-6"
MAX_DIRECTION_TOKENS = 8192  # whole-script output: every section in one pass
DEFAULT_MODEL = "eleven_v3"

# Sibling collections composed during retrieval (runtime-owned / external).
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"

# user_knowledge hits are user-verified, so they outrank tutorial hits on a tie.
USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25
# The domain under which ElevenLabs mechanics facts live in user_knowledge.
ELEVENLABS_MECHANICS_DOMAIN = "elevenlabs_mechanics"

# Default per-run budget for the Claude cost of a `direct` run. Direction never
# triggers research inline, so no delegation is wired (depth is moot). The
# ElevenLabs character budget is NOT represented here — it is orthogonal.
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=1,
    max_depth=1,
    max_cost_usd=1.50,
    max_wall_time_sec=300,
)

# ── Generation (Step 3) ──────────────────────────────────────────────────────

# ElevenLabs TTS output format ("codec_samplerate_bitrate"); the file extension is
# the codec prefix (mp3_44100_128 -> .mp3).
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
# Span attribute for characters consumed by a generate run. The character budget is
# orthogonal — recorded here for tracing, NEVER routed through BudgetEnvelope.
CHARACTERS_SPAN_ATTR = "elevenlabs.characters_consumed"

# Per-run budget for a `generate` run. Generation can process many sections (--all), so
# there is no item cap — the real limiter on the spend is the vendor character quota
# (orthogonal, never in this envelope). The option-B fold-in adds a Claude path (per-section
# re-direction), so there IS a cost cap now (mirrors `direct`'s, slightly higher to allow a
# per-section --all re-direction pass). The character count never enters this envelope.
# max_depth=0: no delegation.
GENERATE_BUDGET = BudgetEnvelope(
    max_items=None,
    max_depth=0,
    max_cost_usd=2.00,
    max_wall_time_sec=600,
)
