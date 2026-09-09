"""Thin wrapper around the shared Voyage embedding client.

Uses `get_embedding_client()` so there's exactly one voyageai client per
process (agent-runtime already `@lru_cache`s it).
"""

from __future__ import annotations

from agent_runtime.memory.embeddings import get_embedding_client


async def embed_summaries(texts: list[str]) -> list[list[float]]:
    """Return L2-normalized 1024-d Voyage vectors for each input string."""
    if not texts:
        return []
    client = get_embedding_client()
    return await client.embed(texts, input_type="document")
