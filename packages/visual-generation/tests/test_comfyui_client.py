from __future__ import annotations

import json

import httpx
import pytest

from visual_generation.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIUnreachable,
)


def _client(handler) -> ComfyUIClient:
    return ComfyUIClient("http://pod.example:8188", transport=httpx.MockTransport(handler))


# ── submit (/prompt) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_posts_graph_and_returns_prompt_id() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"prompt_id": "abc123", "node_errors": {}})

    pid = await _client(handler).submit({"3": {"class_type": "KSampler"}}, client_id="cli-1")

    assert pid == "abc123"
    assert seen["method"] == "POST"
    assert seen["url"] == "http://pod.example:8188/prompt"
    assert seen["body"]["prompt"] == {"3": {"class_type": "KSampler"}}
    assert seen["body"]["client_id"] == "cli-1"


@pytest.mark.asyncio
async def test_submit_raises_on_node_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prompt_id": "x", "node_errors": {"3": "bad"}})

    with pytest.raises(ComfyUIError, match="node_errors"):
        await _client(handler).submit({})


@pytest.mark.asyncio
async def test_submit_raises_on_http_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ComfyUIError, match="500"):
        await _client(handler).submit({})


# ── history (/history/{id}) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_unwraps_run_record() -> None:
    record = {"outputs": {"9": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/history/pid-9"
        return httpx.Response(200, json={"pid-9": record})

    out = await _client(handler).history("pid-9")
    assert out == record


@pytest.mark.asyncio
async def test_history_returns_empty_when_not_yet_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert await _client(handler).history("pid-9") == {}


def test_images_from_history_extracts_descriptors() -> None:
    record = {
        "outputs": {
            "9": {"images": [{"filename": "a.png", "subfolder": "sub", "type": "output"}]},
            "10": {"images": [{"filename": "b.png"}]},
            "11": {"text": ["not an image"]},
        }
    }
    imgs = ComfyUIClient.images_from_history(record)
    assert {"filename": "a.png", "subfolder": "sub", "type": "output"} in imgs
    # Missing subfolder/type default cleanly.
    assert {"filename": "b.png", "subfolder": "", "type": "output"} in imgs
    assert len(imgs) == 2


# ── view (/view) ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_passes_query_params_and_returns_bytes() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, content=b"\x89PNGdata")

    data = await _client(handler).view("img.png", subfolder="batch1", type="output")
    assert data == b"\x89PNGdata"
    assert seen["path"] == "/view"
    assert seen["params"] == {"filename": "img.png", "subfolder": "batch1", "type": "output"}


# ── object_info (/object_info) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_object_info_returns_parsed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/object_info"
        return httpx.Response(200, json={"KSampler": {"input": {}}})

    info = await _client(handler).object_info()
    assert "KSampler" in info


# ── unreachable endpoint ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unreachable_endpoint_raises_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ComfyUIUnreachable, match="unreachable"):
        await _client(handler).object_info()


def test_base_url_required() -> None:
    with pytest.raises(ValueError):
        ComfyUIClient("")


def test_base_url_trailing_slash_stripped() -> None:
    assert ComfyUIClient("http://x:8188/").base_url == "http://x:8188"
