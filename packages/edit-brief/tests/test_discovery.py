from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from edit_brief import discovery
from edit_brief.discovery import (
    _scan_footage,
    _select_take,
    discover_assets,
    discover_music,
    discover_vo_takes,
)


# ── take-selection rule ───────────────────────────────────────────────────────


def _take(section, reaction, created):
    return {"section_id": section, "reaction": reaction, "created_at": created,
            "audio_path": f"/a/{created}.mp3"}


def test_positive_take_wins_over_newer_neutral():
    payloads = [
        _take("s", "liked", "2026-01-01"),
        _take("s", "pending", "2026-06-01"),  # newer but not positive
    ]
    chosen, ambiguous = _select_take(payloads)
    assert chosen["created_at"] == "2026-01-01"
    assert ambiguous is False


def test_newest_positive_among_positives():
    payloads = [
        _take("s", "liked", "2026-01-01"),
        _take("s", "loved", "2026-03-01"),
        _take("s", "disliked", "2026-09-01"),
    ]
    chosen, ambiguous = _select_take(payloads)
    assert chosen["created_at"] == "2026-03-01"
    assert ambiguous is True  # >1 positive → surfaced


def test_newest_overall_when_no_positive():
    payloads = [
        _take("s", "pending", "2026-01-01"),
        _take("s", "disliked", "2026-05-01"),
    ]
    chosen, ambiguous = _select_take(payloads)
    assert chosen["created_at"] == "2026-05-01"
    assert ambiguous is False


# ── discover_vo_takes (mocked scroll) ─────────────────────────────────────────


def _store_with_scroll(payloads):
    store = MagicMock()
    records = [SimpleNamespace(payload=p) for p in payloads]
    store._client.scroll = AsyncMock(return_value=(records, None))
    return store


@pytest.mark.asyncio
async def test_discover_vo_takes_only_scripts_sections(monkeypatch):
    monkeypatch.setattr(discovery, "ffprobe_duration", lambda p: 4.2)
    store = _store_with_scroll([
        _take("intro", "loved", "2026-01-01"),
        _take("outro", "liked", "2026-01-01"),
        _take("ghost", "liked", "2026-01-01"),  # not in the script
    ])
    takes = await discover_vo_takes(store, "proj", ["intro", "outro"])
    assert [t.section_id for t in takes] == ["intro", "outro"]
    assert all(t.duration_sec == 4.2 for t in takes)


@pytest.mark.asyncio
async def test_discover_vo_takes_missing_collection_degrades(monkeypatch):
    store = MagicMock()
    store._client.scroll = AsyncMock(side_effect=RuntimeError("no such collection"))
    takes = await discover_vo_takes(store, "proj", ["intro"])
    assert takes == []


# ── discover_music: BPM precedence ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bpm_flag_takes_precedence(monkeypatch):
    monkeypatch.setattr(discovery, "ffprobe_duration", lambda p: 120.0)
    store = MagicMock()
    store.query_by_vector = AsyncMock()  # must NOT be consulted
    music = await discover_music(store, music_file="/m.wav", bpm=128, music_hint="anything")
    assert music.bpm == 128
    assert music.bpm_source == "flag"
    assert music.duration_sec == 120.0
    store.query_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_bpm_matched_proposal_from_collection(monkeypatch):
    monkeypatch.setattr(discovery, "ffprobe_duration", lambda p: None)
    store = MagicMock()
    store.embedding_client.embed = AsyncMock(return_value=[[0.1, 0.2]])
    store.query_by_vector = AsyncMock(
        return_value=[("id", 0.8, {"bpm": 90, "suggested_track_title": "Calm Piano"})]
    )
    music = await discover_music(store, music_file=None, bpm=None, music_hint="ambient piano")
    assert music.bpm == 90
    assert music.bpm_source == "matched"
    assert music.matched_title == "Calm Piano"


@pytest.mark.asyncio
async def test_bpm_none_when_no_hint_and_no_flag():
    store = MagicMock()
    music = await discover_music(store, music_file=None, bpm=None, music_hint=None)
    assert music.bpm is None
    assert music.bpm_source == "none"


@pytest.mark.asyncio
async def test_bpm_match_degrades_when_collection_missing():
    store = MagicMock()
    store.embedding_client.embed = AsyncMock(return_value=[[0.1]])
    store.query_by_vector = AsyncMock(side_effect=RuntimeError("missing"))
    music = await discover_music(store, music_file=None, bpm=None, music_hint="piano")
    assert music.bpm_source == "none"


# ── footage scan ──────────────────────────────────────────────────────────────


def test_scan_footage_filters_extensions_and_reads_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "ffprobe_duration", lambda p: 1.5)
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / "clip.mp4.txt").write_text("a wide establishing shot")
    (tmp_path / "notes.md").write_text("ignore me")  # wrong extension
    assets = _scan_footage(str(tmp_path))
    assert len(assets) == 1
    a = assets[0]
    assert a.kind == "footage"
    assert a.description == "a wide establishing shot"
    assert a.duration_sec == 1.5


def test_scan_footage_none_dir_returns_empty():
    assert _scan_footage(None) == []


@pytest.mark.asyncio
async def test_discover_assets_generated_plus_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "ffprobe_duration", lambda p: None)
    store = _store_with_scroll([
        {"asset_path": "/gen/img1.png", "caption": "hero shot", "prompt": "a hero",
         "created_at": "2026-01-01"},
        {"caption": "no path, skipped"},
    ])
    (tmp_path / "b.mov").write_bytes(b"x")
    assets = await discover_assets(store, "proj", str(tmp_path))
    kinds = sorted(a.kind for a in assets)
    assert kinds == ["footage", "generated"]
    gen = next(a for a in assets if a.kind == "generated")
    assert gen.path == "/gen/img1.png" and gen.prompt == "a hero"
