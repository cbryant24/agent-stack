from __future__ import annotations

from agent_runtime.memory import MemoryStore, get_memory_store
from agent_runtime.memory.store import filter_by_source_type

from tutorial_research.models import RetrievedChunk


async def retrieve_chunks(
    collection: str,
    query: str,
    limit: int = 10,
    store: MemoryStore | None = None,
) -> list[RetrievedChunk]:
    ms = store or get_memory_store()
    results = await ms.search(
        collection,
        query_text=query,
        limit=limit,
        filters=filter_by_source_type("youtube_tutorial"),
    )
    return [
        RetrievedChunk(
            score=r.score,
            source_id=r.point.source_id,
            content=r.point.text,
            source_title=r.point.source_title,
            source_url=r.point.source_url,
            chunk_index=r.point.chunk_index,
        )
        for r in results
    ]
