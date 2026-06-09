"""Async HTTP client for a ComfyUI endpoint.

v1 talks ONLY to the ComfyUI endpoint the user provides (no RunPod credential —
pod start/stop is Tier-1 advisory per Q4). The base URL is passed in; the agent
often runs with no pod up, so an unreachable endpoint surfaces as a clean
`ComfyUIUnreachable` rather than a raw httpx error.

Surface (the native ComfyUI API, "Export Workflow (API)" format):
  - submit(graph)          POST /prompt            → prompt_id
  - history(prompt_id)     GET  /history/{id}      → the run record (outputs/status)
  - view(filename, ...)    GET  /view              → asset bytes
  - object_info()          GET  /object_info       → installed nodes/models

/ws live progress is deferred to Step 4 (the poll loop): a connect method with no
consumer here would be dead, untestable code. Step 4's poll loop is served by
`/history` polling and can add `/ws` there if live progress is wanted.
"""

from __future__ import annotations

from typing import Any

import httpx

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

    async def view(
        self, filename: str, *, subfolder: str = "", type: str = "output"
    ) -> bytes:
        """GET /view for one asset and return its raw bytes."""
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        response = await self._request("GET", "/view", params=params)
        return response.content

    async def object_info(self) -> dict[str, Any]:
        """GET /object_info — the full node/model enumeration (parsed by model_sync)."""
        response = await self._request("GET", "/object_info")
        return response.json()
