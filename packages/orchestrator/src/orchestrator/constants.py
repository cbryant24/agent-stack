from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent_runtime import BudgetEnvelope, get_config

# ── Models ──────────────────────────────────────────────────────────────────
# Defined here per the per-package convention (music-curation MODEL_GENERATOR,
# voiceover-direction MODEL_DIRECTOR). NOT a runtime constant.
MODEL_ORCHESTRATOR = "claude-sonnet-4-6"
# Reserved for future Haiku utility roles (tool-output compression, long-thread
# summarization). NOT wired into v1 — Sonnet does all reasoning + tool-calling.
MODEL_UTILITY = "claude-haiku-4-5"

MAX_RESPONSE_TOKENS = 4096

# ── Budget ──────────────────────────────────────────────────────────────────
# One turn = one top-level invocation, governed by this per-turn envelope (the
# same single-invocation model the other agents use). max_items is the per-turn
# tool-call ceiling: each executed tool calls tracker.add_item_processed(), so
# check_budget() enforces it (BudgetEnvelope has no max_tool_calls dimension).
# max_depth=2 permits orchestrator -> sub-agent -> tutorial-research.
DEFAULT_BUDGET = BudgetEnvelope(
    max_items=12,
    max_depth=2,
    max_cost_usd=1.50,
    max_wall_time_sec=300,
)

# Caps applied when deriving a child budget for an in-process sub-agent
# delegation (mirrors music-curation's _run_delegation).
SUBAGENT_MAX_ITEMS = 2
SUBAGENT_COST_CAP_USD = 0.50
SUBAGENT_COST_FRACTION = 0.30
SUBAGENT_WALL_TIME_CAP_SEC = 180
SUBAGENT_WALL_TIME_FRACTION = 0.40


def checkpointer_db_path() -> Path:
    """LangGraph AsyncSqliteSaver DB. The library manages its own tables here
    (via .setup()); this is NOT the schema-migration runner."""
    return get_config().agent_data_dir / "agent-stack.db"


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from this file to the uv workspace root (the dir whose
    pyproject.toml declares [tool.uv.workspace]). Used to sandbox read_file/grep."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text(encoding="utf-8"):
            return parent
    # Fallback: packages/orchestrator/src/orchestrator/constants.py -> repo root
    return here.parents[4]
