"""CLI entry point for the YouTube Tutorial Intelligence Pipeline.

Usage:
    yt-pipeline <youtube_url>
    yt-pipeline <youtube_url> --no-screenshots
    yt-pipeline <youtube_url> --output agent
    yt-pipeline <youtube_url> --output both
    yt-pipeline <playlist_url> --output human
"""
from __future__ import annotations

import argparse
import asyncio

from yt_intelligence_pipeline.config import load_and_validate_config
from yt_intelligence_pipeline.transcript.playlist import fetch_playlist_videos, is_playlist_url
from yt_intelligence_pipeline.utils.logging import configure_logging, get_logger
from yt_intelligence_pipeline.utils.slugify import slugify


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform a YouTube tutorial (or playlist) into structured notes."
    )
    parser.add_argument("youtube_url", help="YouTube video or playlist URL to process")
    parser.add_argument(
        "--no-screenshots",
        action="store_false",
        dest="screenshots",
        help="Skip screenshot extraction and video download (faster)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip videos that already have a note in the vault",
    )
    parser.add_argument(
        "--output",
        choices=["human", "agent", "both"],
        default="human",
        help="Output mode: human (Obsidian note), agent (Qdrant ingestion), or both",
    )
    parser.add_argument(
        "--collection",
        default="tutorial_research",
        help="Qdrant collection name for agent mode (default: tutorial_research)",
    )
    parser.set_defaults(screenshots=True)
    return parser.parse_args()


def cli() -> None:
    args = parse_args()
    configure_logging()
    logger = get_logger(__name__)
    config = load_and_validate_config()

    human_output = args.output in ("human", "both")
    agent_output_flag = args.output in ("agent", "both")

    from yt_intelligence_pipeline import process_video

    if is_playlist_url(args.youtube_url):
        logger.info("Playlist URL detected — fetching video list...")
        playlist_title, video_urls = fetch_playlist_videos(args.youtube_url)
        logger.info(f'Playlist: "{playlist_title}" — {len(video_urls)} videos')

        if human_output:
            playlist_dir = config.obsidian_output_path / slugify(playlist_title)
            playlist_dir.mkdir(parents=True, exist_ok=True)
            playlist_config = config.__class__(
                anthropic_api_key=config.anthropic_api_key,
                langsmith_api_key=config.langsmith_api_key,
                langsmith_project=config.langsmith_project,
                obsidian_output_path=playlist_dir,
            )
        else:
            playlist_config = config

        for i, url in enumerate(video_urls, start=1):
            logger.info(f"[{i}/{len(video_urls)}] Processing {url}")
            try:
                result = asyncio.run(process_video(
                    url,
                    use_screenshots=args.screenshots,
                    human_output=human_output,
                    agent_output=agent_output_flag,
                    config=playlist_config,
                    skip_existing=args.skip_existing,
                    collection_name=args.collection,
                ))
                _print_result(result, args.output)
            except Exception as e:
                logger.error(f"Failed to process {url}: {e} — skipping")
    else:
        result = asyncio.run(process_video(
            args.youtube_url,
            use_screenshots=args.screenshots,
            human_output=human_output,
            agent_output=agent_output_flag,
            config=config,
            skip_existing=args.skip_existing,
            collection_name=args.collection,
        ))
        _print_result(result, args.output)


def _print_result(result: object, output_mode: str) -> None:
    from yt_intelligence_pipeline.models import PipelineResult
    if not isinstance(result, PipelineResult):
        return
    if result.human_output_path:
        print(f"Human note: {result.human_output_path}")
    if result.agent_output:
        ao = result.agent_output
        print(
            f"Agent ingestion: {ao.text_points_upserted} text + "
            f"{ao.multimodal_points_upserted} image points → "
            f"collection '{ao.collection_name}' (source_id={ao.source_id})"
        )
