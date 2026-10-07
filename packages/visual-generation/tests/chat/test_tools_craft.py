from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import visual_generation.chat.tools.craft as craft_mod
from visual_generation.batch_file import read_batch
from visual_generation.chat.tools import tool_pack
from visual_generation.constants import IMG2IMG_TEMPLATE_NAME, INPAINT_TEMPLATE_NAME
from visual_generation.explain import ExplainResult
from visual_generation.models import DraftResult, VisualSource, VisualSpec

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


def tool(built: Built, name: str):  # type: ignore[no-untyped-def]
    return next(t for t in tool_pack(built.state) if t.name == name)


async def call(built: Built, name: str, **kw: Any):  # type: ignore[no-untyped-def]
    t = tool(built, name)
    return await t.handler(t.input_model(**kw))


def result(**kw: Any) -> DraftResult:
    spec = kw.pop("spec", None) or VisualSpec(prompt="a foggy street", heading="h")
    base: dict[str, Any] = dict(spec=spec, template_name="z-image-turbo", template_modality="text2img",
                                status="completed", cost_usd=0.04)
    base.update(kw)
    return DraftResult(**base)


@pytest.fixture
def fake_draft(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    spy = AsyncMock(return_value=result())
    monkeypatch.setattr(craft_mod, "_draft", spy)
    return spy


async def test_draft_maps_its_arguments_and_names_the_batch_file(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    b = build()
    r = await call(b, "draft", intent="fog", points=["wet cobbles"], scene="Opening", canon=["Celeste"])
    k = fake_draft.await_args.kwargs
    expected = b.projects_dir / "demo" / "visual-batch.md"
    assert fake_draft.await_args.args == ("fog",)
    assert k["batch_path"] == expected and k["project"] == "demo" and k["projects_dir"] == b.projects_dir
    assert (k["points"], k["scene"], k["force_canon"], k["source"], k["template_name"]) == (["wet cobbles"], "Opening", ["Celeste"], None, None)
    assert k["store"] is b.store and k["memory_store"] is b.memory          # one store per session
    assert k["budget"].max_cost_usd == 0.25                                  # per-call hard cap
    assert not r.is_error and r.artifacts == [str(expected)] and r.data["cost_usd"] == 0.04


async def test_draft_result_always_names_template_and_modality(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    r = await call(build(), "draft", intent="fog")
    assert "Template: z-image-turbo [text2img]" in r.text and r.data["modality"] == "text2img"


async def test_draft_resolves_a_label_to_the_full_id_and_defaults_the_img2img_template(
    build: Callable[..., Built], fake_draft: AsyncMock
) -> None:
    gens = make_gens(3)
    await call(build(gens=gens), "draft", intent="warmer", from_generation="attempt-02", denoise=0.55)
    k = fake_draft.await_args.kwargs
    assert isinstance(k["source"], VisualSource) and k["source"].from_generation == gens[1].entry_id
    assert k["template_name"] == IMG2IMG_TEMPLATE_NAME and k["denoise"] == 0.55


async def test_draft_with_a_mask_defaults_to_the_inpaint_template(
    build: Callable[..., Built], fake_draft: AsyncMock, tmp_path: Path
) -> None:
    img, mask = tmp_path / "a.png", tmp_path / "m.png"
    img.write_bytes(b"x")
    mask.write_bytes(b"x")
    await call(build(), "draft", intent="fix hand", image_path=str(img), mask=str(mask))
    k = fake_draft.await_args.kwargs
    assert k["source"].mask == str(mask) and k["template_name"] == INPAINT_TEMPLATE_NAME


async def test_unresolved_from_generation_asks_instead_of_guessing(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    r = await call(build(gens=make_gens(2)), "draft", intent="x", from_generation="attempt-09")
    assert r.is_error and r.data["open_questions"] and not fake_draft.await_count


@pytest.mark.parametrize("kw,needle", [
    (dict(), "intent, key points, or a scene"),
    (dict(intent="x", from_generation="attempt-01", image_path="/nope.png"), "only one of"),
    (dict(intent="x", mask="/m.png"), "requires a source"),
    (dict(intent="x", image_path="/definitely/not/here.png"), "No such file"),
])
async def test_draft_argument_errors_are_results_and_never_call_the_model(
    build: Callable[..., Built], fake_draft: AsyncMock, kw: dict[str, Any], needle: str
) -> None:
    r = await call(build(gens=make_gens(2)), "draft", **kw)
    assert r.is_error and needle in r.text and not fake_draft.await_count


async def test_draft_without_a_project_says_how_to_fix_it(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    r = await call(build(project=None), "draft", intent="x")
    assert r.is_error and "--project" in r.text and not fake_draft.await_count


async def test_ki8_denoise_without_a_source_is_flagged(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    r = await call(build(), "draft", intent="x", denoise=0.5)
    assert not r.is_error and any("no source image" in w for w in r.data["warnings"])
    assert "Warnings:" in r.text


async def test_ki8_img2img_template_with_no_source_is_flagged(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    fake_draft.return_value = result(template_name=IMG2IMG_TEMPLATE_NAME, template_modality="img2img")
    r = await call(build(), "draft", intent="plain prose")
    assert any("is img2img but this draft has no source" in w for w in r.data["warnings"])


async def test_draft_surfaces_the_librarys_own_warnings(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    fake_draft.return_value = result(revise_warnings=["parent was img2img"], missing_models=["ae.safetensors"],
                                     inert_inheritance=["seed has no slot"], canon_absent=["Celeste"])
    r = await call(build(), "draft", intent="x")
    text = r.text
    assert "parent was img2img" in text and "ae.safetensors" in text and "seed has no slot" in text and "Celeste" in text


async def test_failed_draft_is_an_error_result(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    fake_draft.return_value = result(status="failed", revise_warnings=["Nothing to draft"])
    r = await call(build(), "draft", intent="x")
    assert r.is_error and "Draft failed" in r.text and "Nothing to draft" in r.text


async def test_redraft_resolves_the_label_and_maps_arguments(build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch) -> None:
    spy = AsyncMock(return_value=result())
    monkeypatch.setattr(craft_mod, "_redraft", spy)
    gens = make_gens(4)
    b = build(gens=gens)
    r = await call(b, "redraft", generation="attempt-03", change="softer light", canon=["Celeste"])
    assert spy.await_args.args == (gens[2].entry_id, "softer light")
    k = spy.await_args.kwargs
    assert k["batch_path"] == b.projects_dir / "demo" / "visual-batch.md" and k["force_canon"] == ["Celeste"]
    assert k["store"] is b.store and not r.is_error
    bad = await call(b, "redraft", generation="attempt-40", change="x")
    assert bad.is_error and bad.data["open_questions"] and spy.await_count == 1


async def test_explain_maps_arguments_and_reports_cost(build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch) -> None:
    spy = AsyncMock(return_value=ExplainResult(concept="cfg", level="concise", gloss="guidance scale", own_lessons=["cfg 1 on turbo"], cost_usd=0.02))
    monkeypatch.setattr(craft_mod, "_explain", spy)
    b = build()
    r = await call(b, "explain", concept="cfg", level="full")
    k = spy.await_args.kwargs
    assert spy.await_args.args == ("cfg",) and k["level"] == "full" and k["budget"].max_cost_usd == 0.15
    assert k["store"] is b.store and k["memory_store"] is b.memory
    assert r.data["cost_usd"] == 0.02 and "cfg 1 on turbo" in r.text


def project_docs(b: Built, scenes: list[str]) -> Path:
    d = b.projects_dir / "demo"
    d.mkdir(parents=True)
    (d / "directed.md").write_text("\n\n".join(f"## {s}\nsomething happens" for s in scenes))
    return d


async def test_batch_build_drafts_each_scene_into_a_new_file(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    b = build()
    project_docs(b, ["Opening", "Chase", "Ending"])
    r = await call(b, "batch_build")
    assert fake_draft.await_count == 3
    scenes = [c.kwargs["scene"] for c in fake_draft.await_args_list]
    assert scenes == ["Opening", "Chase", "Ending"]
    assert all(c.kwargs["batch_path"] == b.projects_dir / "demo" / "visual-batch.md" for c in fake_draft.await_args_list)
    assert all(c.kwargs["budget"].max_cost_usd == 0.25 for c in fake_draft.await_args_list)
    assert r.data["built"] == 3 and r.data["cost_usd"] == pytest.approx(0.12)


async def test_batch_build_refuses_an_existing_batch_and_missing_scenes(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    b = build()
    r0 = await call(b, "batch_build")
    assert r0.is_error and "No scenes found" in r0.text
    d = project_docs(b, ["Opening"])
    (d / "visual-batch.md").write_text("existing")
    r1 = await call(b, "batch_build")
    assert r1.is_error and "already exists" in r1.text and not fake_draft.await_count
    assert (d / "visual-batch.md").read_text() == "existing"            # never overwritten


async def test_batch_build_stops_at_the_total_cap(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    fake_draft.return_value = result(cost_usd=0.9)
    b = build()
    project_docs(b, [f"Scene {i}" for i in range(6)])
    r = await call(b, "batch_build")
    assert fake_draft.await_count == 3 and "batch cap was reached" in r.text


async def test_batch_build_anchor_resolves_and_defaults_the_template(build: Callable[..., Built], fake_draft: AsyncMock) -> None:
    gens = make_gens(2)
    b = build(gens=gens)
    project_docs(b, ["Opening"])
    await call(b, "batch_build", from_generation="attempt-01", denoise=0.5)
    k = fake_draft.await_args.kwargs
    assert k["source"].from_generation == gens[0].entry_id and k["template_name"] == IMG2IMG_TEMPLATE_NAME


async def test_effects_and_estimates(build: Callable[..., Built]) -> None:
    from agent_shell.tools.registry import EffectClass

    b = build()
    project_docs(b, ["A", "B"])
    for name in ("draft", "redraft", "explain", "batch_build"):
        t = tool(b, name)
        assert t.effect is EffectClass.LLM_SPEND and t.estimate_cost and t.preview
    bt = tool(b, "batch_build")
    assert bt.estimate_cost(bt.input_model()) == pytest.approx(0.10)       # 2 scenes x $0.05


async def test_real_draft_through_the_tool_writes_no_memory_and_appends_the_batch_file(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch, flux_template: Any
) -> None:
    """The real library draft(), with retrieval and the LLM faked: no Qdrant data write, and the
    only side effect is the batch file."""
    from visual_generation.models import ModelAsset
    from visual_generation.retrieval import RetrievedContext

    draft_mod = importlib.import_module("visual_generation.draft")
    monkeypatch.setattr(draft_mod, "retrieve_context", AsyncMock(return_value=RetrievedContext()))
    monkeypatch.setattr(draft_mod, "craft_spec", AsyncMock(return_value=dict(
        prompt="a wolf in neon rain", negative_prompt=None, settings={"steps": 20}, model="flux1-dev.safetensors",
        seed_strategy="fixed", seed=42, width=1024, height=1024, lora_stack=[], rationale="r")))
    monkeypatch.setattr(craft_mod, "_draft", draft_mod.draft)
    b = build()
    models = [ModelAsset(name="flux1-dev.safetensors", kind="checkpoint")]
    b.store.get_template_by_name = AsyncMock(return_value=flux_template)
    b.store.list_models = MagicMock(return_value=models)
    b.store.get_model = lambda name: {m.name: m for m in models}.get(name)

    r = await call(b, "draft", intent="a wolf in neon rain", template="flux-txt2img")
    assert not r.is_error, r.text
    assert b.writes == []
    batch = read_batch(b.projects_dir / "demo" / "visual-batch.md")
    assert [s.prompt for s in batch.specs] == ["a wolf in neon rain"]
