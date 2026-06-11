from __future__ import annotations

import asyncio
import struct
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_runtime.memory.chunking import (
    DocumentChunk,
    chunk_document,
    chunk_document_with_structure,
)
from agent_runtime.memory.embeddings import MultimodalInput
from agent_runtime.memory.schema import MemoryPoint, SearchResult


def _qdrant_reachable() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:6333/healthz", timeout=1)
        return r.status_code == 200
    except Exception:
        return False


requires_qdrant = pytest.mark.skipif(
    not _qdrant_reachable(),
    reason="Qdrant not running on localhost:6333",
)


def _minimal_png() -> bytes:
    """Minimal valid 1×1 white PNG, under 100 bytes."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def test_png(tmp_path: Path) -> Path:
    p = tmp_path / "test.png"
    p.write_bytes(_minimal_png())
    return p


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


class TestMemoryStoreInspection:
    """Read-only inspection surface (get_collection_info / count_points /
    sample_points) used by the orchestrator's diagnose-only diagnostics. The Qdrant
    client is fully mocked — these never touch a live server."""

    def _store(self) -> Any:
        from agent_runtime.memory.store import MemoryStore
        store = MemoryStore("http://localhost:6333")
        store._client = MagicMock()
        return store

    def test_get_collection_info_returns_structure(self) -> None:
        async def run() -> None:
            store = self._store()
            # name= is a reserved MagicMock kwarg, so set the attribute explicitly
            coll = MagicMock()
            coll.name = "mem"
            store._client.get_collections = AsyncMock(return_value=MagicMock(collections=[coll]))
            vectors = MagicMock(size=1024)
            vectors.distance = MagicMock(value="Cosine")
            info = MagicMock(
                points_count=7, indexed_vectors_count=7,
                config=MagicMock(params=MagicMock(vectors=vectors)),
            )
            info.status = MagicMock(value="green")
            store._client.get_collection = AsyncMock(return_value=info)

            result = await store.get_collection_info("mem")
            assert result is not None
            assert result["points_count"] == 7
            assert result["vector_size"] == 1024
            assert result["distance"] == "Cosine"
            assert result["status"] == "green"

        asyncio.run(run())

    def test_get_collection_info_missing_returns_none(self) -> None:
        async def run() -> None:
            store = self._store()
            store._client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
            assert await store.get_collection_info("absent") is None

        asyncio.run(run())

    def test_count_points(self) -> None:
        async def run() -> None:
            store = self._store()
            store._client.count = AsyncMock(return_value=MagicMock(count=99))
            assert await store.count_points("mem") == 99

        asyncio.run(run())

    def test_sample_points_returns_id_payload_pairs(self) -> None:
        async def run() -> None:
            store = self._store()
            rec = MagicMock(id="pt-1", payload={"memory_type": "take"})
            store._client.scroll = AsyncMock(return_value=([rec], None))
            sample = await store.sample_points("mem", limit=3)
            assert sample == [("pt-1", {"memory_type": "take"})]

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


class TestMemoryStoreMultimodal:
    """Tests for upsert_multimodal_points and upsert_mixed — no external services required."""

    def test_length_mismatch_raises(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            store = MemoryStore("http://localhost:6333")
            point = _make_point()
            inp = MultimodalInput(text="hello")
            with pytest.raises(ValueError, match="same length"):
                await store.upsert_multimodal_points("col", [point], [inp, inp])
        asyncio.run(run())

    def test_empty_is_noop(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            store = MemoryStore("http://localhost:6333")
            # Returns early without touching the Qdrant client
            await store.upsert_multimodal_points("col", [], [])
        asyncio.run(run())

    def test_upsert_mixed_routes_to_sub_methods(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            store = MemoryStore("http://localhost:6333")

            text_calls: list[tuple] = []
            mm_calls: list[tuple] = []

            async def mock_upsert_points(col: str, pts: list) -> None:
                text_calls.append((col, pts))

            async def mock_upsert_mm(col: str, pts: list, inputs: list) -> None:
                mm_calls.append((col, pts, inputs))

            store.upsert_points = mock_upsert_points  # type: ignore[method-assign]
            store.upsert_multimodal_points = mock_upsert_mm  # type: ignore[method-assign]

            text_pts = [_make_point(text="text chunk")]
            mm_pts = [_make_point(text="caption", content_type="image_with_caption")]
            mm_inputs = [MultimodalInput(text="caption")]

            counts = await store.upsert_mixed("testcol", text_pts, mm_pts, mm_inputs)

            assert counts == {"text": 1, "multimodal": 1}
            assert len(text_calls) == 1
            assert text_calls[0][0] == "testcol"
            assert len(mm_calls) == 1
            assert mm_calls[0][0] == "testcol"
            assert len(mm_calls[0][1]) == 1
            assert len(mm_calls[0][2]) == 1

        asyncio.run(run())

    def test_upsert_mixed_skips_empty_lists(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.store import MemoryStore
            store = MemoryStore("http://localhost:6333")

            called = []

            async def mock_upsert_points(col: str, pts: list) -> None:
                called.append("text")

            async def mock_upsert_mm(col: str, pts: list, inputs: list) -> None:
                called.append("mm")

            store.upsert_points = mock_upsert_points  # type: ignore[method-assign]
            store.upsert_multimodal_points = mock_upsert_mm  # type: ignore[method-assign]

            counts = await store.upsert_mixed("col", [], [], [])

            assert counts == {"text": 0, "multimodal": 0}
            assert called == []

        asyncio.run(run())

    @requires_qdrant
    def test_upsert_multimodal_text_only_live(self) -> None:
        async def run() -> None:
            from unittest.mock import AsyncMock, MagicMock, patch
            from agent_runtime.memory.store import MemoryStore
            from ulid import ULID

            store = MemoryStore("http://localhost:6333")
            col = f"test_mm_{str(ULID()).lower()[:12]}"
            await store.ensure_collection(col, vector_size=1024)

            point = _make_point(text="hello multimodal world", content_type="text")
            inp = MultimodalInput(text="hello multimodal world")

            mock_client = MagicMock()
            mock_client.embed_multimodal = AsyncMock(return_value=[[0.5] * 1024])

            with patch(
                "agent_runtime.memory.store.get_embedding_client",
                return_value=mock_client,
            ):
                await store.upsert_multimodal_points(col, [point], [inp])

            from qdrant_client.models import Filter, FieldCondition, MatchValue
            result = await store._client.count(
                collection_name=col,
                count_filter=Filter(
                    must=[FieldCondition(key="source_id", match=MatchValue(value="src-001"))]
                ),
            )
            assert result.count == 1
            await store._client.delete_collection(col)

        asyncio.run(run())


class TestMultimodalInput:
    def test_text_only(self) -> None:
        m = MultimodalInput(text="hello")
        assert m.text == "hello"
        assert m.image_path is None

    def test_image_only(self, test_png: Path) -> None:
        m = MultimodalInput(image_path=test_png)
        assert m.image_path == test_png
        assert m.text is None

    def test_text_and_image(self, test_png: Path) -> None:
        m = MultimodalInput(text="caption", image_path=test_png)
        assert m.text == "caption"
        assert m.image_path == test_png

    def test_rejects_empty(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="At least one"):
            MultimodalInput()

    def test_rejects_nonexistent_image(self, tmp_path: Path) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="does not exist"):
            MultimodalInput(image_path=tmp_path / "ghost.png")

    def test_rejects_unsupported_extension(self, tmp_path: Path) -> None:
        from pydantic import ValidationError
        bad = tmp_path / "file.bmp"
        bad.write_bytes(b"BM")
        with pytest.raises(ValidationError, match="Unsupported image format"):
            MultimodalInput(image_path=bad)

    def test_to_voyage_content_text_only(self) -> None:
        from PIL import Image
        m = MultimodalInput(text="hello world")
        content = m.to_voyage_content()
        assert len(content) == 1
        assert content[0] == "hello world"

    def test_to_voyage_content_image_only(self, test_png: Path) -> None:
        from PIL import Image
        m = MultimodalInput(image_path=test_png)
        content = m.to_voyage_content()
        assert len(content) == 1
        assert isinstance(content[0], Image.Image)

    def test_to_voyage_content_text_and_image(self, test_png: Path) -> None:
        from PIL import Image
        m = MultimodalInput(text="caption", image_path=test_png)
        content = m.to_voyage_content()
        assert len(content) == 2
        assert content[0] == "caption"
        assert isinstance(content[1], Image.Image)


class TestEmbeddingClientMultimodal:
    def test_embed_multimodal_returns_correct_dimension(
        self, test_png: Path
    ) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient

            mock_response = MagicMock()
            mock_response.embeddings = [[0.1] * 1024, [0.2] * 1024]
            client = EmbeddingClient(api_key="test-key")
            client._client.multimodal_embed = AsyncMock(return_value=mock_response)

            inputs = [
                MultimodalInput(text="caption"),
                MultimodalInput(image_path=test_png),
            ]
            vectors = await client.embed_multimodal(inputs)
            assert len(vectors) == 2
            assert len(vectors[0]) == 1024
            assert len(vectors[1]) == 1024

        asyncio.run(run())

    def test_embed_multimodal_batches(self, test_png: Path) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient, _MULTIMODAL_BATCH_SIZE

            call_count = 0

            async def mock_mm_embed(inputs: list, **kwargs: Any) -> Any:
                nonlocal call_count
                call_count += 1
                resp = MagicMock()
                resp.embeddings = [[0.1] * 1024] * len(inputs)
                return resp

            client = EmbeddingClient(api_key="test-key")
            client._client.multimodal_embed = mock_mm_embed

            # _MULTIMODAL_BATCH_SIZE + 2 items → 2 batches
            inputs = [MultimodalInput(text=f"text {i}") for i in range(_MULTIMODAL_BATCH_SIZE + 2)]
            vectors = await client.embed_multimodal(inputs)
            assert len(vectors) == _MULTIMODAL_BATCH_SIZE + 2
            assert call_count == 2

        asyncio.run(run())

    def test_embed_multimodal_empty(self) -> None:
        async def run() -> None:
            from agent_runtime.memory.embeddings import EmbeddingClient
            client = EmbeddingClient(api_key="test-key")
            result = await client.embed_multimodal([])
            assert result == []

        asyncio.run(run())


class TestMemoryPointMultimodal:
    def test_default_content_type_text(self) -> None:
        point = _make_point()
        assert point.content_type == "text"

    def test_image_with_caption_fields(self, test_png: Path) -> None:
        point = _make_point(
            content_type="image_with_caption",
            image_path=str(test_png),
            caption="A screenshot of the UI",
        )
        assert point.content_type == "image_with_caption"
        assert point.caption == "A screenshot of the UI"

    def test_backward_compat_no_content_type(self) -> None:
        # Simulates a payload loaded from Qdrant that predates the field
        payload = {
            "text": "old point",
            "source_id": "old-src",
            "source_type": "web_page",
            "processed_by_agent": "test",
            "processed_in_run": "run-old",
        }
        point = MemoryPoint.from_qdrant_payload(str(uuid.uuid4()), payload)
        assert point.content_type == "text"

    def test_to_qdrant_point_includes_content_type(self, test_png: Path) -> None:
        point = _make_point(
            content_type="image_with_caption",
            image_path=str(test_png),
            caption="test caption",
        )
        qp = point.to_qdrant_point([0.1] * 3)
        assert qp.payload["content_type"] == "image_with_caption"
        assert qp.payload["caption"] == "test caption"
