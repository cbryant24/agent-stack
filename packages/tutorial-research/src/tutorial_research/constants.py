from __future__ import annotations

from agent_runtime import BudgetEnvelope

MODEL_ORCHESTRATOR = "claude-sonnet-4-6"
MODEL_SCORER = "claude-haiku-4-5"
MODEL_SYNTHESIZER = "claude-sonnet-4-6"

DEFAULT_BUDGET = BudgetEnvelope(
    max_items=5,
    max_depth=0,
    max_cost_usd=2.00,
    max_wall_time_sec=900,
)

COVERAGE_SPARSE_THRESHOLD = 0.55
COVERAGE_THIN_SOURCE_COUNT = 2
