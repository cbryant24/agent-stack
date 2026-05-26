"""YouTube Tutorial Intelligence Pipeline.

Human mode: run_pipeline / process_video → Obsidian Markdown notes.
Agent mode: process_video(agent_output=True) → Qdrant vector ingestion via agent-runtime.
"""
from __future__ import annotations

from yt_intelligence_pipeline.models import (
    AgentModeResult,
    PipelineResult,
    TimestampEntry,
    TranscriptSource,
    VideoMetadata,
)

__all__ = [
    "process_video",
    "process_video_sync",
    "PipelineResult",
    "AgentModeResult",
    "VideoMetadata",
    "TimestampEntry",
    "TranscriptSource",
]


async def process_video(
    url: str,
    *,
    use_screenshots: bool = True,
    human_output: bool = True,
    agent_output: bool = False,
    config: object | None = None,
    skip_existing: bool = False,
    collection_name: str = "tutorial_research",
    processed_by_agent: str = "yt-intelligence-pipeline",
    processed_in_run: str | None = None,
) -> PipelineResult:
    """Process a YouTube video through the full pipeline.

    Parameters
    ----------
    url:
        YouTube video URL.
    use_screenshots:
        Download video and extract frames at key timestamps. Default True.
    human_output:
        Write an Obsidian Markdown note. Default True.
    agent_output:
        Chunk, embed, and upsert to Qdrant via agent-runtime. Default False.
    config:
        AppConfig instance. If None, loads from environment.
    skip_existing:
        Skip if a human note already exists at the expected path.
    collection_name:
        Qdrant collection for agent mode.
    processed_by_agent:
        Recorded in MemoryPoint payload.
    processed_in_run:
        Run ID for trace correlation. Inferred from BudgetTracker context if active.
    """
    from yt_intelligence_pipeline.config import AppConfig, load_and_validate_config
    from yt_intelligence_pipeline.pipeline import run_pipeline

    if config is None and human_output:
        config = load_and_validate_config()
    elif config is None:
        # Agent-only mode: create a minimal config without requiring OBSIDIAN_OUTPUT_PATH
        import os
        import tempfile
        from yt_intelligence_pipeline.config import _load_env
        _load_env()
        import anthropic as _anthropic  # noqa: F401 — just to get the key
        config = AppConfig(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            langsmith_api_key=os.getenv("LANGSMITH_API_KEY", ""),
            langsmith_project=os.getenv("LANGSMITH_PROJECT", "youtube-tutorial-pipeline"),
            obsidian_output_path=__import__("pathlib").Path(tempfile.mkdtemp()),
        )

    result = run_pipeline(
        url=url,
        use_screenshots=use_screenshots,
        config=config,  # type: ignore[arg-type]
        skip_existing=skip_existing,
        human_output=human_output,
    )

    if agent_output:
        from yt_intelligence_pipeline.agent_output import ingest_to_qdrant
        result.agent_output = await ingest_to_qdrant(
            result,
            collection_name=collection_name,
            processed_by_agent=processed_by_agent,
            processed_in_run=processed_in_run,
        )

    return result


def process_video_sync(
    url: str,
    **kwargs: object,
) -> PipelineResult:
    """Synchronous wrapper around process_video for use in sync contexts."""
    import asyncio
    return asyncio.run(process_video(url, **kwargs))  # type: ignore[arg-type]
