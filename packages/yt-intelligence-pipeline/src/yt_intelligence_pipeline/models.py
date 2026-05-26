from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class TranscriptSource(str, Enum):
    YOUTUBE_CAPTIONS = "youtube_captions"
    WHISPER = "whisper"


@dataclass
class VideoMetadata:
    title: str
    channel: str
    description: str
    duration_seconds: int


@dataclass
class VideoJob:
    youtube_url: str
    use_screenshots: bool
    raw_transcript: str | None = None
    raw_transcript_timed: str | None = None  # [MM:SS] markers for timestamp chain
    transcript_source: TranscriptSource | None = None
    video_metadata: VideoMetadata | None = None
    temp_video_path: Path | None = None


@dataclass
class TimestampEntry:
    timestamp_seconds: int
    label: str
    extracted_image_path: Path | None = None


@dataclass
class ProcessedOutput:
    cleaned_transcript: str
    summary: str
    key_takeaways: list[str]
    tags: list[str]
    screenshot_timestamps: list[TimestampEntry] | None = None


class AgentModeResult(BaseModel):
    collection_name: str
    text_points_upserted: int
    multimodal_points_upserted: int
    source_id: str


class PipelineResult(BaseModel):
    video_url: str
    video_metadata: dict  # serialized from VideoMetadata dataclass
    cleaned_transcript: str
    summary: str
    key_takeaways: list[str]
    tags: list[str]
    timestamp_entries: list[dict]  # serialized from TimestampEntry list
    human_output_path: Path | None = None
    agent_output: AgentModeResult | None = None
    transcript_source: TranscriptSource | None = None

    model_config = {"arbitrary_types_allowed": True}
