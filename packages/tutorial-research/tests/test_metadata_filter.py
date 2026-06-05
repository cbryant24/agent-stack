"""Verify the metadata_filter yt-dlp call site wires the shared opts through."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tutorial_research.metadata_filter import _fetch_metadata_sync


def _mock_ydl(extract_info_return: dict) -> MagicMock:
    ydl_cls = MagicMock()
    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = extract_info_return
    ydl_cls.return_value.__enter__.return_value = ydl_instance
    return ydl_cls


_INFO = {
    "title": "Async Tutorial",
    "uploader": "Tech Channel",
    "description": "Learn asyncio",
    "duration": 600,
    "view_count": 100,
    "upload_date": "20240101",
    "subtitles": {"en": [{}]},
}


def test_passes_cookiefile_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookie_file = tmp_path / "youtube-cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(cookie_file))
    monkeypatch.delenv("YOUTUBE_REMOTE_COMPONENTS", raising=False)

    ydl_cls = _mock_ydl(_INFO)
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        result = _fetch_metadata_sync("https://youtu.be/abc")

    assert result is not None
    opts = ydl_cls.call_args.args[0]
    assert opts["cookiefile"] == str(cookie_file)
    assert opts["remote_components"] == ["ejs:github"]


def test_no_cookiefile_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(tmp_path / "missing.txt"))

    ydl_cls = _mock_ydl(_INFO)
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        _fetch_metadata_sync("https://youtu.be/abc")

    assert "cookiefile" not in ydl_cls.call_args.args[0]
