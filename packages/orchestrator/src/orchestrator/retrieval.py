"""Domain-scoped knowledge retrieval for the orchestrator.

Generalizes the reference implementation in
``tutorial_research/retrieval.py``: each ``search_knowledge`` call targets exactly
ONE embedding space (text / ``voyage-3-large``), co-queries ``user_knowledge`` with
the established 1.25x authority boost (capped), and degrades gracefully to ``[]``
when a collection is missing. Scores are never merged across embedding spaces.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from qdrant_client.models import FieldCondition, Filter, MatchValue

from agent_runtime import MemoryStore, UserKnowledgeStore, get_memory_store
from agent_runtime.memory.store import filter_by_source_type

# Reuse the tutorial-research reference constants directly (single source of truth).
from tutorial_research.retrieval import (
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
    _USER_KNOWLEDGE_CAP_FRACTION,
    retrieve_chunks,
)

logger = logging.getLogger(__name__)

# Sentinel used by UserKnowledgeStore to mark active (non-superseded) entries.
_ACTIVE_SENTINEL = ""

Domain = Literal[
    "tutorial_research",
    "music_curation_memory",
    "voiceover_direction_memory",
    "visual_generation_memory",
    "technique_research_outputs",
    "langgraph_mechanics",
]


@dataclass
class KnowledgeResult:
    score: float
    label: str
    snippet: str
    collection: str


@dataclass(frozen=True)
class _DomainSpec:
    # Either a (collection, optional source_type) pair queried as text + a boosted
    # user_knowledge co-query, OR a user_knowledge-native domain filter (uk_domain).
    collection: str | None = None
    source_type: str | None = None
    co_query_user_knowledge: bool = True
    uk_domain: str | None = None


# All domains are text (voyage-3-large) spaces — one embedding space per call.
# (concept-script is stateless and owns no collection, so it has no domain here.)
DOMAINS: dict[str, _DomainSpec] = {
    # Literal reuse of tutorial-research's retrieve_chunks (source_type filter +
    # boosted user_knowledge co-query + graceful degrade already baked in).
    "tutorial_research": _DomainSpec(collection="tutorial_research", source_type="youtube_tutorial"),
    "music_curation_memory": _DomainSpec(collection="music_curation_memory"),
    "voiceover_direction_memory": _DomainSpec(collection="voiceover_direction_memory"),
    "visual_generation_memory": _DomainSpec(collection="visual_generation_memory"),
    "technique_research_outputs": _DomainSpec(collection="technique_research_outputs"),
    # This domain *is* user_knowledge, so there is no separate co-query / boost.
    "langgraph_mechanics": _DomainSpec(uk_domain="langgraph_mechanics", co_query_user_knowledge=False),
}


async def _fetch_user_knowledge(
    store: MemoryStore, query: str, *, limit: int
) -> list[KnowledgeResult]:
    """Boosted user_knowledge co-query. Returns [] on any error (collection absent,
    Qdrant down, embedding failure) so retrieval degrades gracefully."""
    try:
        current_only = Filter(
            must=[FieldCondition(key="superseded_by", match=MatchValue(value=_ACTIVE_SENTINEL))]
        )
        embedder = store.embedding_client
        [vector] = await embedder.embed([query], input_type="query")
        raw = await store.query_by_vector(
            USER_KNOWLEDGE_COLLECTION, vector, limit=limit, filters=current_only
        )
        return [
            KnowledgeResult(
                score=score * USER_KNOWLEDGE_SCORE_MULTIPLIER,
                label=payload.get("domain", "user_knowledge"),
                snippet=payload.get("statement", ""),
                collection=USER_KNOWLEDGE_COLLECTION,
            )
            for _pid, score, payload in raw
        ]
    except Exception:
        logger.debug("user_knowledge co-query skipped (collection may not exist yet)")
        return []


async def _search_collection(
    collection: str,
    query: str,
    *,
    source_type: str | None,
    co_query_user_knowledge: bool,
    limit: int,
    store: MemoryStore,
) -> list[KnowledgeResult]:
    """Text search over one collection (voyage-3-large) merged with an optional
    capped, boosted user_knowledge co-query. Mirrors retrieve_chunks' merge."""
    uk_limit = max(1, round(limit * _USER_KNOWLEDGE_CAP_FRACTION))
    filters = filter_by_source_type(source_type) if source_type else None

    async def _primary() -> list[KnowledgeResult]:
        try:
            results = await store.search(collection, query_text=query, limit=limit, filters=filters)
            return [
                KnowledgeResult(
                    score=r.score,
                    label=r.point.source_title or r.point.source_id,
                    snippet=r.point.text,
                    collection=collection,
                )
                for r in results
            ]
        except Exception:
            logger.debug("primary collection query skipped (collection may not exist): %s", collection)
            return []

    if co_query_user_knowledge:
        primary, uk = await asyncio.gather(
            _primary(), _fetch_user_knowledge(store, query, limit=uk_limit)
        )
    else:
        primary, uk = await _primary(), []

    merged = primary + uk
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:limit]


async def search_knowledge(
    query: str,
    domain: Domain,
    *,
    limit: int = 8,
    store: MemoryStore | None = None,
) -> list[KnowledgeResult]:
    """Semantic search scoped to one knowledge domain (one embedding space).

    Always co-queries user_knowledge with the 1.25x authority boost, except for
    the langgraph_mechanics domain which IS user_knowledge (filtered by domain).
    """
    spec = DOMAINS.get(domain)
    if spec is None:
        raise ValueError(f"Unknown knowledge domain: {domain!r}. Valid: {sorted(DOMAINS)}")

    ms = store or get_memory_store()

    # user_knowledge-native domain (e.g. langgraph_mechanics).
    if spec.uk_domain is not None:
        try:
            uks = UserKnowledgeStore(ms)
            hits = await uks.search(query, domain=spec.uk_domain, limit=limit)
            return [
                KnowledgeResult(
                    score=h.score, label=h.domain, snippet=h.statement,
                    collection=USER_KNOWLEDGE_COLLECTION,
                )
                for h in hits
            ]
        except Exception:
            logger.debug("user_knowledge domain query skipped: %s", spec.uk_domain)
            return []

    assert spec.collection is not None

    # tutorial_research: reuse the reference retrieve_chunks verbatim.
    if domain == "tutorial_research":
        chunks = await retrieve_chunks(spec.collection, query, limit=limit, store=ms)
        return [
            KnowledgeResult(
                score=c.score,
                label=c.source_title or c.source_id,
                snippet=c.content,
                collection=c.collection_name or spec.collection,
            )
            for c in chunks
        ]

    return await _search_collection(
        spec.collection,
        query,
        source_type=spec.source_type,
        co_query_user_knowledge=spec.co_query_user_knowledge,
        limit=limit,
        store=ms,
    )
