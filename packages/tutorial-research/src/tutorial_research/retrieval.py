from __future__ import annotations

import asyncio
import logging

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from agent_runtime.memory import MemoryStore, get_memory_store

from tutorial_research.models import RetrievedChunk

logger = logging.getLogger(__name__)

# tutorial_research holds both YouTube-tutorial chunks and bulk-ingested course-doc chunks
# (see docs_ingest.py). Both are tutorial-derived technique, so retrieval surfaces both.
_TUTORIAL_SOURCE_TYPES = ["youtube_tutorial", "course_doc"]


def _filter_by_source_types(source_types: list[str]) -> Filter:
    return Filter(
        must=[FieldCondition(key="source_type", match=MatchAny(any=source_types))]
    )

USER_KNOWLEDGE_SCORE_MULTIPLIER = 1.25
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
_USER_KNOWLEDGE_CAP_FRACTION = 0.30

# Sentinel used by UserKnowledgeStore to mark active (non-superseded) entries.
_ACTIVE_SENTINEL = ""


async def _fetch_user_knowledge_chunks(
    store: MemoryStore,
    query: str,
    *,
    limit: int,
) -> list[RetrievedChunk]:
    """Query user_knowledge and return scored chunks.

    Returns [] on any error (collection not found, Qdrant down, etc.) so retrieval
    degrades gracefully when user_knowledge is not yet populated.
    """
    try:
        current_only_filter = Filter(
            must=[FieldCondition(key="superseded_by", match=MatchValue(value=_ACTIVE_SENTINEL))]
        )
        embedder = store.embedding_client
        [vector] = await embedder.embed([query], input_type="query")
        raw = await store.query_by_vector(
            USER_KNOWLEDGE_COLLECTION,
            vector,
            limit=limit,
            filters=current_only_filter,
        )
        return [
            RetrievedChunk(
                score=score * USER_KNOWLEDGE_SCORE_MULTIPLIER,
                source_id=payload.get("entry_id", pid),
                content=payload.get("statement", ""),
                source_title=payload.get("domain"),
                source_url=payload.get("source_ref"),
                collection_name=USER_KNOWLEDGE_COLLECTION,
            )
            for pid, score, payload in raw
        ]
    except Exception:
        logger.debug("user_knowledge query skipped (collection may not exist yet)")
        return []


async def retrieve_chunks(
    collection: str,
    query: str,
    limit: int = 10,
    store: MemoryStore | None = None,
) -> list[RetrievedChunk]:
    """Retrieve relevant chunks from the tutorial collection and user_knowledge.

    Both collections are queried in parallel. user_knowledge hits receive a
    USER_KNOWLEDGE_SCORE_MULTIPLIER boost (1.25×) and are capped at 30% of the
    requested limit. When user_knowledge is unavailable the query degrades silently.
    """
    ms = store or get_memory_store()
    uk_limit = max(1, round(limit * _USER_KNOWLEDGE_CAP_FRACTION))

    tutorial_task = ms.search(
        collection,
        query_text=query,
        limit=limit,
        filters=_filter_by_source_types(_TUTORIAL_SOURCE_TYPES),
    )
    uk_task = _fetch_user_knowledge_chunks(ms, query, limit=uk_limit)

    tutorial_results, uk_chunks = await asyncio.gather(tutorial_task, uk_task)

    tutorial_chunks = [
        RetrievedChunk(
            score=r.score,
            source_id=r.point.source_id,
            content=r.point.text,
            source_title=r.point.source_title,
            source_url=r.point.source_url,
            chunk_index=r.point.chunk_index,
            collection_name=collection,
        )
        for r in tutorial_results
    ]

    merged = tutorial_chunks + uk_chunks
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:limit]
