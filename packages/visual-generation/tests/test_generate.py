from __future__ import annotations

import itertools
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.generate import (
    GenerationPlan,
    SpecPlan,
    plan_generation_sync,
    spend_generation_sync,
)
from visual_generation.graph_build import build_prompt_graph
from visual_generation.gpu_tracker import GpuLedger
from visual_generation.models import LoraRef, ModelAsset, VisualSpec


class _FakeComfy:
    """A ComfyUI client double: records submits, returns one image immediately."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    async def submit(self, graph: dict, client_id=None) -> str:
        self.submitted.append(graph)
        return "pid-1"

    async def history(self, prompt_id: str) -> dict:
        return {"outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}}

    async def view(self, filename, subfolder="", type="output") -> bytes:
        return b"\x89PNGdata"

    images_from_history = staticmethod(ComfyUIClient.images_from_history)


def _spec(**overrides) -> VisualSpec:
    base = dict(
        prompt="a wolf in neon rain",
        model="flux1-dev.safetensors",
        seed=42,
        width=1024,
        height=1024,
        settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5},
        workflow_ref="flux-txt2img",
        project="proj",
    )
    base.update(overrides)
    return VisualSpec(**base)


def _plan(flux_template, spec: VisualSpec, *, per_run_estimate=0.05) -> GenerationPlan:
    graph, unmapped = build_prompt_graph(spec, flux_template)
    return GenerationPlan(
        project=spec.project,
        plans=[SpecPlan(spec=spec, template=flux_template, graph=graph, resolved_seed=spec.seed, unmapped=unmapped)],
        per_run_estimate_usd=per_run_estimate,
        estimate_source="default",
        gpu_rate_usd_per_hr=3.0,
    )


def _store(get_model=lambda name: None) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_generation = AsyncMock()
    store.get_model = get_model
    return store


def _clock():
    return itertools.count(0, 10).__next__


# ── spend: the happy path ────────────────────────────────────────────────────


def test_spend_submits_built_graph_and_writes_pending_generation(tmp_path: Path, flux_template) -> None:
    fake = _FakeComfy()
    store = _store()
    plan = _plan(flux_template, _spec())

    result = spend_generation_sync(
        plan, endpoint="http://pod:8188", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    # The concrete graph (prompt written via slot_map) was submitted.
    assert fake.submitted[0]["6"]["inputs"]["text"] == "a wolf in neon rain"

    # A PENDING generation was upserted, with a recorded per-run GPU cost.
    gen = store.upsert_generation.call_args[0][0]
    assert gen.status == "pending"
    assert gen.reaction == "pending"
    assert gen.cost_usd > 0
    assert gen.seed == 42

    # The asset was written to disk (non-identity → assets dir).
    assert gen.asset_path is not None and Path(gen.asset_path).exists()
    assert "/assets/" in gen.asset_path

    assert result.items_processed == 1
    assert result.session_cost_usd > 0
    assert result.drained is True


def test_identity_derivation_overrides_the_file_for_the_write_path(tmp_path: Path, flux_template) -> None:
    # The spec DECLARES non-identity, but a LoRA in the stack is registry-flagged.
    spec = _spec(identity_bearing=False, lora_stack=[LoraRef(name="char-lora.safetensors", strength=0.8)])
    registry = {"char-lora.safetensors": ModelAsset(name="char-lora.safetensors", kind="lora", identity_bearing=True)}
    store = _store(get_model=lambda name: registry.get(name))
    fake = _FakeComfy()

    spend_generation_sync(
        _plan(flux_template, spec), endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    gen = store.upsert_generation.call_args[0][0]
    # Derivation overrode the file: written to the SECURED identity path.
    assert gen.identity_bearing is True
    assert "/identity/" in gen.asset_path


def test_max_session_cost_ceiling_stops_before_spending(tmp_path: Path, flux_template) -> None:
    fake = _FakeComfy()
    store = _store()
    # Estimate above the ceiling → the first iteration breaks before any submit.
    plan = _plan(flux_template, _spec(), per_run_estimate=1.0)

    result = spend_generation_sync(
        plan, endpoint="x", gpu_rate=3.0, max_session_cost=0.50, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    assert fake.submitted == []          # nothing submitted
    assert result.items_processed == 0
    assert result.status == "partial"
    assert result.drained is False
    store.upsert_generation.assert_not_called()


def test_ledger_accumulates_session_cost(tmp_path: Path, flux_template) -> None:
    ledger = GpuLedger(tmp_path / "ledger.json")
    spend_generation_sync(
        _plan(flux_template, _spec()), endpoint="x", gpu_rate=3.0, store=_store(),
        client=_FakeComfy(), ledger=ledger, clock=_clock(),
    )
    assert ledger.cumulative() > 0


# ── plan: estimate seeding from the batch ────────────────────────────────────


def _plan_store(flux_template, costs: list[float]) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.recent_generation_costs = AsyncMock(return_value=costs)
    return store


def _write_batch_file(tmp_path: Path) -> Path:
    from visual_generation.batch_file import write_batch
    from visual_generation.models import GenerationBatch

    path = tmp_path / "p.batch.md"
    write_batch(GenerationBatch(project="proj", specs=[_spec(heading="wolf")]), path)
    return path


def test_plan_cold_start_uses_default_estimate(tmp_path: Path, flux_template) -> None:
    path = _write_batch_file(tmp_path)
    store = _plan_store(flux_template, costs=[])
    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())

    assert len(plan.plans) == 1
    assert plan.estimate_source == "default"
    assert plan.estimated_session_cost_usd == pytest.approx(plan.per_run_estimate_usd)


def test_plan_learns_estimate_from_prior_costs(tmp_path: Path, flux_template) -> None:
    path = _write_batch_file(tmp_path)
    store = _plan_store(flux_template, costs=[0.10, 0.30])
    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())

    assert plan.estimate_source == "learned"
    assert plan.per_run_estimate_usd == pytest.approx(0.20)


def test_plan_skips_specs_without_a_resolvable_template(tmp_path: Path) -> None:
    path = _write_batch_file(tmp_path)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=None)  # template not registered
    store.recent_generation_costs = AsyncMock(return_value=[])
    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())

    assert plan.plans == []
    assert len(plan.skipped) == 1
