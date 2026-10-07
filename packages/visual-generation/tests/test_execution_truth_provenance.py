"""Entry-gate item 6 (and the seed assertion): the exact submitted graph and the input/output
hashes are saved beside every output, and the stored record agrees with what was submitted."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from visual_generation.batch_file import write_batch
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.generate import plan_generation_sync, spend_generation_sync
from visual_generation.gpu_tracker import GpuLedger
from visual_generation.models import (
    GenerationBatch,
    LoraRef,
    ModelAsset,
    VisualGeneration,
    VisualSource,
    VisualSpec,
    WorkflowTemplate,
)

PNG = b"\x89PNG-output-bytes"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def spec(**kw) -> VisualSpec:
    base = dict(prompt="a plain red mug on a white table", seed=42, width=1024, height=1024,
                settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5}, model="flux1-dev.safetensors",
                workflow_ref="flux-txt2img", project="proj")
    base.update(kw)
    return VisualSpec(**base)


class FakeComfy:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.uploads: list[tuple[str, bytes]] = []

    async def submit(self, graph, client_id=None):
        self.submitted.append(json.loads(json.dumps(graph)))      # what the pod received
        return "pid-7"

    async def history(self, pid):
        return {"outputs": {"9": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}

    async def view(self, filename, subfolder="", type="output"):
        return PNG

    async def upload_image(self, data, filename, *, subfolder="", overwrite=True):
        self.uploads.append((filename, data))
        return f"input/{filename}"

    images_from_history = staticmethod(ComfyUIClient.images_from_history)


def store_double(registry: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_generation = AsyncMock()
    store.get_model = (registry or {}).get
    return store


def plan(tmp: Path, template: WorkflowTemplate, *specs: VisualSpec, registry: dict | None = None):
    path = tmp / "b.batch.md"
    write_batch(GenerationBatch(project="proj", specs=list(specs)), path)
    ps = MagicMock()
    ps.ensure_collection = AsyncMock()
    ps.get_template_by_name = AsyncMock(return_value=template)
    ps.recent_generation_costs = AsyncMock(return_value=[])
    ps.get_model = (registry or {}).get
    return plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=ps, memory_store=MagicMock())


def spend(p, tmp: Path, client, store=None):
    store = store or store_double()
    result = spend_generation_sync(p, endpoint="http://pod:8188", gpu_rate=3.0, store=store, client=client,
                                   ledger=GpuLedger(tmp / "ledger.json"), clock=itertools.count(0, 10).__next__)
    return result, store


def seed_target(template: WorkflowTemplate) -> tuple[str, str]:
    t = template.slot_map["seed"]
    return t["node_id"], t["input_key"]


def files_for(gen: VisualGeneration) -> tuple[Path, Path]:
    asset = Path(gen.asset_path)
    return asset.parent / f"{asset.stem}.graph.json", asset.parent / f"{asset.stem}.provenance.json"


# ── the sidecar files ─────────────────────────────────────────────────────────


def test_the_exact_submitted_graph_is_saved_beside_the_asset(tmp_path: Path, flux_template) -> None:
    fake = FakeComfy()
    _, store = spend(plan(tmp_path, flux_template, spec()), tmp_path, fake)
    gen = store.upsert_generation.call_args[0][0]
    graph_file, prov_file = files_for(gen)
    assert graph_file.exists() and prov_file.exists()
    assert json.loads(graph_file.read_text()) == fake.submitted[0]            # what the pod received
    assert gen.submitted_graph_sha256 == sha(graph_file.read_bytes())          # the hash is of the file
    assert gen.provenance_path == str(prov_file)


def test_the_provenance_record_has_the_charter_fields(tmp_path: Path, flux_template) -> None:
    fake = FakeComfy()
    _, store = spend(plan(tmp_path, flux_template, spec(lora_stack=[])), tmp_path, fake)
    gen = store.upsert_generation.call_args[0][0]
    _, prov_file = files_for(gen)
    prov = json.loads(prov_file.read_text())
    assert prov["generation_id"] == gen.entry_id and prov["prompt_id"] == "pid-7"
    assert prov["endpoint"] == "http://pod:8188" and prov["project"] == "proj"
    assert prov["workflow"]["name"] == "flux-txt2img"
    assert prov["workflow"]["sha256"] == sha(json.dumps(flux_template.graph, sort_keys=True, separators=(",", ":"),
                                                         ensure_ascii=False).encode())
    assert prov["submitted_graph_sha256"] == gen.submitted_graph_sha256
    assert prov["outputs"] == [{"path": gen.asset_path, "sha256": sha(PNG)}]
    assert prov["model"]["name"] == "flux1-dev.safetensors" and prov["model"]["sha256"] is None
    assert {"started_at", "completed_at"} <= set(prov["timing"]) and prov["unmapped"] == []
    assert prov["resolved_seed"] == 42 and prov["seed_slot"] == dict(zip(("node_id", "input_key"), seed_target(flux_template)))


def test_the_graph_is_hashed_as_submitted_even_if_the_client_mutates_it(tmp_path: Path, flux_template) -> None:
    class Mutating(FakeComfy):
        async def submit(self, graph, client_id=None):
            pid = await super().submit(graph)
            graph.clear()                                  # a client that scribbles on its argument
            return pid

    fake = Mutating()
    _, store = spend(plan(tmp_path, flux_template, spec()), tmp_path, fake)
    gen = store.upsert_generation.call_args[0][0]
    assert json.loads(files_for(gen)[0].read_text()) == fake.submitted[0] and fake.submitted[0]


def test_old_generation_payloads_still_load() -> None:
    old = VisualGeneration(caption="c").to_payload()
    old.pop("submitted_graph_sha256", None)
    old.pop("provenance_path", None)
    g = VisualGeneration.from_payload(old)
    assert g.submitted_graph_sha256 is None and g.provenance_path is None


def test_a_skipped_spec_leaves_no_files(tmp_path: Path, flux_template) -> None:
    class NoImage(FakeComfy):
        async def history(self, pid):
            return {"outputs": {"9": {"images": []}}}          # finished, but produced no image

    _, store = spend(plan(tmp_path, flux_template, spec()), tmp_path, NoImage())
    store.upsert_generation.assert_not_called()


# ── the seed assertion, through the real client on a mock transport ──────────


def _mock_client(captured: list[dict]) -> ComfyUIClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/prompt":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"prompt_id": "pm-1"})
        if request.url.path == "/history/pm-1":
            return httpx.Response(200, json={"pm-1": {"outputs": {"9": {"images": [
                {"filename": "o.png", "subfolder": "", "type": "output"}]}}}})
        if request.url.path == "/view":
            return httpx.Response(200, content=PNG)
        return httpx.Response(404)

    return ComfyUIClient("http://pod:8188", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("kw,expect_fixed", [
    (dict(seed=123456789, seed_strategy="fixed"), 123456789),
    (dict(seed=None, seed_strategy="random"), None),
    (dict(seed=42, seed_strategy="random"), None),                 # random overrides a leftover seed
])
def test_the_seed_on_the_record_equals_the_seed_the_client_posted(tmp_path: Path, flux_template, kw, expect_fixed) -> None:
    posted: list[dict] = []
    _, store = spend(plan(tmp_path, flux_template, spec(**kw)), tmp_path, _mock_client(posted))
    gen = store.upsert_generation.call_args[0][0]
    node, key = seed_target(flux_template)
    wire_seed = posted[0]["prompt"][node]["inputs"][key]
    prov = json.loads(files_for(gen)[1].read_text())
    assert wire_seed == gen.seed == prov["resolved_seed"] == prov["graph_seed"]
    if expect_fixed is not None:
        assert wire_seed == expect_fixed
    assert json.loads(files_for(gen)[0].read_text()) == posted[0]["prompt"]


def test_two_random_runs_post_different_seeds_and_record_both(tmp_path: Path, flux_template) -> None:
    posted: list[dict] = []
    seeds = []
    for i in range(2):
        d = tmp_path / str(i)
        d.mkdir()
        _, store = spend(plan(d, flux_template, spec(seed=None, seed_strategy="random")), d, _mock_client(posted))
        seeds.append(store.upsert_generation.call_args[0][0].seed)
    node, key = seed_target(flux_template)
    assert seeds[0] != seeds[1] and [p["prompt"][node]["inputs"][key] for p in posted] == seeds


# ── identity assets: sidecars stay under the secured root ────────────────────


def test_identity_outputs_keep_their_sidecars_in_the_secured_directory(tmp_path: Path, flux_template) -> None:
    reg = {"c.safetensors": ModelAsset(name="c.safetensors", kind="lora", identity_bearing=True)}
    # a template with a loader so the identity LoRA fits
    graph = json.loads(json.dumps(flux_template.graph))
    graph["70"] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"lora_name": "x", "strength_model": 1.0, "model": ["4", 0]}}
    slot_map = {**flux_template.slot_map, "lora_0": {"node_id": "70", "input_key": "lora_name"},
                "lora_0_strength": {"node_id": "70", "input_key": "strength_model"}}
    t = WorkflowTemplate(name="flux-txt2img", descriptor="d", graph=graph, slot_map=slot_map)
    s = spec(lora_stack=[LoraRef(name="c.safetensors", strength=0.9)])
    _, store = spend(plan(tmp_path, t, s, registry=reg), tmp_path, FakeComfy(), store_double(reg))
    gen = store.upsert_generation.call_args[0][0]
    graph_file, prov_file = files_for(gen)
    assert gen.identity_bearing and "/identity/" in gen.asset_path
    assert graph_file.parent == prov_file.parent == Path(gen.asset_path).parent and "/identity/" in str(prov_file)


# ── sources: what was uploaded is hashed ──────────────────────────────────────


def test_source_files_are_hashed_from_the_bytes_that_were_uploaded(tmp_path: Path) -> None:
    import json as _json

    from visual_generation.slot_inference import infer_slots

    wf = Path(__file__).parent.parent / "workflows" / "z-image-turbo-inpaint-lora-api.json"
    g = _json.loads(wf.read_text())
    t = WorkflowTemplate(name="z-inpaint", descriptor="d", graph=g, slot_map=infer_slots(g).slot_map)
    init, mask = tmp_path / "base.png", tmp_path / "mask.png"
    init.write_bytes(b"\x89PNG-init-bytes")
    mask.write_bytes(b"\x89PNG-mask-bytes")
    s = spec(workflow_ref="z-inpaint", model=None, source=VisualSource(image_path=str(init), mask=str(mask)),
             settings={"steps": 8, "cfg": 1.0, "denoise": 0.6})
    fake = FakeComfy()
    _, store = spend(plan(tmp_path, t, s), tmp_path, fake)
    gen = store.upsert_generation.call_args[0][0]
    prov = json.loads(files_for(gen)[1].read_text())
    by_role = {x["role"]: x for x in prov["sources"]}
    assert by_role["init_image"]["sha256"] == sha(b"\x89PNG-init-bytes")
    assert by_role["mask"]["sha256"] == sha(b"\x89PNG-mask-bytes")
    assert by_role["init_image"]["local_path"] == str(init)
    assert by_role["init_image"]["uploaded_as"] == f"input/{fake.uploads[0][0]}"      # the name the pod returned
    assert by_role["mask"]["uploaded_as"] == f"input/{fake.uploads[1][0]}"
    assert sha(fake.uploads[0][1]) == by_role["init_image"]["sha256"]          # hashed what was sent


def test_a_text2img_run_records_no_sources(tmp_path: Path, flux_template) -> None:
    _, store = spend(plan(tmp_path, flux_template, spec()), tmp_path, FakeComfy())
    prov = json.loads(files_for(store.upsert_generation.call_args[0][0])[1].read_text())
    assert prov["sources"] == []


def test_neutralized_loras_are_recorded(tmp_path: Path, zimage_lora_template) -> None:
    s = spec(workflow_ref="z-image-turbo-lora", model=None, settings={"steps": 8, "cfg": 1.0})
    _, store = spend(plan(tmp_path, zimage_lora_template, s), tmp_path, FakeComfy())
    prov = json.loads(files_for(store.upsert_generation.call_args[0][0])[1].read_text())
    assert prov["neutralized_loras"] == ["narrator-zimage.safetensors"]


# ── quick ─────────────────────────────────────────────────────────────────────


def test_quick_saves_the_graph_and_provenance_beside_its_output(tmp_path: Path, flux_template) -> None:
    from visual_generation.quick import quick_generate_sync

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.get_model = lambda n: None
    fake = FakeComfy()
    out = tmp_path / "mine" / "mug.png"
    r = quick_generate_sync("a plain red mug", endpoint="http://pod:8188", template_name="flux-txt2img", seed=99,
                            store=store, client=fake, out_path=out)
    graph_file, prov_file = out.parent / "mug.graph.json", out.parent / "mug.provenance.json"
    assert json.loads(graph_file.read_text()) == fake.submitted[0]
    prov = json.loads(prov_file.read_text())
    node, key = seed_target(flux_template)
    assert prov["resolved_seed"] == 99 == prov["graph_seed"] == fake.submitted[0][node]["inputs"][key]
    assert prov["outputs"][0]["sha256"] == sha(PNG) and prov["submitted_graph_sha256"] == sha(graph_file.read_bytes())
    assert r.graph_path == graph_file and r.provenance_path == prov_file
    store.upsert_generation.assert_not_called() if hasattr(store, "upsert_generation") else None
