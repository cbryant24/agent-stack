from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from agent_runtime.memory.embeddings import EmbeddingClient, MultimodalInput, get_embedding_client
from agent_runtime.memory.schema import MemoryPoint, SearchResult
from agent_runtime.tracing.decorators import record_memory_query, record_memory_write

_UPSERT_BATCH_SIZE = 100


def filter_by_source_type(source_type: str) -> Filter:
    return Filter(
        must=[FieldCondition(key="source_type", match=MatchValue(value=source_type))]
    )


def filter_by_domain_tags(tags: list[str]) -> Filter:
    return Filter(
        must=[FieldCondition(key="domain_tags", match=MatchAny(any=tags))]
    )


def filter_after(dt: datetime) -> Filter:
    return Filter(
        must=[
            FieldCondition(
                key="processed_at",
                range=Range(gte=dt.isoformat()),
            )
        ]
    )


class MemoryStore:
    def __init__(self, url: str) -> None:
        self._client = AsyncQdrantClient(url=url)

    # ── Low-level public surface ─────────────────────────────────────────────
    # These methods expose raw Qdrant operations for components (like
    # UserKnowledgeStore) that manage their own payload schema and cannot use
    # the higher-level upsert_points / search methods, which assume MemoryPoint.

    @property
    def embedding_client(self) -> EmbeddingClient:
        """Return the shared embedding client."""
        return get_embedding_client()

    async def upsert_raw_points(
        self, collection: str, points: list[PointStruct]
    ) -> None:
        """Upsert pre-built PointStruct objects without re-embedding."""
        for i in range(0, len(points), _UPSERT_BATCH_SIZE):
            await self._client.upsert(
                collection_name=collection,
                points=points[i : i + _UPSERT_BATCH_SIZE],
            )
        record_memory_write(collection, len(points))

    async def set_payload(
        self, collection: str, point_id: str, payload: dict[str, Any]
    ) -> None:
        """Update specific payload fields on an existing point without re-embedding."""
        await self._client.set_payload(
            collection_name=collection,
            payload=payload,
            points=[point_id],
        )

    async def retrieve_points(
        self, collection: str, point_ids: list[str]
    ) -> list[Any]:
        """Fetch points by ID. Returns raw qdrant Record objects (.id, .payload)."""
        return await self._client.retrieve(
            collection_name=collection,
            ids=point_ids,
            with_payload=True,
        )

    async def query_by_vector(
        self,
        collection: str,
        vector: list[float],
        *,
        limit: int = 10,
        filters: Filter | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Search using a pre-computed vector.

        Returns a list of (point_id, score, payload) tuples. For use by
        components that manage their own payload schema.
        """
        results = await self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            query_filter=filters,
            with_payload=True,
        )
        return [
            (str(hit.id), hit.score, hit.payload or {})
            for hit in results.points
        ]

    # ────────────────────────────────────────────────────────────────────────

    async def ensure_collection(self, name: str, vector_size: int = 1024) -> None:
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}
        if name not in existing_names:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    async def upsert_points(
        self, collection: str, points: list[MemoryPoint]
    ) -> None:
        embedder = get_embedding_client()
        texts = [p.text for p in points]
        vectors = await embedder.embed(texts, input_type="document")

        qdrant_points = [
            p.to_qdrant_point(v) for p, v in zip(points, vectors)
        ]

        for i in range(0, len(qdrant_points), _UPSERT_BATCH_SIZE):
            batch = qdrant_points[i : i + _UPSERT_BATCH_SIZE]
            await self._client.upsert(collection_name=collection, points=batch)

        record_memory_write(collection, len(points))

    async def upsert_multimodal_points(
        self,
        collection: str,
        points: list[MemoryPoint],
        inputs: list[MultimodalInput],
    ) -> None:
        """Upsert points whose embeddings come from multimodal inputs (text+image or image-only).

        `points` and `inputs` must be parallel — points[i] is embedded from inputs[i].
        """
        if len(points) != len(inputs):
            raise ValueError(
                f"points and inputs must be the same length, "
                f"got {len(points)} and {len(inputs)}"
            )
        if not points:
            return

        embedder = get_embedding_client()
        vectors = await embedder.embed_multimodal(inputs, input_type="document")

        qdrant_points = [p.to_qdrant_point(v) for p, v in zip(points, vectors)]
        for i in range(0, len(qdrant_points), _UPSERT_BATCH_SIZE):
            await self._client.upsert(
                collection_name=collection,
                points=qdrant_points[i : i + _UPSERT_BATCH_SIZE],
            )

        record_memory_write(collection, len(points))

    async def upsert_mixed(
        self,
        collection: str,
        text_points: list[MemoryPoint],
        multimodal_points: list[MemoryPoint],
        multimodal_inputs: list[MultimodalInput],
    ) -> dict[str, int]:
        """Upsert both text-only and multimodal points to the same collection.

        Returns counts: {"text": N, "multimodal": M}.
        """
        if text_points:
            await self.upsert_points(collection, text_points)
        if multimodal_points:
            await self.upsert_multimodal_points(collection, multimodal_points, multimodal_inputs)
        return {"text": len(text_points), "multimodal": len(multimodal_points)}

    async def search(
        self,
        collection: str,
        query_text: str,
        *,
        limit: int = 10,
        filters: Filter | None = None,
    ) -> list[SearchResult]:
        embedder = get_embedding_client()
        [query_vector] = await embedder.embed([query_text], input_type="query")

        results = await self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            query_filter=filters,
            with_payload=True,
        )

        search_results: list[SearchResult] = []
        for hit in results.points:
            point = MemoryPoint.from_qdrant_payload(str(hit.id), hit.payload or {})
            search_results.append(SearchResult(point=point, score=hit.score))

        record_memory_query(collection, query_text, len(search_results))
        return search_results

    async def delete_by_source(self, collection: str, source_id: str) -> None:
        await self._client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
            ),
        )

    async def search_multimodal(
        self,
        collection: str,
        query_text: str | None = None,
        query_image_path: Path | None = None,
        *,
        limit: int = 10,
        filters: Filter | None = None,
    ) -> list[SearchResult]:
        from agent_runtime.memory.embeddings import MultimodalInput

        query_input = MultimodalInput(text=query_text, image_path=query_image_path)
        embedder = get_embedding_client()
        [query_vector] = await embedder.embed_multimodal([query_input], input_type="query")

        results = await self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            query_filter=filters,
            with_payload=True,
        )

        search_results: list[SearchResult] = []
        for hit in results.points:
            point = MemoryPoint.from_qdrant_payload(str(hit.id), hit.payload or {})
            search_results.append(SearchResult(point=point, score=hit.score))

        record_memory_query(collection, str(query_text or query_image_path), len(search_results))
        return search_results


@lru_cache(maxsize=1)
def get_memory_store() -> MemoryStore:
    from agent_runtime.config import get_config
    return MemoryStore(url=get_config().qdrant_url)
