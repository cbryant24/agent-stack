"""Shared test fixtures for yt-intelligence-pipeline tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars so config loading works without real credentials."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "test-pipeline")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "agent-data"))
    monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "vault"))

    obsidian_dir = tmp_path / "obsidian"
    obsidian_dir.mkdir()
    monkeypatch.setenv("OBSIDIAN_OUTPUT_PATH", str(obsidian_dir))

    # Prevent any real .env file from being loaded
    monkeypatch.setattr(
        "yt_intelligence_pipeline.config._load_env",
        lambda: None,
    )
