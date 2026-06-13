"""Smoke tests: imports, config loading, CLI entry point callable."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


class TestImports:
    def test_package_importable(self) -> None:
        import yt_intelligence_pipeline  # noqa: F401

    def test_process_video_importable(self) -> None:
        from yt_intelligence_pipeline import process_video
        assert callable(process_video)

    def test_process_video_sync_importable(self) -> None:
        from yt_intelligence_pipeline import process_video_sync
        assert callable(process_video_sync)

    def test_models_importable(self) -> None:
        from yt_intelligence_pipeline.models import (
            AgentModeResult,
            PipelineResult,
            TimestampEntry,
            TranscriptSource,
            VideoMetadata,
        )

    def test_config_importable(self) -> None:
        from yt_intelligence_pipeline.config import AppConfig, load_and_validate_config

    def test_pipeline_importable(self) -> None:
        from yt_intelligence_pipeline.pipeline import run_pipeline
        assert callable(run_pipeline)

    def test_cli_importable(self) -> None:
        from yt_intelligence_pipeline.main import cli
        assert callable(cli)


class TestConfigLoading:
    def test_loads_with_fake_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config loads when all env vars are present."""
        from yt_intelligence_pipeline.config import AppConfig, load_and_validate_config

        obsidian = tmp_path / "vault"
        obsidian.mkdir()
        monkeypatch.setenv("OBSIDIAN_OUTPUT_PATH", str(obsidian))

        cfg = load_and_validate_config()
        assert cfg.anthropic_api_key == "sk-test-anthropic"
        assert cfg.obsidian_output_path == obsidian
        assert isinstance(cfg, AppConfig)

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRODUCTION_AGENTS_ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SystemExit):
            from yt_intelligence_pipeline.config import load_and_validate_config
            load_and_validate_config()

    def test_missing_obsidian_path_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OBSIDIAN_OUTPUT_PATH", raising=False)
        with pytest.raises(SystemExit):
            from yt_intelligence_pipeline.config import load_and_validate_config
            load_and_validate_config()


class TestSubmoduleImports:
    def test_transcript_fetcher(self) -> None:
        from yt_intelligence_pipeline.transcript.fetcher import (
            extract_video_id,
            fetch_youtube_captions,
        )

    def test_utils_slugify(self) -> None:
        from yt_intelligence_pipeline.utils.slugify import slugify
        assert slugify("Hello World! 123") == "hello-world-123"

    def test_utils_logging(self) -> None:
        from yt_intelligence_pipeline.utils.logging import configure_logging, get_logger
        logger = get_logger("test")
        assert logger is not None

    def test_agent_output_importable(self) -> None:
        from yt_intelligence_pipeline.agent_output import ingest_to_qdrant
        assert callable(ingest_to_qdrant)
