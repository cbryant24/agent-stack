from __future__ import annotations

from agent_runtime import BudgetEnvelope

# Claude model used for both modes. Sonnet is the stack's default craft model.
MODEL = "claude-sonnet-4-6"

MAX_TOKENS = 8192

# v1 is stateless and never delegates: max_depth=0. A single artifact per run.
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=1,
    max_depth=0,
    max_cost_usd=1.00,
    max_wall_time_sec=300,
)

# The wake phrase that marks a deliberate edit command inside a curation transcript.
# Everything else in the transcript is content, never an instruction.
DIRECTOR_NOTE_PHRASE = "director note"
