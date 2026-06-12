from __future__ import annotations

from agent_runtime import BudgetEnvelope

AGENT_NAME = "edit-brief"

# Sonnet places the retrieved findings against the COMPUTED grids and emits the
# per-section ordered steps. It never computes or alters a timestamp/BPM — the
# time engine owns all arithmetic. One model slot, defined here per the
# per-package convention.
MODEL_BRIEF = "claude-sonnet-4-6"
MAX_BRIEF_TOKENS = 8192

# One per-run envelope. Synthesis is one whole-brief Sonnet call (retry-once on a
# parse failure); discovery + the time engine are free, no external spend, no
# delegation (max_depth=0). Unvalidated starting values — see the handoff.
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=1,
    max_depth=0,
    max_cost_usd=2.00,
    max_wall_time_sec=600,
)

# ── Collections read (this agent is a READER, never an owner — it imports no
# sibling package; foreign collections are read generically by name, the
# orchestrator's cross-collection-reader precedent) ──────────────────────────
VOICEOVER_COLLECTION = "voiceover_direction_memory"
MUSIC_COLLECTION = "music_curation_memory"
VISUAL_COLLECTION = "visual_generation_memory"
TECHNIQUE_OUTPUTS_COLLECTION = "technique_research_outputs"
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
EDITING_TOOLSET_DOMAIN = "editing_toolset"

# Foreign-payload discriminators / values read during discovery. Duplicated here
# (not imported) to keep edit-brief decoupled from the sibling packages; the
# source of truth is voiceover_direction/constants.py and the agents' models.py.
MEMORY_TYPE_TAKE = "take"
MEMORY_TYPE_GENERATION = "generation"
# Take-selection rule: a positively-reacted take wins, else the latest take.
# Mirrors voiceover_direction.constants.POSITIVE_REACTIONS.
POSITIVE_VO_REACTIONS = {"loved", "liked", "liked_with_changes"}

# ── Time-engine defaults (flags override) ────────────────────────────────────
# Inter-section breathing gap, seconds. The director tunes via --gap; stated
# timing preferences land in user_knowledge and ground future runs.
DEFAULT_GAP_SEC = 0.5
# Word-count → duration estimate rate when a section has no VO take. ~150 wpm.
DEFAULT_WORDS_PER_SEC = 2.5

# ── Retrieval limits ─────────────────────────────────────────────────────────
TOOLSET_LIMIT = 10
FINDINGS_LIMIT = 6
TUTORIAL_LIMIT = 4
USER_KNOWLEDGE_LIMIT = 6
# user_knowledge hits are first-party, verified — boosted over tutorial material
# per the established 1.25× convention.
USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25

# Media extensions the --footage scan considers (the one input with no record).
FOOTAGE_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm",
    ".mp3", ".wav", ".m4a", ".aac", ".flac",
    ".png", ".jpg", ".jpeg", ".webp",
}
