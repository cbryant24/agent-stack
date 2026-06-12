"""Reference grounding — the deterministic, non-LLM half of stage 1.

Two cheap context sources, both optional and both degrading to empty on failure:

- `fetch_url_context` — yt-dlp metadata/description for a reference video URL.
  Metadata/description ONLY; no frame extraction (that is Mode B, parked).
- `tavily_reference_search` — REFERENCE discovery (what "videos like X" are,
  exemplars, commentary). This is the Tavily-boundary distinction from
  tutorial-research: that agent searches for *tutorials to ingest*; this one
  searches to *understand the reference*. No youtube-only filter, no "tutorial"
  framing, and crucially it ingests nothing.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_runtime import get_config
from agent_runtime.youtube import prepare_ydl_opts

logger = logging.getLogger(__name__)


def _fetch_url_metadata_sync(url: str) -> dict[str, Any] | None:
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
    except Exception as exc:  # DownloadError and friends — degrade to no context
        logger.warning("yt-dlp metadata fetch failed for %s: %s", url, exc)
        return None
    if not info:
        return None
    return {
        "title": info.get("title", ""),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "description": (info.get("description") or "")[:1500],
        "duration_seconds": int(info.get("duration") or 0),
        "tags": (info.get("tags") or [])[:20],
        "categories": info.get("categories") or [],
    }


async def fetch_url_context(url: str) -> dict[str, Any] | None:
    """Fetch yt-dlp metadata/description for a reference video URL (no frames)."""
    return await asyncio.to_thread(_fetch_url_metadata_sync, url)


def _tavily_search_sync(query: str, max_results: int) -> list[str]:
    from tavily import TavilyClient

    api_key = get_config().tavily_api_key
    if not api_key:
        logger.info("TAVILY_API_KEY not configured — skipping reference discovery")
        return []
    client = TavilyClient(api_key=api_key)
    results = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
    )
    snippets: list[str] = []
    for r in results.get("results", []):
        title = r.get("title", "")
        content = (r.get("content") or "")[:300]
        url = r.get("url", "")
        if content:
            snippets.append(f"{title} — {content} ({url})")
    return snippets


async def tavily_reference_search(query: str, *, max_results: int = 5) -> list[str]:
    """Reference discovery for an under-specified named reference. Returns []
    when Tavily is unconfigured or fails (graceful degrade — a well-specified
    goal never triggers this path at all)."""
    try:
        return await asyncio.to_thread(_tavily_search_sync, query, max_results)
    except Exception as exc:
        logger.warning("Tavily reference search failed (degrading): %s", exc)
        return []
