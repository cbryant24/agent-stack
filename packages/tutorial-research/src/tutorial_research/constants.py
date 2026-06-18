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

MAX_SYNTHESIS_TOKENS = 8192

# ── Course-doc bulk ingest (ingest-docs) ──────────────────────────────────────
TUTORIAL_RESEARCH_COLLECTION = "tutorial_research"

# Frontmatter `course` value that marks a file as belonging to the Diffusion Mastery
# course. Files with any other `course` (e.g. the Prompt Engineering Bootcamp) are skipped.
DIFFUSION_MASTERY_COURSE = "[[Diffusion Mastery: Flux, Stable Diffusion, Midjourney & more]]"

# source_type stamped on course-doc chunks (a MemoryPoint Literal member). Distinct from
# "youtube_tutorial" so course material is identifiable; both are retrievable from
# tutorial_research (see retrieval.py).
COURSE_DOC_SOURCE_TYPE = "course_doc"

# Default H2 sections to keep (case-insensitive). Everything else — notably the
# "Related Concepts" link lists — is dropped. Tunable per call.
DEFAULT_KEEP_SECTIONS = frozenset(
    {
        "quick review",
        "key concepts",
        "practical applications",
        "important details",
    }
)
