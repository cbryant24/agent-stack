from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_COOKIES_FILE = "~/agent-data/youtube-cookies.txt"
_DEFAULT_REMOTE_COMPONENTS = "ejs:github"


def youtube_cookies_file() -> Path:
    """Resolve the configured cookie file path (env override + ~ expansion)."""
    raw = os.getenv("YOUTUBE_COOKIES_FILE") or _DEFAULT_COOKIES_FILE
    return Path(raw).expanduser()


def youtube_remote_components() -> list[str]:
    """Resolve yt-dlp remote components to allow (env override, comma-separated).

    Defaults to ``ejs:github`` so the EJS JavaScript challenge solver is enabled
    (required for YouTube to return real media formats). Set
    ``YOUTUBE_REMOTE_COMPONENTS`` empty to disable all remote fetching, or to a
    comma-separated list (e.g. ``ejs:npm``) to override.
    """
    raw = os.getenv("YOUTUBE_REMOTE_COMPONENTS")
    if raw is None:
        raw = _DEFAULT_REMOTE_COMPONENTS
    return [c.strip() for c in raw.split(",") if c.strip()]


def apply_cookiefile(opts: dict[str, Any]) -> dict[str, Any]:
    """Inject yt-dlp's ``cookiefile`` into ``opts`` when the file exists on disk.

    If the file is missing, leave ``opts`` unchanged and log a warning so
    environments without the cookie file still run (unauthenticated path).
    Mutates and returns ``opts`` for convenient inline use.
    """
    path = youtube_cookies_file()
    if path.exists():
        opts["cookiefile"] = str(path)
    else:
        logger.warning(
            "YouTube cookie file not found at %s; proceeding unauthenticated "
            "(set YOUTUBE_COOKIES_FILE to override)",
            path,
        )
    return opts


def apply_remote_components(opts: dict[str, Any]) -> dict[str, Any]:
    """Inject yt-dlp's ``remote_components`` into ``opts`` to enable the EJS solver.

    This is the API equivalent of the CLI flag ``--remote-components ejs:github``.
    When the configured list is empty (env set empty), leave ``opts`` unchanged
    so no remote fetching is allowed. Mutates and returns ``opts``.
    """
    components = youtube_remote_components()
    if components:
        opts["remote_components"] = components
    return opts


def prepare_ydl_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Apply all shared YouTube yt-dlp options (cookiefile + EJS solver).

    Single entry point for the yt-dlp call sites. Mutates and returns ``opts``.
    """
    apply_cookiefile(opts)
    apply_remote_components(opts)
    return opts
