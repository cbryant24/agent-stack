"""Tests for agent_output.py — chunking, embedding, and Qdrant ingestion (Phase 3)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yt_intelligence_pipeline.agent_output import _extract_video_id, ingest_to_qdrant
from yt_intelligence_pipeline.models import AgentModeResult, PipelineResult, TranscriptSource


# ── URL parsing ────────────────────────────────────────────────────────────────

class TestExtractVideoId:
    def test_standard_watch_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_youtu_be_url(self) -> None:
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_with_params(self) -> None:
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"

    def test_shorts_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError):
            _extract_video_id("https://www.youtube.com/channel/UCfoo")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_result(
    *,
    transcript: str = "Python async programming is powerful. " * 30,
    tags: list[str] | None = None,
    timestamp_entries: list[dict] | None = None,
) -> PipelineResult:
    return PipelineResult(
        video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_metadata={"title": "Python Async Tutorial", "channel": "Tech Channel",
                        "description": "Learn async", "duration_seconds": 600},
        cleaned_transcript=transcript,
        summary="Learn Python async programming.",
        key_takeaways=["Use async/await", "asyncio is powerful"],
        tags=tags or ["python", "async", "tutorial"],
        timestamp_entries=timestamp_entries or [],
        transcript_source=TranscriptSource.YOUTUBE_CAPTIONS,
    )


def _patch_runtime(tmp_path: Path) -> tuple:
    """Return mocks for the agent-runtime memory layer."""
    mock_store = MagicMock()
    mock_store.ensure_collection = AsyncMock()
    mock_store.upsert_points = AsyncMock()
    mock_store.upsert_multimodal_points = AsyncMock()

    return (mock_store,)


def _store_patches(store: MagicMock, tmp_path: Path) -> tuple:
    """Return the standard patch context managers for ingest_to_qdrant tests."""
    return (
        patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store),
        patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=tmp_path / "agent-data"),
    )


# ── Text-only ingestion ────────────────────────────────────────────────────────

class TestIngestToQdrantTextOnly:
    def test_returns_agent_mode_result(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)
        result = _make_result()

        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=tmp_path / "agent-data"):
            agent_result = asyncio.run(ingest_to_qdrant(result, collection_name="test_col"))

        assert isinstance(agent_result, AgentModeResult)
        assert agent_result.source_id == "youtube:dQw4w9WgXcQ"
        assert agent_result.collection_name == "test_col"
        assert agent_result.multimodal_points_upserted == 0

    def test_chunks_transcript_and_upserts(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)
        paragraphs = [f"Python asyncio tutorial content paragraph {i}. " * 20 for i in range(15)]
        long_transcript = "\n\n".join(paragraphs)
        result = _make_result(transcript=long_transcript)

        captured = []
        async def capture_upsert(col, points):
            captured.extend(points)
        store.upsert_points = capture_upsert

        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=tmp_path / "agent-data"):
            agent_result = asyncio.run(ingest_to_qdrant(result))

        assert agent_result.text_points_upserted > 1
        assert len(captured) > 1
        for p in captured:
            assert p.source_id == "youtube:dQw4w9WgXcQ"
            assert p.source_type == "youtube_tutorial"
            assert p.content_type == "text"
            assert "python" in p.domain_tags

    def test_persists_transcript_and_metadata(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)
        result = _make_result()
        agent_data = tmp_path / "agent-data"

        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=agent_data):
            asyncio.run(ingest_to_qdrant(result))

        source_dir = agent_data / "sources" / "youtube-tutorials" / "dQw4w9WgXcQ"
        assert (source_dir / "transcript.txt").exists()
        assert (source_dir / "metadata.json").exists()

        import json
        meta = json.loads((source_dir / "metadata.json").read_text())
        assert meta["source_id"] == "youtube:dQw4w9WgXcQ"
        assert meta["url"] == result.video_url

    def test_source_id_format(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)
        result = _make_result()
        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=tmp_path / "agent-data"):
            ar = asyncio.run(ingest_to_qdrant(result))
        assert ar.source_id.startswith("youtube:")


# ── Screenshot / multimodal ingestion ─────────────────────────────────────────

class TestIngestToQdrantWithScreenshots:
    def _make_png(self, path: Path) -> Path:
        import struct, zlib
        def chunk(name: bytes, data: bytes) -> bytes:
            c = struct.pack(">I", len(data)) + name + data
            return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
            + chunk(b"IEND", b"")
        )
        return path

    def test_multimodal_points_upserted_for_screenshots(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)

        img1 = self._make_png(tmp_path / "screenshot_001.png")
        img2 = self._make_png(tmp_path / "screenshot_002.png")

        result = _make_result(timestamp_entries=[
            {"timestamp_seconds": 30, "label": "Terminal showing pip install",
             "extracted_image_path": str(img1)},
            {"timestamp_seconds": 90, "label": "Code editor with async function",
             "extracted_image_path": str(img2)},
        ])

        captured_mm_calls: list[tuple] = []
        async def capture_mm_upsert(col, points, inputs):
            captured_mm_calls.append((col, points, inputs))
        store.upsert_multimodal_points = capture_mm_upsert

        agent_data = tmp_path / "agent-data"
        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=agent_data):
            ar = asyncio.run(ingest_to_qdrant(result))

        assert ar.multimodal_points_upserted == 2
        assert len(captured_mm_calls) == 1
        col, points, inputs = captured_mm_calls[0]
        assert col == "tutorial_research"
        assert len(points) == 2
        assert len(inputs) == 2

    def test_missing_screenshot_file_skipped(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)

        result = _make_result(timestamp_entries=[
            {"timestamp_seconds": 30, "label": "Ghost screenshot",
             "extracted_image_path": str(tmp_path / "ghost.png")},
        ])

        agent_data = tmp_path / "agent-data"
        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=agent_data):
            ar = asyncio.run(ingest_to_qdrant(result))

        assert ar.multimodal_points_upserted == 0
        store.upsert_multimodal_points.assert_not_called()

    def test_screenshots_copied_to_agent_data(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)

        img = self._make_png(tmp_path / "screenshot_001.png")
        result = _make_result(timestamp_entries=[
            {"timestamp_seconds": 30, "label": "Terminal", "extracted_image_path": str(img)},
        ])

        agent_data = tmp_path / "agent-data"
        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=agent_data):
            asyncio.run(ingest_to_qdrant(result))

        expected = (
            agent_data / "sources" / "youtube-tutorials" / "dQw4w9WgXcQ" / "screenshots" / "screenshot_001.png"
        )
        assert expected.exists()

    def test_multimodal_failure_degrades_gracefully(self, tmp_path: Path) -> None:
        (store,) = _patch_runtime(tmp_path)

        img = self._make_png(tmp_path / "screenshot_001.png")
        result = _make_result(timestamp_entries=[
            {"timestamp_seconds": 30, "label": "Terminal", "extracted_image_path": str(img)},
        ])

        async def failing_mm_upsert(col, points, inputs):
            raise RuntimeError("rate limit")
        store.upsert_multimodal_points = failing_mm_upsert

        agent_data = tmp_path / "agent-data"
        with patch("yt_intelligence_pipeline.agent_output.get_memory_store", return_value=store), \
             patch("yt_intelligence_pipeline.agent_output._agent_data_dir", return_value=agent_data):
            ar = asyncio.run(ingest_to_qdrant(result))

        # Text path succeeded; multimodal failed gracefully
        assert ar.text_points_upserted >= 1
        assert ar.multimodal_points_upserted == 0
        # Screenshot was still copied to agent-data
        expected = (
            agent_data / "sources" / "youtube-tutorials" / "dQw4w9WgXcQ" / "screenshots" / "screenshot_001.png"
        )
        assert expected.exists()
