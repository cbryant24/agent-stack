from __future__ import annotations

from agent_runtime import BudgetEnvelope

AGENT_NAME = "technique-research"

# Sonnet is vision-capable — the identification chain analyses reference images
# directly (Claude vision, not embeddings). One model slot drives grounding,
# identification, and curation. Defined here per the per-package convention.
MODEL_IDENTIFY = "claude-sonnet-4-6"

# One per-run envelope. Identification is cheap (one or two Sonnet calls);
# delegations dominate and the gate is the real spend control. max_items caps
# techniques GATHERED (delegations), not findings curated. max_depth=1 permits
# exactly the one hop to tutorial-research (which delegates no further).
# Unvalidated starting values — see the handoff's budget section.
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=5,
    max_depth=1,
    max_cost_usd=5.00,
    max_wall_time_sec=2700,
)

# Per-delegation child caps. derive_child() enforces parent >= child on the
# numeric limits, so these are upper bounds applied against the run envelope.
# Sized for ~tutorial-research's own research-mode defaults ($2.00 / 900s).
DELEGATION_CHILD = {
    "max_items": 3,
    "max_cost_usd": 2.00,
    "max_wall_time_sec": 900,
}

# Collections / domains touched.
TECHNIQUE_OUTPUTS_COLLECTION = "technique_research_outputs"
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
EDITING_TOOLSET_DOMAIN = "editing_toolset"

DELEGATE_TARGET_TUTORIAL_RESEARCH = "tutorial-research"

# ── Check-before-delegate thresholds ─────────────────────────────────────────
# Per identified domain the check queries three collections; if ANY collection's
# max similarity score clears its threshold, the domain is answered locally and
# no delegation is spent. These are UNVALIDATED starting values — tune them from
# the `delegation_decision` trace events (local_max_score vs threshold vs the
# decision that followed) once real runs accumulate, exactly as music-curation's
# DELEGATION_*_THRESHOLD block is meant to be tuned. Higher = delegate more
# eagerly (trust local knowledge less); lower = lean on existing knowledge.
CHECK_TECHNIQUE_OUTPUTS_THRESHOLD = 0.70  # own prior curated findings
CHECK_TUTORIAL_THRESHOLD = 0.65           # already-gathered tutorial material
CHECK_USER_KNOWLEDGE_THRESHOLD = 0.70     # user-verified facts

MAX_IDENTIFY_TOKENS = 4096
MAX_ASSESS_TOKENS = 1024
MAX_CURATION_TOKENS = 4096

# How many hits to pull per collection on the check / toolset reads.
CHECK_LIMIT = 6
TOOLSET_LIMIT = 10
CURATION_MATERIAL_LIMIT = 8
