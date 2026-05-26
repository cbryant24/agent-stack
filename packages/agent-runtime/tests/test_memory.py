from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_runtime.memory.chunking import (
    DocumentChunk,
    chunk_document,
    chunk_document_with_structure,
)
from agent_runtime.memory.schema import MemoryPoint, SearchResult

from tests.conftest import requires_qdrant


@pytest.fixture(autouse=True)
def _env(fake_env: None) -> None:
    pass


def _make_point(**kwargs: Any) -> MemoryPoint:
    defaults = dict(
        text="sample text",
        source_id="src-001",
        source_type="web_page",
        processed_by_agent="test-agent",
        processed_in_run="run-001",
    )
    defaults.update(kwargs)
    return MemoryPoint(**defaults)


class TestChunking:
    def test_empty_text(self) -> None:
        assert chunk_document("") == []

    def test_short_text_single_chunk(self) -> None:
        text = "Hello world. This is a short document."
        chunks = chunk_document(text, target_tokens=512)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].token_count > 0
        assert "Hello world" in chunks[0].text

    def test_chunk_indices_sequential(self) -> None:
        long_text = "\n\n".join([f"Paragraph {i}. " * 30 for i in range(10)])
        chunks = chunk_document(long_text, target_tokens=100, overlap_tokens=10)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_char_offsets_non_negative(self) -> None:
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunk_document(text, target_tokens=512)
        for chunk in chunks:
            assert chunk.start_char >= 0
            assert chunk.end_char <= len(text)

    def test_chunk_token_count_within_target(self) -> None:
        # Large text with clear paragraph breaks
        paragraphs = [f"This is sentence {i} in paragraph {i}. " * 20 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_document(text, target_tokens=200, overlap_tokens=20)
        # Each chunk should not massively exceed target (allow 2x for edge cases)
        for chunk in chunks:
            assert chunk.token_count <= 400, f"Chunk {chunk.chunk_index} too large: {chunk.token_count}"

    def test_structure_preserves_heading(self) -> None:
        text = "Introduction text.\n\nSection details here."
        headings = [(0, "## Introduction"), (19, "## Section")]
        chunks = chunk_document_with_structure(text, headings, target_tokens=512)
        assert len(chunks) > 0
        assert any("##" in c.heading_context for c in chunks)

    def test_structure_no_headings(self) -> None:
        text = "Just some text without headings."
        chunks = chunk_document_with_structure(text, [], target_tokens=512)
        assert len(chunks) == 1
        assert chunks[0].heading_context == ""


class TestMemoryPointSchema:
    def test_to_qdrant_point(self) -> None:
        point = _make_point()
        qdrant_point = point.to_qdrant_point([0.1, 0.2, 0.3])
        assert qdrant_point.vector == [0.1, 0.2, 0.3]
        assert "text" in qdrant_point.payload
        assert qdrant_point.payload["source_id"] == "src-001"

    def test_uuid_auto_generated(self) -> None:
        p1 = _make_point()
        p2 = _make_point()
        assert p1.id != p2.id

    def test_search_result_model(self) -> None:
        point = _make_point()
        result = SearchResult(point=point, score=0.95)
        assert result.score == pytest.approx(0.95)


class TestEmbeddingClientMocked:
    def test_embed_returns_correct_dimension(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient

            mock_response = MagicMock()
            mock_response.embeddings = [[0.1] * 1024, [0.2] * 1024]

            client = EmbeddingClient(api_key="test-key")
            client._client.embed = AsyncMock(return_value=mock_response)

            vectors = await client.embed(["text one", "text two"])
            assert len(vectors) == 2
            assert len(vectors[0]) == 1024

        asyncio.run(run())

    def test_embed_batches_large_input(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient, _BATCH_SIZE

            call_count = 0

            async def mock_embed(texts: list, **kwargs: Any) -> Any:
                nonlocal call_count
                call_count += 1
                resp = MagicMock()
                resp.embeddings = [[0.1] * 1024] * len(texts)
                return resp

            client = EmbeddingClient(api_key="test-key")
            client._client.embed = mock_embed

            texts = ["text"] * (_BATCH_SIZE + 10)
            vectors = await client.embed(texts)
            assert len(vectors) == _BATCH_SIZE + 10
            assert call_count == 2  # Two batches

        asyncio.run(run())


@requires_qdrant
class TestMemoryStoreLive:
    def _collection_name(self) -> str:
        from ulid import ULID
        return f"test_{str(ULID()).lower()[:12]}"

    def test_ensure_collection_idempotent(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            store = MemoryStore("http://localhost:6333")
            col = self._collection_name()
            await store.ensure_collection(col)
            await store.ensure_collection(col)  # must not raise
            await store._client.delete_collection(col)

        asyncio.run(run())

    def test_upsert_and_search(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient
            from agent_runtime.memory.store import MemoryStore

            # Mock embeddings to avoid real API calls
            mock_embed_return = [[float(i) / 1024] * 1024 for i in range(3)]
            mock_embed_return[0] = [1.0 / 1024] * 1024   # "python" doc
            mock_embed_return[1] = [0.01 / 1024] * 1024  # "unrelated" doc
            query_vec = [1.0 / 1024] * 1024               # "python" query

            store = MemoryStore("http://localhost:6333")
            col = self._collection_name()
            await store.ensure_collection(col, vector_size=1024)

            points = [
                _make_point(text="Python async programming guide", source_id="doc-1"),
                _make_point(text="Recipe for chocolate cake", source_id="doc-2"),
            ]

            embed_call = 0

            async def mock_embed(texts: list, **kwargs: Any) -> Any:
                nonlocal embed_call
                resp = MagicMock()
                if embed_call == 0:
                    resp.embeddings = mock_embed_return[:len(texts)]
                else:
                    resp.embeddings = [query_vec]
                embed_call += 1
                return resp

            store._client.__class__  # touch to ensure initialized

            with patch.object(
                __import__("agent_runtime.memory.embeddings", fromlist=["EmbeddingClient"]).EmbeddingClient,
                "embed",
                new=AsyncMock(side_effect=[
                    mock_embed_return[:2],  # upsert call
                    [query_vec],            # search call
                ]),
            ):
                from agent_runtime.memory import get_embedding_client
                orig = get_embedding_client.__wrapped__ if hasattr(get_embedding_client, "__wrapped__") else None
                client = EmbeddingClient.__new__(EmbeddingClient)
                client._client = MagicMock()
                client._client.embed = AsyncMock(side_effect=[
                    MagicMock(embeddings=mock_embed_return[:2]),
                    MagicMock(embeddings=[query_vec]),
                ])

                with patch("agent_runtime.memory.store.get_embedding_client", return_value=client):
                    await store.upsert_points(col, points)
                    results = await store.search(col, "python programming", limit=2)

                assert len(results) > 0
            await store._client.delete_collection(col)

        asyncio.run(run())

    def test_delete_by_source(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            from agent_runtime.memory.embeddings import EmbeddingClient

            store = MemoryStore("http://localhost:6333")
            col = self._collection_name()
            await store.ensure_collection(col, vector_size=3)

            # Use tiny vectors to avoid Voyage API calls
            from qdrant_client.models import PointStruct
            pts = [
                PointStruct(id=str(uuid.uuid4()), vector=[0.1, 0.2, 0.3],
                            payload={"source_id": "to-delete", "text": "x"}),
                PointStruct(id=str(uuid.uuid4()), vector=[0.4, 0.5, 0.6],
                            payload={"source_id": "keep", "text": "y"}),
            ]
            await store._client.upsert(collection_name=col, points=pts)

            await store.delete_by_source(col, "to-delete")

            from qdrant_client.models import Filter, FieldCondition, MatchValue
            remaining = await store._client.count(
                collection_name=col,
                count_filter=Filter(must=[
                    FieldCondition(key="source_id", match=MatchValue(value="to-delete"))
                ]),
            )
            assert remaining.count == 0
            await store._client.delete_collection(col)

        asyncio.run(run())

    def test_filter_by_source_type(self) -> None:
        from agent_runtime.memory.store import filter_by_source_type
        f = filter_by_source_type("web_page")
        assert f.must[0].key == "source_type"
