from __future__ import annotations

from pathlib import Path

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

    def test_tilde_in_agent_data_dir_is_expanded(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
    ) -> None:
        from unittest.mock import patch
        monkeypatch.setenv("AGENT_DATA_DIR", "~/test_tilde_data_dir_expansion")
        monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "reports"))
        reset_config()
        request.addfinalizer(reset_config)
        with patch.object(Path, "mkdir"):
            cfg = RuntimeConfig()
        assert cfg.agent_data_dir == Path.home() / "test_tilde_data_dir_expansion"
        assert not str(cfg.agent_data_dir).startswith("~")

    def test_tilde_in_agent_reports_vault_is_expanded(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
    ) -> None:
        from unittest.mock import patch
        monkeypatch.setenv("AGENT_REPORTS_VAULT", "~/test_tilde_reports_vault_expansion")
        monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))
        reset_config()
        request.addfinalizer(reset_config)
        with patch.object(Path, "mkdir"):
            cfg = RuntimeConfig()
        assert cfg.agent_reports_vault == Path.home() / "test_tilde_reports_vault_expansion"
        assert not str(cfg.agent_reports_vault).startswith("~")


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


class TestChatOpenAIKey:
    def test_defaults_to_none(self, fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHAT_OPENAI_API_KEY", raising=False)
        assert RuntimeConfig(_env_file=None).chat_openai_api_key is None  # type: ignore[call-arg]

    def test_read_from_chat_env_var(self, fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_OPENAI_API_KEY", "sk-chat")
        monkeypatch.setenv("PRODUCTION_AGENTS_OPENAI_API_KEY", "sk-shared")
        cfg = RuntimeConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.chat_openai_api_key == "sk-chat"
        assert cfg.openai_api_key == "sk-shared"


class TestProjectsDir:
    def test_default_is_agent_projects_in_home(self, fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_PROJECTS_DIR", raising=False)
        cfg = RuntimeConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.agent_projects_dir == Path("~/agent-projects").expanduser()

    def test_env_override_expands_tilde_and_is_not_created(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        target = tmp_path / "work" / "projects"
        monkeypatch.setenv("AGENT_PROJECTS_DIR", str(target))
        cfg = RuntimeConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.agent_projects_dir == target
        assert not target.exists()                     # director-owned: never auto-created

    def test_project_dir_joins_a_valid_slug(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agent_runtime.config import project_dir

        monkeypatch.setenv("AGENT_PROJECTS_DIR", str(tmp_path))
        cfg = RuntimeConfig(_env_file=None)  # type: ignore[call-arg]
        assert project_dir("celeste-you-dangerous", cfg) == tmp_path / "celeste-you-dangerous"
        assert project_dir("a1", cfg) == tmp_path / "a1"
        assert not (tmp_path / "a1").exists()

    @pytest.mark.parametrize(
        "bad", ["", "Has-Caps", "with space", "snake_case", "../escape", "a/b", "-lead", "trail-", "a--b"]
    )
    def test_project_dir_rejects_non_kebab_slugs(
        self, fake_env: None, tmp_path: Path, bad: str
    ) -> None:
        from agent_runtime.config import project_dir

        with pytest.raises(ValueError, match="invalid project slug"):
            project_dir(bad, RuntimeConfig(agent_projects_dir=tmp_path, _env_file=None))  # type: ignore[call-arg]

    def test_project_dir_uses_the_cached_config_by_default(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agent_runtime.config import project_dir

        monkeypatch.setenv("AGENT_PROJECTS_DIR", str(tmp_path))
        reset_config()
        assert project_dir("demo") == tmp_path / "demo"
        reset_config()
