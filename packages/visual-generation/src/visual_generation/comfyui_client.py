"""Async HTTP client for a ComfyUI endpoint.

v1 talks ONLY to the ComfyUI endpoint the user provides (no RunPod credential —
pod start/stop is Tier-1 advisory per Q4). The base URL is passed in; the agent
often runs with no pod up, so an unreachable endpoint surfaces as a clean
`ComfyUIUnreachable` rather than a raw httpx error.

Surface (the native ComfyUI API, "Export Workflow (API)" format):
  - submit(graph)          POST /prompt            → prompt_id
  - history(prompt_id)     GET  /history/{id}      → the run record (outputs/status)
  - view(filename, ...)    GET  /view              → asset bytes
  - upload_image(data, …)  POST /upload/image      → pod-side input filename
  - object_info()          GET  /object_info       → installed nodes/models

/ws live progress is deferred to Step 4 (the poll loop): a connect method with no
consumer here would be dead, untestable code. Step 4's poll loop is served by
`/history` polling and can add `/ws` there if live progress is wanted.
"""

from __future__ import annotations

from typing import Any

import httpx

from visual_generation.constants import VIDEO_ASSET_EXTS

_DEFAULT_TIMEOUT = 30.0


class ComfyUIError(RuntimeError):
    """A ComfyUI request reached the server but failed (bad status, node errors)."""


class ComfyUIUnreachable(ComfyUIError):
    """The ComfyUI endpoint could not be reached (no pod up, wrong URL, timeout)."""


class ComfyUIClient:
    """Thin async wrapper over the native ComfyUI HTTP API.

    `transport` is an injection seam for tests (an `httpx.MockTransport`); in
    normal use it is None and httpx opens real connections.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required (the ComfyUI endpoint URL)")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with self._client() as client:
                response = await client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise ComfyUIUnreachable(
                f"ComfyUI endpoint unreachable at {self._base_url} ({type(exc).__name__}). "
                "Is a pod up and the endpoint correct?"
            ) from exc
        if response.status_code >= 400:
            raise ComfyUIError(
                f"ComfyUI {method} {path} returned {response.status_code}: {response.text[:300]}"
            )
        return response

    async def submit(self, prompt_graph: dict[str, Any], *, client_id: str | None = None) -> str:
        """POST an API-format graph to /prompt and return its prompt_id.

        Raises ComfyUIError if the server reports node_errors (a malformed graph).
        """
        body: dict[str, Any] = {"prompt": prompt_graph}
        if client_id is not None:
            body["client_id"] = client_id
        response = await self._request("POST", "/prompt", json=body)
        data = response.json()
        node_errors = data.get("node_errors")
        if node_errors:
            raise ComfyUIError(f"ComfyUI rejected the graph (node_errors): {node_errors}")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI /prompt returned no prompt_id: {data}")
        return prompt_id

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """GET /history/{prompt_id} and return that run's record.

        Returns the inner record ({"outputs": ..., "status": ...}), or {} if the
        prompt_id is not yet in history (still queued/running).
        """
        response = await self._request("GET", f"/history/{prompt_id}")
        data = response.json()
        return data.get(prompt_id, {})

    @staticmethod
    def images_from_history(record: dict[str, Any]) -> list[dict[str, str]]:
        """Extract image output descriptors ({filename, subfolder, type}) from a
        history record — the inputs `view()` needs to fetch the bytes."""
        images: list[dict[str, str]] = []
        for node_output in (record.get("outputs") or {}).values():
            for img in node_output.get("images", []) or []:
                images.append(
                    {
                        "filename": img.get("filename", ""),
                        "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "output"),
                    }
                )
        return images

    @staticmethod
    def videos_from_history(record: dict[str, Any]) -> list[dict[str, str]]:
        """Extract video output descriptors ({filename, subfolder, type}) from a
        history record, unioning the shapes a SaveVideo node can produce.

        The history key for a video output varies by node. Confirmed against ComfyUI
        master source: native `SaveVideo` returns `ui.PreviewVideo(...)`, which
        serialises as `{"images": [...], "animated": (True,)}` (comfy_api/latest/_ui.py
        `PreviewVideo.as_dict`) — i.e. video descriptors land under **"images"** with an
        `"animated"` flag, NOT a `"videos"` key. The third-party VHS `VideoCombine` node
        uses `"gifs"`. So we collect, in order of authority: (1) an `animated`-flagged
        node's `images`; (2) explicit `videos`/`gifs` keys; (3) a filename-extension
        sweep (`VIDEO_ASSET_EXTS`) over every list output as a version-agnostic backstop.
        Descriptors are deduped by (filename, subfolder, type); `view()` fetches the
        bytes exactly as for images.
        """
        videos: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def _add(item: Any) -> None:
            if not isinstance(item, dict):
                return
            filename = item.get("filename", "")
            if not filename:
                return
            desc = {
                "filename": filename,
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            }
            key = (desc["filename"], desc["subfolder"], desc["type"])
            if key not in seen:
                seen.add(key)
                videos.append(desc)

        for node_output in (record.get("outputs") or {}).values():
            if not isinstance(node_output, dict):
                continue
            # 1) native SaveVideo: PreviewVideo → images[] + a truthy "animated" flag.
            if node_output.get("animated"):
                for item in node_output.get("images", []) or []:
                    _add(item)
            # 2) explicit named keys: some builds use "videos"; VHS VideoCombine "gifs".
            for named in ("videos", "gifs"):
                for item in node_output.get(named, []) or []:
                    _add(item)
            # 3) extension sweep: any list-of-dicts output whose filename ends in a known
            #    video extension — the version-agnostic backstop (also catches an mp4
            #    under "images" if a build omits the animated flag).
            for value in node_output.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if isinstance(item, dict):
                        fn = item.get("filename", "")
                        if isinstance(fn, str) and fn.lower().endswith(VIDEO_ASSET_EXTS):
                            _add(item)
        return videos

    async def view(
        self, filename: str, *, subfolder: str = "", type: str = "output"
    ) -> bytes:
        """GET /view for one asset and return its raw bytes."""
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        response = await self._request("GET", "/view", params=params)
        return response.content

    async def upload_image(
        self,
        data: bytes,
        filename: str,
        *,
        subfolder: str = "",
        overwrite: bool = True,
    ) -> str:
        """POST raw image bytes to /upload/image; return the pod-side filename.

        ComfyUI's LoadImage reads from the pod's input dir, so an init image / mask
        must be uploaded before a graph can reference it. The returned name (prefixed
        with the subfolder when ComfyUI nests it) is what goes into the LoadImage
        `image` input. Callers should pass a collision-proof `filename` (e.g. prefixed
        with the spec/generation id) since the input dir is shared and overwrite=True.
        """
        files = {"image": (filename, data, "application/octet-stream")}
        form: dict[str, str] = {"overwrite": "true" if overwrite else "false"}
        if subfolder:
            form["subfolder"] = subfolder
        response = await self._request("POST", "/upload/image", files=files, data=form)
        body = response.json()
        name = body.get("name")
        if not name:
            raise ComfyUIError(f"ComfyUI /upload/image returned no name: {body}")
        sub = body.get("subfolder", "")
        return f"{sub}/{name}" if sub else name

    async def object_info(self) -> dict[str, Any]:
        """GET /object_info — the full node/model enumeration (parsed by model_sync)."""
        response = await self._request("GET", "/object_info")
        return response.json()
