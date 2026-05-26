from __future__ import annotations

import yt_dlp


def is_playlist_url(url: str) -> bool:
    return "list=" in url and "watch?v=" not in url


def fetch_playlist_videos(playlist_url: str) -> tuple[str, list[str]]:
    """Returns (playlist_title, [video_url, ...])."""
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    title = info.get("title", "playlist")
    entries = info.get("entries") or []
    urls = [
        f"https://www.youtube.com/watch?v={e['id']}"
        for e in entries
        if e and e.get("id")
    ]
    return title, urls
