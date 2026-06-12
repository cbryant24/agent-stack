from __future__ import annotations

from agent_runtime import BudgetEnvelope

AGENT_NAME = "feedback-iteration"

# Sonnet maps perceptual feedback to anchors, diagnoses the change, rewrites step
# text, and (for a timing request) names the OPERATION and the AMOUNT THE DIRECTOR
# STATED. It never computes or alters a timestamp — the time engine owns all
# arithmetic. One model slot per the per-package convention.
MODEL_REVISE = "claude-sonnet-4-6"
MAX_REVISE_TOKENS = 8192

# One per-run envelope. The single spend is one whole-brief mapping/diagnosis call
# (retry-once on a parse failure); parsing, the time engine, patching, and
# versioning are free, no external spend, no delegation (max_depth=0).
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=1,
    max_depth=0,
    max_cost_usd=2.00,
    max_wall_time_sec=600,
)

# ── Collections read for grounding (READER, never an owner — imports no sibling
# package; foreign collections read generically by name) ─────────────────────
TECHNIQUE_OUTPUTS_COLLECTION = "technique_research_outputs"
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
EDITING_TOOLSET_DOMAIN = "editing_toolset"

# Lessons distilled from feedback are durable editing-taste rules. They are
# written to user_knowledge via propose→confirm — F&I owns no collection.
EDITING_PREFERENCE_DOMAIN = "editing_preference"

# ── Retrieval limits ─────────────────────────────────────────────────────────
TOOLSET_LIMIT = 10
FINDINGS_LIMIT = 6
TUTORIAL_LIMIT = 4
USER_KNOWLEDGE_LIMIT = 6
# user_knowledge hits are first-party, verified — boosted over tutorial material
# per the established 1.25× convention.
USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25
