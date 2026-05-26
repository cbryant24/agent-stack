from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class AppConfig:
    anthropic_api_key: str
    langsmith_api_key: str
    langsmith_project: str
    obsidian_output_path: Path


def load_and_validate_config() -> AppConfig:
    # Load from the workspace .env (two levels up from this package) or cwd
    _load_env()

    missing = []

    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")

    langsmith_api_key = os.getenv("LANGSMITH_API_KEY", "")
    if not langsmith_api_key:
        missing.append("LANGSMITH_API_KEY")

    langsmith_project = os.getenv("LANGSMITH_PROJECT", "youtube-tutorial-pipeline")

    obsidian_output_path_str = os.getenv("OBSIDIAN_OUTPUT_PATH", "")
    if not obsidian_output_path_str:
        missing.append("OBSIDIAN_OUTPUT_PATH")

    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    obsidian_output_path = Path(obsidian_output_path_str).expanduser()
    if not obsidian_output_path.is_dir():
        raise SystemExit(
            f"OBSIDIAN_OUTPUT_PATH does not exist or is not a directory: {obsidian_output_path}"
        )

    return AppConfig(
        anthropic_api_key=anthropic_api_key,
        langsmith_api_key=langsmith_api_key,
        langsmith_project=langsmith_project,
        obsidian_output_path=obsidian_output_path,
    )


def _load_env() -> None:
    """Try loading .env from cwd, then walk up to workspace root."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        env_file = directory / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            return
    load_dotenv()  # fallback: look in default locations
