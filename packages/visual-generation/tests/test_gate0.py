"""Gate 0 (evaluation-charter): the verifier judges real provenance written by the real spend path."""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


from visual_generation.batch_file import read_batch_diagnosed, write_batch
from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.gate0 import render_record, verify_gate0
from visual_generation.generate import plan_generation_sync, spend_generation_sync
from visual_generation.gpu_tracker import GpuLedger
from visual_generation.models import GenerationBatch, VisualSpec

import importlib

# the package exports a function named `generate` that shadows the submodule
generate_mod = importlib.import_module("visual_generation.generate")

PNG = b"\x89PNG-gate0-output"
FIXED = 12345
DOCS = Path(__file__).parent.parent / "docs" / "gate0"


class Comfy:
    def __init__(self) -> None:
        self.n = 0

    async def submit(self, graph, client_id=None):
        self.n += 1
        return f"pid-{self.n}"

    async def history(self, pid):
        return {"outputs": {"9": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}

    async def view(self, filename, subfolder="", type="output"):
        return PNG + str(self.n).encode()

    images_from_history = staticmethod(ComfyUIClient.images_from_history)


def spec(heading: str, **kw) -> VisualSpec:
    base = dict(heading=heading, prompt="a plain red ceramic mug on a white table", width=1024, height=1024,
                settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5}, model="flux1-dev.safetensors",
                workflow_ref="flux-txt2img", project="gate0")
    base.update(kw)
    return VisualSpec(**base)


def run_gate0(tmp: Path, template, specs: list[VisualSpec]) -> list:
    """Plan + spend the batch for real (fake pod); returns the generations written."""
    path = tmp / "gate0.batch.md"
    write_batch(GenerationBatch(project="gate0", specs=specs), path)
    ps = MagicMock()
    ps.ensure_collection = AsyncMock()
    ps.get_template_by_name = AsyncMock(return_value=template)
    ps.recent_generation_costs = AsyncMock(return_value=[])
    ps.get_model = lambda n: None
    plan = plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=ps, memory_store=MagicMock())
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_generation = AsyncMock()
    store.get_model = lambda n: None
    spend_generation_sync(plan, endpoint="http://pod:8188", gpu_rate=3.0, store=store, client=Comfy(),
                          ledger=GpuLedger(tmp / "ledger.json"), clock=itertools.count(0, 10).__next__)
    return [c.args[0] for c in store.upsert_generation.call_args_list]


def good_specs() -> list[VisualSpec]:
    return [spec("random A", seed=None, seed_strategy="random"), spec("random B", seed=None, seed_strategy="random"),
            spec("fixed", seed=FIXED, seed_strategy="fixed")]


def verify(gens: list, template, **kw):
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_generations = AsyncMock(return_value=gens)
    store.get_template_by_name = AsyncMock(return_value=template)
    store.get_model = lambda n: None
    store.recent_generation_costs = AsyncMock(return_value=[])
    return asyncio.run(verify_gate0("gate0", store=store, template_name="flux-txt2img", fixed_seed=FIXED, **kw))


def by_name(report) -> dict:
    return {c.name: c for c in report.checks}


# ── a clean run passes every criterion ───────────────────────────────────────


def test_a_clean_run_passes_every_criterion(tmp_path: Path, flux_template) -> None:
    report = verify(run_gate0(tmp_path, flux_template, good_specs()), flux_template)
    checks = by_name(report)
    assert report.passed, [(c.name, c.detail) for c in report.checks if not c.passed]
    assert set(checks) == {"seed_matches_graph", "random_seeds_differ", "fixed_seed_honored",
                           "replay_inputs_preserved", "unsupported_slot_refused"}
    assert len(report.generations) == 3


# ── each criterion can fail ───────────────────────────────────────────────────


