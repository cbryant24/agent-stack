from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_runtime.youtube import (
    apply_cookiefile,
    apply_remote_components,
    prepare_ydl_opts,
    youtube_cookies_file,
    youtube_remote_components,
)


class TestYoutubeCookiesFile:
    def test_default_path_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTUBE_COOKIES_FILE", raising=False)
        assert youtube_cookies_file() == Path.home() / "agent-data" / "youtube-cookies.txt"

    def test_env_override_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "~/some/cookies.txt")
        resolved = youtube_cookies_file()
        assert resolved == Path.home() / "some" / "cookies.txt"
        assert not str(resolved).startswith("~")


class TestApplyCookiefile:
    def test_sets_when_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cookie_file = tmp_path / "youtube-cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n")
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(cookie_file))

        opts = {"quiet": True}
        result = apply_cookiefile(opts)

        assert result is opts
        assert opts["cookiefile"] == str(cookie_file)
        assert opts["quiet"] is True

    def test_skips_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        missing = tmp_path / "nope" / "youtube-cookies.txt"
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(missing))

        opts = {"quiet": True}
        with caplog.at_level(logging.WARNING, logger="agent_runtime.youtube"):
            result = apply_cookiefile(opts)

        assert result is opts
        assert "cookiefile" not in opts
        assert opts == {"quiet": True}
        assert any("cookie file not found" in r.message.lower() for r in caplog.records)


class TestYoutubeRemoteComponents:
    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTUBE_REMOTE_COMPONENTS", raising=False)
        assert youtube_remote_components() == ["ejs:github"]

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_REMOTE_COMPONENTS", "ejs:npm, ejs:github")
        assert youtube_remote_components() == ["ejs:npm", "ejs:github"]

    def test_empty_env_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_REMOTE_COMPONENTS", "")
        assert youtube_remote_components() == []


class TestApplyRemoteComponents:
    def test_sets_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTUBE_REMOTE_COMPONENTS", raising=False)

        opts = {"quiet": True}
        result = apply_remote_components(opts)

        assert result is opts
        assert opts["remote_components"] == ["ejs:github"]
        assert opts["quiet"] is True

    def test_omits_key_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_REMOTE_COMPONENTS", "")

        opts = {"quiet": True}
        result = apply_remote_components(opts)

        assert result is opts
        assert "remote_components" not in opts
        assert opts == {"quiet": True}


class TestPrepareYdlOpts:
    def test_applies_both_cookiefile_and_solver(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cookie_file = tmp_path / "youtube-cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n")
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(cookie_file))
        monkeypatch.delenv("YOUTUBE_REMOTE_COMPONENTS", raising=False)

        opts = {"quiet": True}
        result = prepare_ydl_opts(opts)

        assert result is opts
        assert opts["cookiefile"] == str(cookie_file)
        assert opts["remote_components"] == ["ejs:github"]
        assert opts["quiet"] is True
