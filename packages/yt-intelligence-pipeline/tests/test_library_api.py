"""Tests for the library entry point (Phase 2)."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yt_intelligence_pipeline import process_video, process_video_sync
from yt_intelligence_pipeline.models import (
    AgentModeResult,
    PipelineResult,
    TranscriptSource,
)


class TestProcessVideoSignature:
    def test_is_coroutine_function(self) -> None:
        import asyncio
        assert asyncio.iscoroutinefunction(process_video)

    def test_has_expected_parameters(self) -> None:
        sig = inspect.signature(process_video)
        params = sig.parameters
        assert "url" in params
        assert "use_screenshots" in params
        assert "human_output" in params
        assert "agent_output" in params
        assert "config" in params
        assert "collection_name" in params

    def test_defaults(self) -> None:
        sig = inspect.signature(process_video)
        assert sig.parameters["use_screenshots"].default is True
        assert sig.parameters["human_output"].default is True
        assert sig.parameters["agent_output"].default is False
        assert sig.parameters["collection_name"].default == "tutorial_research"

    def test_sync_wrapper_exists(self) -> None:
        assert callable(process_video_sync)


class TestProcessVideoMocked:
    """process_video with all external calls mocked."""

    def _make_pipeline_result(self, tmp_path: Path) -> PipelineResult:
        return PipelineResult(
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_metadata={"title": "Test Video", "channel": "Test Channel",
                            "description": "", "duration_seconds": 120},
            cleaned_transcript="This is a cleaned transcript about Python.",
            summary="A test video summary.",
            key_takeaways=["Takeaway one", "Takeaway two"],
            tags=["python", "tutorial"],
            timestamp_entries=[],
            human_output_path=tmp_path / "test-video.md",
            transcript_source=TranscriptSource.YOUTUBE_CAPTIONS,
        )

    def test_human_only_mode_calls_run_pipeline(self, tmp_path: Path) -> None:
        expected = self._make_pipeline_result(tmp_path)
        with patch("yt_intelligence_pipeline.pipeline.run_pipeline", return_value=expected) as mock_run, \
             patch("yt_intelligence_pipeline.config.load_and_validate_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(obsidian_output_path=tmp_path)
            result = asyncio.run(process_video(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                human_output=True,
                agent_output=False,
            ))
        mock_run.assert_called_once()
        assert result.agent_output is None

    def test_agent_mode_calls_ingest(self, tmp_path: Path) -> None:
        expected = self._make_pipeline_result(tmp_path)
        agent_result = AgentModeResult(
            collection_name="tutorial_research",
            text_points_upserted=5,
            multimodal_points_upserted=0,
            source_id="youtube:dQw4w9WgXcQ",
        )
        with patch("yt_intelligence_pipeline.pipeline.run_pipeline", return_value=expected), \
             patch("yt_intelligence_pipeline.config.load_and_validate_config") as mock_cfg, \
             patch("yt_intelligence_pipeline.agent_output.ingest_to_qdrant",
                   new=AsyncMock(return_value=agent_result)):
            mock_cfg.return_value = MagicMock(obsidian_output_path=tmp_path)
            result = asyncio.run(process_video(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                human_output=True,
                agent_output=True,
            ))
        assert result.agent_output is not None
        assert result.agent_output.source_id == "youtube:dQw4w9WgXcQ"
        assert result.agent_output.text_points_upserted == 5

    def test_returns_pipeline_result_type(self, tmp_path: Path) -> None:
        expected = self._make_pipeline_result(tmp_path)
        with patch("yt_intelligence_pipeline.pipeline.run_pipeline", return_value=expected), \
             patch("yt_intelligence_pipeline.config.load_and_validate_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(obsidian_output_path=tmp_path)
            result = asyncio.run(process_video(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ))
        assert isinstance(result, PipelineResult)


class TestCLIOutputFlag:
    """Verify CLI accepts --output flag without breaking."""

    def test_cli_help_contains_output_flag(self) -> None:
        from yt_intelligence_pipeline.main import parse_args
        import sys
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["yt-pipeline", "--help"]
            parse_args()
        assert exc.value.code == 0

    def test_output_default_is_human(self) -> None:
        from yt_intelligence_pipeline.main import parse_args
        import sys
        sys.argv = ["yt-pipeline", "https://www.youtube.com/watch?v=test"]
        args = parse_args()
        assert args.output == "human"

    def test_output_agent_parsed(self) -> None:
        from yt_intelligence_pipeline.main import parse_args
        import sys
        sys.argv = ["yt-pipeline", "https://www.youtube.com/watch?v=test", "--output", "agent"]
        args = parse_args()
        assert args.output == "agent"

    def test_output_both_parsed(self) -> None:
        from yt_intelligence_pipeline.main import parse_args
        import sys
        sys.argv = ["yt-pipeline", "https://www.youtube.com/watch?v=test", "--output", "both"]
        args = parse_args()
        assert args.output == "both"

    def test_invalid_output_raises(self) -> None:
        from yt_intelligence_pipeline.main import parse_args
        import sys
        sys.argv = ["yt-pipeline", "https://www.youtube.com/watch?v=test", "--output", "invalid"]
        with pytest.raises(SystemExit):
            parse_args()
