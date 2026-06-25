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
from visual_generation.models import (
    LoraRef,
    ModelAsset,
    VisualGeneration,
    VisualSource,
    VisualSpec,
    WorkflowTemplate,
)
from visual_generation.slot_inference import infer_slots


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


def test_redraft_spec_is_generated_as_text2img(tmp_path: Path, flux_template) -> None:
    # A redraft spec carries revised_from (lineage) but source=None. generate must treat
    # it as plain text2img: no source upload, no parent_id/chain lineage from revised_from.
    fake = _FakeComfy()  # NB: _FakeComfy has NO upload_image — any source path would AttributeError.
    store = _store()
    spec = _spec(revised_from="gen-parent", source=None)

    spend_generation_sync(
        _plan(flux_template, spec), endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    gen = store.upsert_generation.call_args[0][0]
    # revised_from does NOT drive source provisioning — this is a fresh text2img render.
    assert gen.parent_id is None
    assert gen.source_image_path is None
    assert gen.source_mask_path is None
    # A txt2img generation roots its own chain.
    assert gen.chain_root_id == gen.entry_id


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


# ── refinement (img2img / inpaint): source resolution + parent_id lineage ─────


class _FakeComfyUpload(_FakeComfy):
    """_FakeComfy + a recording upload_image (the pod-side seam the source loop uses)."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads: list[tuple[str, bytes]] = []

    async def upload_image(self, data, filename, *, subfolder="", overwrite=True) -> str:
        self.uploads.append((filename, data))
        return f"input/{filename}"


def _img2img_template(*, with_mask: bool) -> WorkflowTemplate:
    graph: dict = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "z.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
    }
    if with_mask:
        graph["12"] = {"class_type": "LoadImageMask", "inputs": {"image": "", "channel": "red"}}
        graph["11"] = {"class_type": "VAEEncodeForInpaint", "inputs": {
            "pixels": ["10", 0], "vae": ["4", 2], "mask": ["12", 0]}}
    else:
        graph["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}}
    graph["3"] = {"class_type": "KSampler", "inputs": {
        "seed": 0, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "normal",
        "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["6", 0],
        "latent_image": ["11", 0]}}
    inferred = infer_slots(graph)
    return WorkflowTemplate(
        name="z-img2img", descriptor="img2img", graph=graph,
        slot_map=inferred.slot_map, required_models=inferred.required_models,
    )


def _source_plan(template: WorkflowTemplate, spec: VisualSpec) -> GenerationPlan:
    graph, unmapped = build_prompt_graph(spec, template)
    return GenerationPlan(
        project=spec.project,
        plans=[SpecPlan(spec=spec, template=template, graph=graph, resolved_seed=spec.seed, unmapped=unmapped)],
        per_run_estimate_usd=0.05, estimate_source="default", gpu_rate_usd_per_hr=3.0,
    )


def test_from_generation_resolves_uploads_and_sets_parent_lineage(tmp_path: Path, flux_template) -> None:
    parent_file = tmp_path / "parentframe.png"
    parent_file.write_bytes(b"\x89PNGparent")
    parent = VisualGeneration(
        entry_id="gen-parent", caption="c", asset_path=str(parent_file), chain_root_id="root-1"
    )
    store = _store()
    store.get_generation = AsyncMock(return_value=parent)
    fake = _FakeComfyUpload()
    spec = _spec(source=VisualSource(from_generation="gen-parent"), workflow_ref="z-img2img")

    spend_generation_sync(
        _source_plan(_img2img_template(with_mask=False), spec),
        endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    # The parent's frame was uploaded with a collision-proof (spec-id-prefixed) name.
    assert len(fake.uploads) == 1
    assert fake.uploads[0][0] == f"{spec.spec_id}_parentframe.png"
    assert fake.uploads[0][1] == b"\x89PNGparent"
    # The returned pod-side filename landed in the LoadImage init_image slot.
    assert fake.submitted[0]["10"]["inputs"]["image"] == f"input/{spec.spec_id}_parentframe.png"
    # Lineage: parent_id set, chain_root_id INHERITED from the parent.
    gen = store.upsert_generation.call_args[0][0]
    assert gen.parent_id == "gen-parent"
    assert gen.chain_root_id == "root-1"
    assert gen.source_image_path == str(parent_file)


def test_image_path_source_uploads_and_records_provenance_no_parent(tmp_path: Path, flux_template) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNGref")
    store = _store()
    store.get_generation = AsyncMock()
    fake = _FakeComfyUpload()
    spec = _spec(source=VisualSource(image_path=str(ref)), workflow_ref="z-img2img")

    spend_generation_sync(
        _source_plan(_img2img_template(with_mask=False), spec),
        endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    store.get_generation.assert_not_called()  # external image → no memory lookup
    gen = store.upsert_generation.call_args[0][0]
    assert gen.parent_id is None
    assert gen.chain_root_id == gen.entry_id  # its own chain root
    assert gen.source_image_path == str(ref)


def test_inpaint_uploads_init_and_mask(tmp_path: Path, flux_template) -> None:
    init = tmp_path / "init.png"
    init.write_bytes(b"i")
    mask = tmp_path / "mask.png"
    mask.write_bytes(b"m")
    store = _store()
    fake = _FakeComfyUpload()
    spec = _spec(source=VisualSource(image_path=str(init), mask=str(mask)), workflow_ref="z-img2img")

    spend_generation_sync(
        _source_plan(_img2img_template(with_mask=True), spec),
        endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    names = [n for n, _ in fake.uploads]
    assert names == [f"{spec.spec_id}_init.png", f"{spec.spec_id}_mask_mask.png"]
    # Both slots written into the graph.
    assert fake.submitted[0]["10"]["inputs"]["image"] == f"input/{spec.spec_id}_init.png"
    assert fake.submitted[0]["12"]["inputs"]["image"] == f"input/{spec.spec_id}_mask_mask.png"
    gen = store.upsert_generation.call_args[0][0]
    assert gen.source_mask_path == str(mask)


def test_source_against_txt2img_template_skips_with_reason(tmp_path: Path, flux_template) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"r")
    store = _store()
    fake = _FakeComfyUpload()
    # flux_template is txt2img — it has no init_image slot.
    spec = _spec(source=VisualSource(image_path=str(ref)), workflow_ref="flux-txt2img")

    result = spend_generation_sync(
        _source_plan(flux_template, spec),
        endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    store.upsert_generation.assert_not_called()
    assert spec.spec_id in result.skipped
    assert any("no init_image slot" in r for r in result.skip_reasons)


def test_missing_parent_generation_skips_with_reason_no_upload(tmp_path: Path, flux_template) -> None:
    store = _store()
    store.get_generation = AsyncMock(return_value=None)  # parent not in memory
    fake = _FakeComfyUpload()
    spec = _spec(source=VisualSource(from_generation="ghost"), workflow_ref="z-img2img")

    result = spend_generation_sync(
        _source_plan(_img2img_template(with_mask=False), spec),
        endpoint="x", gpu_rate=3.0, store=store, client=fake,
        ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )

    assert fake.uploads == []  # bailed before any upload
    store.upsert_generation.assert_not_called()
    assert any("ghost" in r and "not found" in r for r in result.skip_reasons)


def test_sourceless_spend_uploads_nothing(tmp_path: Path, flux_template) -> None:
    fake = _FakeComfyUpload()
    spend_generation_sync(
        _plan(flux_template, _spec()), endpoint="x", gpu_rate=3.0, store=_store(),
        client=fake, ledger=GpuLedger(tmp_path / "ledger.json"), clock=_clock(),
    )
    assert fake.uploads == []  # text-to-image path never uploads


# ── plan-phase: runtime denoise default + coherence warning ──────────────────


def _source_batch_file(tmp_path: Path, ref: Path, **spec_overrides) -> Path:
    from visual_generation.batch_file import write_batch
    from visual_generation.models import GenerationBatch

    spec = _spec(
        heading="refine", workflow_ref="z-img2img",
        source=VisualSource(image_path=str(ref)), **spec_overrides,
    )
    path = tmp_path / "p.batch.md"
    write_batch(GenerationBatch(project="proj", specs=[spec]), path)
    return path


def test_plan_injects_runtime_denoise_default_without_warning(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"r")
    template = _img2img_template(with_mask=False)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    store.recent_generation_costs = AsyncMock(return_value=[])
    store.get_generation = AsyncMock()
    # spec has no explicit denoise → runtime default injected into the graph only.
    path = _source_batch_file(tmp_path, ref, settings={})

    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())

    sp = plan.plans[0]
    assert sp.graph["3"]["inputs"]["denoise"] == 0.5  # DEFAULT_DENOISE, runtime graph
    assert sp.warnings == []


def test_plan_warns_on_incoherent_denoise(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"r")
    template = _img2img_template(with_mask=False)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    store.recent_generation_costs = AsyncMock(return_value=[])
    store.get_generation = AsyncMock()
    path = _source_batch_file(tmp_path, ref, settings={"denoise": 0.95})

    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())

    assert any("coherence" in w for w in plan.plans[0].warnings)
