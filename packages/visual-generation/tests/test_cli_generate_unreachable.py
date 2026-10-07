"""Regression: `generate` with no pod reachable prints one line with the fix, never a traceback
(2026-10-07 handoff, §3 item 2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from click.testing import CliRunner

from visual_generation.cli import cli
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.generate import GenerationPlan, SpecPlan, spend_generation
from visual_generation.gpu_tracker import GpuLedger
from visual_generation.graph_build import build_prompt_graph
from visual_generation.models import VisualSpec


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _plan(flux_template) -> GenerationPlan:  # type: ignore[no-untyped-def]
    spec = VisualSpec(prompt="a wolf", seed=1, workflow_ref="flux-txt2img", project="proj")
    graph, unmapped = build_prompt_graph(spec, flux_template)
    return GenerationPlan(
        project="proj",
        plans=[SpecPlan(spec=spec, template=flux_template, graph=graph, resolved_seed=1, unmapped=unmapped)],
        per_run_estimate_usd=0.05,
    )


def test_generate_with_no_pod_prints_one_line_and_no_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flux_template
) -> None:
    batch = tmp_path / "p.batch.md"
    batch.write_text("<!-- vg-batch: {} -->\n\n## s\n\nbody\n", encoding="utf-8")
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_model = lambda name: None

    def spend_sync(plan: GenerationPlan, *, endpoint: str, **kw: object):  # type: ignore[no-untyped-def]
        import asyncio

        kw.pop("on_wait", None)
        client = ComfyUIClient(endpoint, transport=httpx.MockTransport(_down))
        return asyncio.run(spend_generation(
            plan, endpoint=endpoint, store=store, client=client,
            ledger=GpuLedger(tmp_path / "ledger.json"), **kw,  # type: ignore[arg-type]
        ))

    monkeypatch.setattr("visual_generation.cli.plan_generation_sync", lambda *a, **k: _plan(flux_template))
    monkeypatch.setattr("visual_generation.cli.spend_generation_sync", spend_sync)

    out = CliRunner().invoke(cli, ["generate", str(batch), "--all", "--endpoint", "http://127.0.0.1:8188", "--yes"])

    assert out.exit_code == 1
    assert out.exception is None or isinstance(out.exception, SystemExit)     # not a raw ComfyUIUnreachable
    assert "Traceback" not in out.output
    errors = [ln for ln in out.output.splitlines() if ln.startswith("Error:")]
    assert len(errors) == 1
    assert "not reachable at http://127.0.0.1:8188" in errors[0] and "0 of 1 rendered" in errors[0]
    assert "scripts/pod up" in errors[0] and "ssh -N -L 8188" in errors[0]
    assert "Batch drained" not in out.output          # nothing drained, so no stop-your-pod prompt
