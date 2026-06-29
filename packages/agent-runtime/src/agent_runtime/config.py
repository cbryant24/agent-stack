from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(validation_alias="PRODUCTION_AGENTS_ANTHROPIC_API_KEY")
    orchestrator_anthropic_api_key: str | None = None
    openai_api_key: str | None = Field(
        default=None, validation_alias="PRODUCTION_AGENTS_OPENAI_API_KEY"
    )
    default_llm_provider: str = Field(
        default="anthropic", validation_alias="PRODUCTION_AGENTS_DEFAULT_LLM_PROVIDER"
    )
    voyage_api_key: str
    tavily_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    qdrant_url: str = "http://localhost:6333"
    otel_endpoint: str = "http://localhost:4318"
    agent_data_dir: Path = Path("~/agent-data").expanduser()
    agent_reports_vault: Path = Path("~/obsidian/agent-reports").expanduser()

    @field_validator("agent_data_dir", "agent_reports_vault", mode="before")
    @classmethod
    def _expand_path(cls, v: Any) -> Path:
        return Path(v).expanduser()

    @model_validator(mode="after")
    def _ensure_directories(self) -> RuntimeConfig:
        for subdir in ("sources", "runs", "qdrant"):
            (self.agent_data_dir / subdir).mkdir(parents=True, exist_ok=True)
        (self.agent_data_dir / "drafts" / "user_knowledge").mkdir(parents=True, exist_ok=True)
        for subdir in ("tutorial-research", "music-curation", "system"):
            (self.agent_reports_vault / subdir).mkdir(parents=True, exist_ok=True)
        return self


@lru_cache(maxsize=1)
def get_config() -> RuntimeConfig:
    return RuntimeConfig()


def reset_config() -> None:
    get_config.cache_clear()
