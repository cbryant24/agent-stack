"""Verify every yt-dlp call site wires the shared opts through.

These functions have no other tests; here we mock ``yt_dlp.YoutubeDL`` so nothing
hits the network and assert that ``cookiefile`` lands in the opts dict when the
configured cookie file exists (and is absent when it does not), and that the EJS
solver ``remote_components`` option is applied.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_intelligence_pipeline.screenshots.downloader import download_video_to_temp
from yt_intelligence_pipeline.transcript.metadata import fetch_video_metadata
from yt_intelligence_pipeline.transcript.playlist import fetch_playlist_videos
from yt_intelligence_pipeline.transcript.whisper_fallback import _download_audio


def _mock_ydl(extract_info_return: dict) -> MagicMock:
    """Build a MagicMock standing in for the yt_dlp.YoutubeDL class.

    The real call sites use ``with yt_dlp.YoutubeDL(opts) as ydl``, so the
    context-manager __enter__ must return an object whose ``extract_info``
    yields canned data.
    """
    ydl_cls = MagicMock()
    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = extract_info_return
    ydl_cls.return_value.__enter__.return_value = ydl_instance
    return ydl_cls


@pytest.fixture
def cookie_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "youtube-cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(path))
    monkeypatch.delenv("YOUTUBE_REMOTE_COMPONENTS", raising=False)
    return path


def _passed_opts(ydl_cls: MagicMock) -> dict:
    return ydl_cls.call_args.args[0]


def test_fetch_video_metadata_passes_cookiefile(cookie_file: Path) -> None:
    ydl_cls = _mock_ydl(
        {"title": "T", "uploader": "C", "description": "", "duration": 1}
    )
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        fetch_video_metadata("https://youtu.be/abc")
    opts = _passed_opts(ydl_cls)
    assert opts["cookiefile"] == str(cookie_file)
    assert opts["remote_components"] == ["ejs:github"]


def test_fetch_playlist_videos_passes_cookiefile(cookie_file: Path) -> None:
    ydl_cls = _mock_ydl({"title": "PL", "entries": [{"id": "v1"}]})
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        fetch_playlist_videos("https://youtube.com/playlist?list=PL1")
    opts = _passed_opts(ydl_cls)
    assert opts["cookiefile"] == str(cookie_file)
    assert opts["remote_components"] == ["ejs:github"]


def test_download_audio_passes_cookiefile(cookie_file: Path, tmp_path: Path) -> None:
    dest = tmp_path / "audio"
    dest.mkdir()
    (dest / "v1.mp3").write_text("")  # satisfy the post-download glob
    ydl_cls = _mock_ydl({"id": "v1"})
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        _download_audio("https://youtu.be/v1", dest)
    opts = _passed_opts(ydl_cls)
    assert opts["cookiefile"] == str(cookie_file)
    assert opts["remote_components"] == ["ejs:github"]


def test_download_video_passes_cookiefile(
    cookie_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "video"
    dest.mkdir()
    (dest / "v1.mp4").write_text("")  # satisfy the post-download glob
    monkeypatch.setattr("tempfile.mkdtemp", lambda: str(dest))
    ydl_cls = _mock_ydl({"id": "v1"})
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        download_video_to_temp("https://youtu.be/v1")
    opts = _passed_opts(ydl_cls)
    assert opts["cookiefile"] == str(cookie_file)
    assert opts["remote_components"] == ["ejs:github"]


def test_no_cookiefile_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(tmp_path / "missing.txt"))
    ydl_cls = _mock_ydl(
        {"title": "T", "uploader": "C", "description": "", "duration": 1}
    )
    with patch("yt_dlp.YoutubeDL", ydl_cls):
        fetch_video_metadata("https://youtu.be/abc")
    assert "cookiefile" not in _passed_opts(ydl_cls)
