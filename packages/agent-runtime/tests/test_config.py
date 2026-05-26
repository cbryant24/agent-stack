from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_runtime.config import RuntimeConfig, get_config, reset_config


class TestRuntimeConfig:
    def test_requires_anthropic_key(self) -> None:
        with pytest.raises((ValidationError, Exception)):
            RuntimeConfig(voyage_api_key="x", _env_file=None)  # type: ignore[call-arg]

    def test_defaults_populate(self, fake_env: None) -> None:
        cfg = RuntimeConfig()
        assert cfg.qdrant_url == "http://localhost:6333"
        assert cfg.otel_endpoint == "http://localhost:4318"
        assert cfg.agent_data_dir.name == "agent-data"
        assert cfg.tavily_api_key is not None  # set by fake_env

    def test_env_values_read(self, fake_env: None) -> None:
        cfg = RuntimeConfig()
        assert cfg.anthropic_api_key == "sk-test-anthropic"
        assert cfg.voyage_api_key == "pa-test-voyage"

    def test_directories_created(self, fake_env: None, tmp_path: pytest.TempPathFactory) -> None:
        import os
        cfg = RuntimeConfig(
            agent_data_dir=tmp_path / "agent-data",  # type: ignore[call-arg]
            agent_reports_vault=tmp_path / "reports",  # type: ignore[call-arg]
        )
        assert (cfg.agent_data_dir / "sources").exists()
        assert (cfg.agent_data_dir / "runs").exists()
        assert (cfg.agent_data_dir / "qdrant").exists()
        assert (cfg.agent_reports_vault / "tutorial-research").exists()


class TestGetConfig:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_returns_same_instance(self, fake_env: None) -> None:
        a = get_config()
        b = get_config()
        assert a is b

    def test_reset_clears_cache(self, fake_env: None) -> None:
        a = get_config()
        reset_config()
        b = get_config()
        assert a is not b
