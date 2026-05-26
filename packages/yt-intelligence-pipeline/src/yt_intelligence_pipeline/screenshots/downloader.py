from __future__ import annotations

import tempfile
from pathlib import Path

import yt_dlp


def download_video_to_temp(youtube_url: str) -> Path:
    """Download the video to a fresh temp dir and return the local file path."""
    tmp_dir = Path(tempfile.mkdtemp())
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        video_id = info["id"]

    video_files = list(tmp_dir.glob(f"{video_id}.*"))
    if not video_files:
        raise RuntimeError(f"Video download failed: no file found in {tmp_dir}")
    return video_files[0]
