from __future__ import annotations

from types import SimpleNamespace

import pytest

from technique_research import grounding


@pytest.mark.asyncio
async def test_tavily_skipped_when_no_key(monkeypatch) -> None:
    monkeypatch.setattr(grounding, "get_config", lambda: SimpleNamespace(tavily_api_key=None))
    assert await grounding.tavily_reference_search("Xenoz edits") == []


@pytest.mark.asyncio
async def test_tavily_degrades_on_error(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(grounding, "_tavily_search_sync", _boom)
    assert await grounding.tavily_reference_search("q") == []


@pytest.mark.asyncio
async def test_url_context_returns_helper_result(monkeypatch) -> None:
    meta = {"title": "Ref clip", "uploader": "chan", "description": "fast cuts"}
    monkeypatch.setattr(grounding, "_fetch_url_metadata_sync", lambda url: meta)
    assert await grounding.fetch_url_context("https://x") == meta


@pytest.mark.asyncio
async def test_url_context_none_when_helper_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(grounding, "_fetch_url_metadata_sync", lambda url: None)
    assert await grounding.fetch_url_context("https://x") is None
