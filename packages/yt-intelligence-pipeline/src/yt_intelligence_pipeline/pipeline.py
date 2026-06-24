from __future__ import annotations

from pathlib import Path

from yt_intelligence_pipeline.config import AppConfig
from yt_intelligence_pipeline.models import (
    PipelineResult,
    ProcessedOutput,
    TimestampEntry,
    TranscriptSource,
    VideoJob,
)
from yt_intelligence_pipeline.chains.cleanup_chain import run_cleanup_chain
from yt_intelligence_pipeline.chains.summary_chain import run_summary_chain
from yt_intelligence_pipeline.chains.timestamp_chain import run_timestamp_chain
from yt_intelligence_pipeline.obsidian.writer import write_obsidian_note
from yt_intelligence_pipeline.screenshots.downloader import download_video_to_temp
from yt_intelligence_pipeline.screenshots.extractor import extract_frames
from yt_intelligence_pipeline.transcript.fetcher import fetch_youtube_captions
from yt_intelligence_pipeline.transcript.metadata import fetch_video_metadata
from yt_intelligence_pipeline.transcript.whisper_fallback import (
    transcribe_from_file,
    transcribe_with_whisper,
)
from yt_intelligence_pipeline.utils.logging import get_logger
from yt_intelligence_pipeline.utils.slugify import slugify

logger = get_logger(__name__)


def run_pipeline(
    url: str,
    use_screenshots: bool,
    config: AppConfig,
    skip_existing: bool = False,
    human_output: bool = True,
) -> PipelineResult:
    """Execute the full 7-step pipeline. Returns a PipelineResult."""

    job = VideoJob(youtube_url=url, use_screenshots=use_screenshots)

    # Step 1: Metadata (cheap — lets us check skip_existing before any heavy work)
    logger.info("Fetching video metadata...")
    job.video_metadata = fetch_video_metadata(url)
    logger.info(f'"{job.video_metadata.title}" by {job.video_metadata.channel}')

    if skip_existing and human_output:
        note_path = config.obsidian_output_path / f"{slugify(job.video_metadata.title)}.md"
        if note_path.exists():
            logger.info(f"Skipping — note already exists: {note_path.name}")
            return PipelineResult(
                video_url=url,
                video_metadata={
                    "title": job.video_metadata.title,
                    "channel": job.video_metadata.channel,
                    "description": job.video_metadata.description,
                    "duration_seconds": job.video_metadata.duration_seconds,
                },
                cleaned_transcript="",
                summary="",
                key_takeaways=[],
                tags=[],
                timestamp_entries=[],
                human_output_path=note_path,
                transcript_source=None,
            )

    try:
        # Step 2: Transcript
        logger.info("Fetching transcript...")
        captions = fetch_youtube_captions(url)
        if captions:
            job.raw_transcript, job.raw_transcript_timed = captions
            job.transcript_source = TranscriptSource.YOUTUBE_CAPTIONS
            logger.info("Using YouTube captions")
        else:
            if use_screenshots:
                logger.info("Captions unavailable — downloading video for Whisper + screenshots...")
                job.temp_video_path = download_video_to_temp(url)
                logger.info("Transcribing with Whisper (this may take several minutes)...")
                job.raw_transcript, job.raw_transcript_timed = transcribe_from_file(job.temp_video_path)
            else:
                logger.info("Captions unavailable — downloading audio for Whisper...")
                job.raw_transcript, job.raw_transcript_timed = transcribe_with_whisper(url)
            job.transcript_source = TranscriptSource.WHISPER
            logger.info("Whisper transcription complete")

        # Step 3: Cleanup
        logger.info("Running transcript cleanup chain...")
        cleaned = run_cleanup_chain(job.raw_transcript, config.anthropic_api_key)

        # Step 4: Summary + Takeaways + Tags
        logger.info("Running summary chain...")
        summary_result = run_summary_chain(cleaned, job.video_metadata, config.anthropic_api_key)

        # Step 5: Timestamp identification (conditional)
        timestamps: list[TimestampEntry] | None = None
        if use_screenshots:
            logger.info("Identifying screenshot timestamps...")
            timestamps = run_timestamp_chain(job.raw_transcript_timed, config.anthropic_api_key)
            logger.info(f"Claude identified {len(timestamps)} screenshot moments")

        output = ProcessedOutput(
            cleaned_transcript=cleaned,
            summary=summary_result.summary,
            key_takeaways=summary_result.key_takeaways,
            tags=summary_result.tags,
            screenshot_timestamps=timestamps,
        )

        # Step 6: Screenshot extraction (conditional)
        if use_screenshots and timestamps:
            if job.temp_video_path is None:
                logger.info("Downloading video for frame extraction...")
                job.temp_video_path = download_video_to_temp(url)

            slug = slugify(job.video_metadata.title)
            if human_output:
                screenshots_dir = config.obsidian_output_path / slug
            else:
                # agent-only mode: write to a temp location; agent_output.py will copy to agent-data
                import tempfile
                screenshots_dir = Path(tempfile.mkdtemp()) / slug

            logger.info(f"Extracting {len(timestamps)} frames with ffmpeg...")
            output.screenshot_timestamps = extract_frames(job.temp_video_path, timestamps, screenshots_dir)
            job.temp_video_path = None

        # Step 7: Write human note (conditional)
        human_output_path: Path | None = None
        if human_output:
            logger.info("Writing Obsidian note...")
            human_output_path = write_obsidian_note(config.obsidian_output_path, job, output)
            logger.info(f"Done — note written to: {human_output_path}")

        # Build structured result
        ts_entries = []
        if output.screenshot_timestamps:
            ts_entries = [
                {
                    "timestamp_seconds": ts.timestamp_seconds,
                    "label": ts.label,
                    "extracted_image_path": str(ts.extracted_image_path) if ts.extracted_image_path else None,
                }
                for ts in output.screenshot_timestamps
            ]

        return PipelineResult(
            video_url=url,
            video_metadata={
                "title": job.video_metadata.title,
                "channel": job.video_metadata.channel,
                "description": job.video_metadata.description,
                "duration_seconds": job.video_metadata.duration_seconds,
            },
            cleaned_transcript=output.cleaned_transcript,
            summary=output.summary,
            key_takeaways=output.key_takeaways,
            tags=output.tags,
            timestamp_entries=ts_entries,
            human_output_path=human_output_path,
            transcript_source=job.transcript_source,
        )

    finally:
        if job.temp_video_path is not None and job.temp_video_path.exists():
            job.temp_video_path.unlink(missing_ok=True)
            try:
                job.temp_video_path.parent.rmdir()
            except OSError:
                pass
