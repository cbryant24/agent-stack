from __future__ import annotations

import yt_dlp

from yt_intelligence_pipeline.models import VideoMetadata


def fetch_video_metadata(youtube_url: str) -> VideoMetadata:
    opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
    return VideoMetadata(
        title=info.get("title", "Unknown Title"),
        channel=info.get("uploader") or info.get("channel", "Unknown Channel"),
        description=info.get("description", ""),
        duration_seconds=info.get("duration", 0),
    )
