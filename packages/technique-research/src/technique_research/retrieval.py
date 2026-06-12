"""Toolset read + the three-collection check-before-delegate.

The editing_toolset read is the cold-start dependency: the identification and
curation prompts are grounded in whatever `user_knowledge` domain=editing_toolset
holds at runtime. The toolset is NEVER hardcoded here — this read is its only
source.

The check is the economizing step: per identified domain, query the three
knowledge layers in parallel; if ANY clears its threshold, answer locally and
spend no delegation. Every leg emits a `delegation_decision` trace event for
post-hoc threshold tuning — the music-curation pattern, no new mechanism.
"""
from __future__ import annotations

import asyncio
import logging

from agent_runtime import MemoryStore, UserKnowledgeStore
from agent_runtime.tracing import record_delegation_decision

# Reuse tutorial-research's boosted, capped, graceful-degrading three-leg read
# verbatim for the tutorial_research leg (exactly as orchestrator/retrieval.py does).
from tutorial_research.retrieval import retrieve_chunks

from technique_research.constants import (
    CHECK_LIMIT,
    CHECK_TECHNIQUE_OUTPUTS_THRESHOLD,
    CHECK_TUTORIAL_THRESHOLD,
    CHECK_USER_KNOWLEDGE_THRESHOLD,
    EDITING_TOOLSET_DOMAIN,
    TECHNIQUE_OUTPUTS_COLLECTION,
    TOOLSET_LIMIT,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
)
from technique_research.models import CheckOutcome, TechniqueDomain
from technique_research.store import TechniqueResearchStore

logger = logging.getLogger(__name__)


async def read_editing_toolset(query: str, uks: UserKnowledgeStore) -> str:
    """Retrieve the director's toolset facts for `query` and format them for the
    prompt. Returns '' when the domain is empty/unavailable (degrades gracefully).
    """
    try:
        hits = await uks.search(query, domain=EDITING_TOOLSET_DOMAIN, limit=TOOLSET_LIMIT)
    except Exception:
        logger.debug("editing_toolset read skipped (collection may not exist yet)")
        return ""
    if not hits:
        return ""
    lines = [f"- {h.statement}" for h in hits]
    return "The director's editing toolset (from user_knowledge):\n" + "\n".join(lines)


async def _max_user_knowledge_score(
    uks: UserKnowledgeStore, query: str, *, limit: int
) -> float:
    try:
        hits = await uks.search(query, limit=limit)
    except Exception:
        return 0.0
    return max((h.score for h in hits), default=0.0)


async def _max_tutorial_score(memory_store: MemoryStore, query: str, *, limit: int) -> float:
    try:
        chunks = await retrieve_chunks(
            TUTORIAL_RESEARCH_COLLECTION, query, limit=limit, store=memory_store
        )
    except Exception:
        return 0.0
    return max((c.score for c in chunks), default=0.0)


async def check_domain(
    domain: TechniqueDomain,
    store: TechniqueResearchStore,
    memory_store: MemoryStore,
    uks: UserKnowledgeStore,
) -> CheckOutcome:
    """Decide local vs delegate for one domain across the three collections."""
    query = domain.search_query

    own_pairs, tutorial_score, uk_score = await asyncio.gather(
        store.search_findings(query, limit=CHECK_LIMIT),
        _max_tutorial_score(memory_store, query, limit=CHECK_LIMIT),
        _max_user_knowledge_score(uks, query, limit=CHECK_LIMIT),
    )
    own_score = max((s for s, _ in own_pairs), default=0.0)

    legs = [
        (TECHNIQUE_OUTPUTS_COLLECTION, own_score, CHECK_TECHNIQUE_OUTPUTS_THRESHOLD),
        (TUTORIAL_RESEARCH_COLLECTION, tutorial_score, CHECK_TUTORIAL_THRESHOLD),
        (USER_KNOWLEDGE_COLLECTION, uk_score, CHECK_USER_KNOWLEDGE_THRESHOLD),
    ]
    has_local = any(score >= threshold for _, score, threshold in legs)
    decision = "local" if has_local else "delegate"

    for collection, score, threshold in legs:
        record_delegation_decision(
            trigger_type="technique_check",
            collection=collection,
            query=query,
            local_max_score=score,
            threshold=threshold,
            decision="local" if score >= threshold else "delegate",
        )

    return CheckOutcome(
        domain_name=domain.name,
        decision=decision,
        technique_outputs_score=own_score,
        tutorial_score=tutorial_score,
        user_knowledge_score=uk_score,
    )