def test_a_seed_that_differs_from_the_graph_fails(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    graph_file = Path(gens[0].provenance_path).with_name(Path(gens[0].provenance_path).stem.replace(".provenance", "") + ".graph.json")
    graph = json.loads(graph_file.read_text())
    t = flux_template.slot_map["seed"]
    graph[t["node_id"]]["inputs"][t["input_key"]] = 1                    # the graph says 1, the record says otherwise
    graph_file.write_text(json.dumps(graph))
    c = by_name(verify(gens, flux_template))["seed_matches_graph"]
    assert not c.passed and gens[0].entry_id[:8] in c.detail


def test_a_record_seed_that_differs_from_the_provenance_fails(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    gens[1] = gens[1].model_copy(update={"seed": 5})
    assert not by_name(verify(gens, flux_template))["seed_matches_graph"].passed


def test_two_random_runs_with_the_same_seed_fail(tmp_path: Path, flux_template, monkeypatch) -> None:
    monkeypatch.setattr(generate_mod.random, "randint", lambda a, b: 777)
    c = by_name(verify(run_gate0(tmp_path, flux_template, good_specs()), flux_template))["random_seeds_differ"]
    assert not c.passed and "777" in c.detail


def test_a_fixed_seed_that_is_not_the_requested_one_fails(tmp_path: Path, flux_template) -> None:
    specs = [good_specs()[0], good_specs()[1], spec("fixed", seed=999, seed_strategy="fixed")]
    c = by_name(verify(run_gate0(tmp_path, flux_template, specs), flux_template))["fixed_seed_honored"]
    assert not c.passed and "999" in c.detail and str(FIXED) in c.detail


def test_too_few_generations_fail_the_criteria_that_need_them(tmp_path: Path, flux_template) -> None:
    report = verify(run_gate0(tmp_path, flux_template, good_specs()[:1]), flux_template)
    checks = by_name(report)
    assert not checks["random_seeds_differ"].passed and "need 2" in checks["random_seeds_differ"].detail
    assert not checks["fixed_seed_honored"].passed and not report.passed


def test_a_missing_or_altered_graph_file_fails_replay(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    prov = Path(gens[0].provenance_path)
    graph_file = prov.with_name(prov.name.replace(".provenance.json", ".graph.json"))
    graph_file.write_text(graph_file.read_text() + " ")                  # one byte changed: the hash no longer matches
    c = by_name(verify(gens, flux_template))["replay_inputs_preserved"]
    assert not c.passed and "hash" in c.detail
    graph_file.unlink()
    assert "missing" in by_name(verify(gens, flux_template))["replay_inputs_preserved"].detail


def test_an_altered_output_fails_replay(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    Path(gens[2].asset_path).write_bytes(b"not the render")
    c = by_name(verify(gens, flux_template))["replay_inputs_preserved"]
    assert not c.passed and "output" in c.detail


def test_a_generation_with_no_provenance_fails_replay(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    gens[0] = gens[0].model_copy(update={"provenance_path": None, "submitted_graph_sha256": None})
    c = by_name(verify(gens, flux_template))["replay_inputs_preserved"]
    assert not c.passed and "no provenance" in c.detail


def test_the_refusal_check_fails_if_the_plan_would_not_refuse(tmp_path: Path, flux_template, monkeypatch) -> None:
    import visual_generation.gate0 as g

    class NotRefused:
        plans = [object()]
        skipped: list = []
        skip_reasons: dict = {}

    monkeypatch.setattr(g, "plan_generation", AsyncMock(return_value=NotRefused()))
    c = by_name(verify(run_gate0(tmp_path, flux_template, good_specs()), flux_template))["unsupported_slot_refused"]
    assert not c.passed


def test_the_refusal_check_uses_the_registered_template_without_its_seed_slot(tmp_path: Path, flux_template) -> None:
    report = verify(run_gate0(tmp_path, flux_template, good_specs()), flux_template)
    c = by_name(report)["unsupported_slot_refused"]
    assert c.passed and "seed slot" in c.detail


def test_an_unknown_template_fails_the_refusal_check_with_a_reason(tmp_path: Path, flux_template) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_generations = AsyncMock(return_value=[])
    store.get_template_by_name = AsyncMock(return_value=None)
    report = asyncio.run(verify_gate0("gate0", store=store, template_name="nope", fixed_seed=FIXED))
    c = by_name(report)["unsupported_slot_refused"]
    assert not c.passed and "nope" in c.detail


# ── the record ────────────────────────────────────────────────────────────────


def test_the_record_lists_every_check_and_generation(tmp_path: Path, flux_template) -> None:
    gens = run_gate0(tmp_path, flux_template, good_specs())
    text = render_record(verify(gens, flux_template))
    for needle in ("Gate 0", "PASS", "seed_matches_graph", "random_seeds_differ", "fixed_seed_honored",
                   "replay_inputs_preserved", "unsupported_slot_refused", "attempt_id", "prompt_id",
                   "workflow_sha256", "submitted_graph_path", gens[0].entry_id, "director_signoff: false"):
        assert needle in text, needle


def test_a_failed_run_says_fail(tmp_path: Path, flux_template) -> None:
    text = render_record(verify(run_gate0(tmp_path, flux_template, good_specs()[:1]), flux_template))
    assert "FAIL" in text and "Gate 0 result: FAIL" in text


# ── the shipped fixture and docs ──────────────────────────────────────────────


def test_the_shipped_fixture_batch_is_two_random_and_one_fixed_seed_spec() -> None:
    batch, issues = read_batch_diagnosed(DOCS / "batch.md")
    assert issues == [] and len(batch.specs) == 3 and batch.project == "gate0"
    strategies = sorted(s.seed_strategy for s in batch.specs)
    assert strategies == ["fixed", "random", "random"]
    fixed = next(s for s in batch.specs if s.seed_strategy == "fixed")
    assert fixed.seed == FIXED
    assert all(s.lora_stack == [] and s.source is None for s in batch.specs)       # neutral: no identity, no source
    assert all("mug" in s.prompt for s in batch.specs)


def test_the_run_guide_and_record_template_exist_and_name_the_commands() -> None:
    run = (DOCS / "RUN.md").read_text()
    for needle in ("gate0 verify", "generate", "pod up", "pod down", "EXECUTION_TRUTH_VERIFIED_SINCE", "batch.md"):
        assert needle in run, needle
    assert "attempt_id" in (DOCS / "record-template.md").read_text()


def test_the_cli_command_is_registered() -> None:
    from click.testing import CliRunner

    from visual_generation.cli import cli

    out = CliRunner().invoke(cli, ["gate0", "verify", "--help"]).output
    for flag in ("--project", "--template", "--fixed-seed", "--out"):
        assert flag in out
