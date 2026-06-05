from __future__ import annotations

import asyncio
import logging

from agent_runtime.youtube import prepare_ydl_opts

from tutorial_research.models import CandidateEntry

logger = logging.getLogger(__name__)


def _fetch_metadata_sync(url: str) -> CandidateEntry | None:
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    prepare_ydl_opts(ydl_opts)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        logger.debug("Dropping %s: yt-dlp fetch failed: %s", url, exc)
        return None

    if not info:
        logger.debug("Dropping %s: no metadata returned", url)
        return None

    if info.get("is_live") or info.get("was_live"):
        logger.debug("Dropping %s: live stream", url)
        return None

    # Members-only / paywalled — yt-dlp sets availability field
    availability = info.get("availability", "")
    if availability in ("subscriber_only", "premium_only", "needs_auth"):
        logger.debug("Dropping %s: paywalled (%s)", url, availability)
        return None

    has_captions = bool(info.get("subtitles") or info.get("automatic_captions"))

    return CandidateEntry(
        url=url,
        title=info.get("title", ""),
        channel=info.get("uploader") or info.get("channel") or "",
        description=(info.get("description") or "")[:500],
        duration_seconds=int(info.get("duration") or 0),
        view_count=int(info.get("view_count") or 0),
        upload_date=info.get("upload_date") or "",
        has_captions=has_captions,
    )


async def fetch_video_metadata(url: str) -> CandidateEntry | None:
    return await asyncio.to_thread(_fetch_metadata_sync, url)
