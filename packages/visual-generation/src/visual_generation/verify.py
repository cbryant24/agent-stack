"""knowledge-verify — prove what retrieval surfaces for a query, and flag gaps.

Deterministic, read-only, no GPU: runs the same retrieval the craft uses, summarizes
exactly what each leg returned (provenance), and flags the gaps that mean "ingested
knowledge is being ignored" — a leg returning nothing, or a collection that holds
content but surfaced none of it for this query. This is the on-demand answer to
"is my z-image research actually being used?"
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.memory.store import MemoryStore

from visual_generation.constants import (
    COLLECTION_NAME,
    TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
)
from visual_generation.models import ProvenanceLeg
from visual_generation.retrieval import retrieve_context, summarize_provenance
from visual_generation.store import VisualGenerationStore

# Collections to size-audit (the four the agent reads from).
_AUDIT_COLLECTIONS = (
    COLLECTION_NAME,
    USER_KNOWLEDGE_COLLECTION,
    TUTORIAL_RESEARCH_COLLECTION,
    TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
)
# Legs that represent *visual research/canon* (as opposed to the agent's own memory).
_VISUAL_LABELS = {"Project canon", "Technique reports", "Tutorial research"}


@dataclass
class VerifyReport:
    query: str
    legs: list[ProvenanceLeg]
    gaps: list[str]
    collection_counts: dict[str, int]  # -1 = unreachable/absent
    project: str | None = None


async def verify_knowledge(
    query: str,
    store: VisualGenerationStore,
    memory_store: MemoryStore,
    *,
    project: str | None = None,
    limit: int = 8,
) -> VerifyReport:
    """Run retrieval for `query`, summarize what surfaced, and flag the gaps."""
    ctx = await retrieve_context(
        query, store, memory_store,
        generation_limit=limit, lesson_limit=limit, template_limit=limit,
        fact_limit=limit, canon_limit=limit, technique_report_limit=limit, tutorial_limit=limit,
    )
    legs = summarize_provenance(ctx, per_leg=3)
    surfaced = {leg.label for leg in legs}

    gaps: list[str] = []
    if not (_VISUAL_LABELS & surfaced):
        gaps.append(
            "No visual knowledge surfaced (canon / technique reports / tutorial) — research "
            "may be missing, untagged, or off-topic for this query."
        )

    counts: dict[str, int] = {}
    for collection in _AUDIT_COLLECTIONS:
        try:
            counts[collection] = await memory_store.count_points(collection)
        except Exception:
            counts[collection] = -1
            gaps.append(f"{collection}: collection unreachable or absent.")

    # Content exists but didn't surface → the loudest "being ignored" signal.
    if counts.get(TUTORIAL_RESEARCH_COLLECTION, 0) > 0 and "Tutorial research" not in surfaced:
        gaps.append(
            "tutorial_research holds content but nothing surfaced for this query — visual tags "
            "may not match, or similarity is too low."
        )
    if counts.get(TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION, 0) > 0 and "Technique reports" not in surfaced:
        gaps.append(
            "technique_research_outputs holds content but nothing visual-tagged surfaced for "
            "this query."
        )

    return VerifyReport(
        query=query, legs=legs, gaps=gaps, collection_counts=counts, project=project
    )
