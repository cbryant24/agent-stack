"""Shared doubles for the generation and pod tool tests: a ComfyUI served by httpx.MockTransport,
and a stand-in for the agent-shell Session (audit log, dry-run switch, GPU budget)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
from agent_shell.audit.log import AuditLog
from agent_shell.guard.gate import Budget

from visual_generation.batch_file import write_batch
from visual_generation.chat.state import ChatState
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.models import GenerationBatch, VisualSpec

PLAN = dict(
    question="Does each saved seed equal the seed in the submitted graph?", baseline_attempt=None,
    hypothesis="Random seeds differ and the fixed seed is honored.", changed_variable="seed strategy",
    controlled_variables=["template flux-txt2img", "prompt"], acceptance_gate="evaluation-charter.md Gate 0",
    stop_rule="stop after 3 renders or the first mismatch", session_cost_cap_usd=0.5,
)


class Comfy:
    """A ComfyUI behind MockTransport. `down` makes every request fail to connect; `empty_polls`
    is how many /history polls return nothing before the image appears."""

    def __init__(self, *, loras: list[str] | None = None, empty_polls: int = 0) -> None:
        self.down = False
        self.loras = loras or []
        self.empty_polls = empty_polls
        self.requests: list[str] = []
        self.submitted: list[dict[str, Any]] = []
        self.drop_after_submits: int | None = None
        self.queue_running = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"os": "posix"}})
        if path == "/object_info":
            return httpx.Response(200, json={
                "LoraLoader": {"input": {"required": {"lora_name": [self.loras]}}},
                "UNETLoader": {"input": {"required": {"unet_name": [["z_image_turbo_bf16.safetensors"]]}}},
            })
        if path == "/prompt":
            if self.drop_after_submits is not None and len(self.submitted) >= self.drop_after_submits:
                self.down = True
                raise httpx.ConnectError("connection reset", request=request)
            import json

            self.submitted.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": f"pid-{len(self.submitted)}"})
        if path == "/queue":
            pid = f"pid-{len(self.submitted)}"
            return httpx.Response(200, json={"queue_running": [[0, pid]] if self.queue_running else [], "queue_pending": []})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[1]
            if self.empty_polls > 0:
                self.empty_polls -= 1
                return httpx.Response(200, json={})
            return httpx.Response(200, json={pid: {"outputs": {"9": {"images": [
                {"filename": "out.png", "subfolder": "", "type": "output"}]}}}})
        if path == "/view":
            return httpx.Response(200, content=b"\x89PNGdata")
        return httpx.Response(404)

    def client(self, endpoint: str) -> ComfyUIClient:
        return ComfyUIClient(endpoint, transport=httpx.MockTransport(self.handle))


def attach(state: ChatState, tmp_path: Path, *, dry_run: bool = False, comfy: Comfy | None = None,
           gpu_budget: float = 5.0) -> tuple[AuditLog, list[str]]:
    """Give the state what run_chat would: a session (audit, dry-run, budget), a notifier, a ComfyUI."""
    audit = AuditLog(tmp_path / "run" / "audit.jsonl")
    state.session = SimpleNamespace(audit=audit, dry_run=dry_run, session_id="sess-1",
                                    budgets=SimpleNamespace(gpu=Budget("gpu", gpu_budget)))
    said: list[str] = []
    state.notify = said.append
    if comfy is not None:
        state.comfy = comfy.client
    return audit, said


def write_specs(state: ChatState, specs: list[VisualSpec], project: str = "demo") -> Path:
    path = state.batch_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_batch(GenerationBatch(project=project, specs=specs), path)
    return path


def spec(spec_id: str, **over: Any) -> VisualSpec:
    base: dict[str, Any] = dict(spec_id=spec_id, prompt=f"prompt {spec_id}", seed=7, workflow_ref="flux-txt2img",
                                project="demo", heading=spec_id)
    return VisualSpec(**{**base, **over})


def wire_generation(store: Any, template: Any, *, costs: list[float] | None = None) -> None:
    """The store calls plan/spend make, on top of the chat conftest's doubles."""
    store.get_template_by_name = AsyncMock(side_effect=lambda name: template if name == template.name else None)
    store.recent_generation_costs = AsyncMock(return_value=costs or [])
    store.get_model = lambda name: None
