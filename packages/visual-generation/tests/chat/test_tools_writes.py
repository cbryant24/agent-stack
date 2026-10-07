from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_shell.tools.registry import EffectClass

import visual_generation.chat.tools.craft as craft_mod
import visual_generation.chat.tools.writes as writes_mod
from visual_generation.chat.config import build_chat_config
from visual_generation.chat.tools import tool_pack
from visual_generation.evaluation import EXECUTION_TRUTH_ENV
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    DraftResult,
    EvaluationEntry,
    ModelAsset,
    TechniqueLesson,
    VisualSpec,
)

from .conftest import Built, make_gens  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

EV = dict(generation="attempt-03", raw_feedback="the face reads plastic", reaction="disliked", rating=2,
          change=["softer light"], strike_class="plastic-face",
          findings=[dict(layer="conditioning_asset", evidence="observed", statement="button eyes read as paint",
                         basis="attempt-03 asset")])
LESSON = dict(statement="a masked eye inpaint fixes button eyes", scope="workflow", valence="positive",
              layer="conditioning_asset", topic="identity", evidence_n=2)


@pytest.fixture(autouse=True)
def _unset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EXECUTION_TRUTH_ENV, raising=False)


def tool(b: Built, tool_name: str, /) -> Any:
    return next(t for t in tool_pack(b.state) if t.name == tool_name)


async def run(b: Built, tool_name: str, /, **kw: Any) -> Any:
    t = tool(b, tool_name)
    return await t.handler(t.input_model(**kw))


async def preview(b: Built, tool_name: str, /, **kw: Any) -> str:
    t = tool(b, tool_name)
    out = t.preview(t.input_model(**kw))
    return await out if hasattr(out, "__await__") else out


async def precheck(b: Built, tool_name: str, /, **kw: Any) -> str | None:
    t = tool(b, tool_name)
    return await t.precheck(t.input_model(**kw)) if t.precheck else None


def gens8(b_kw: dict[str, Any] | None = None) -> list[Any]:
    return make_gens(8)


# ── the set of write tools and their effects ──────────────────────────────────


async def test_write_tools_have_the_documented_effects(build: Callable[..., Built]) -> None:
    t = {s.name: s for s in tool_pack(build().state)}
    M, D = EffectClass.MEMORY_WRITE, EffectClass.DESTRUCTIVE_LOCAL
    expected = {"report": M, "record_evaluation": M, "add_lesson": M, "add_fact": M, "canon_set": M,
                "canon_edit": M, "workflow_register": M, "lesson_rm": D, "batch_rm": D, "model_rm": D,
                "canon_rm": D, "list_evaluations": EffectClass.READ}
    assert {n: t[n].effect for n in expected} == expected
    gated = [s for s in t.values() if s.effect in (M, D)]
    assert all(s.preview is not None for s in gated)               # every write shows what it will do


# ── report ────────────────────────────────────────────────────────────────────


async def test_report_preview_precheck_and_write(build: Callable[..., Built]) -> None:
    gens = make_gens(3)
    b = build(gens=gens, allow_writes=True)
    p = await preview(b, "report", generation="attempt-02", reaction="disliked", rating=3, notes="warmer")
    assert "attempt-02" in p and "disliked ★3" in p and "notes: warmer" in p and "ratings are meaningful" in p
    assert "could not" in (await precheck(b, "report", generation="attempt-09", reaction="loved")).lower()
    r = await run(b, "report", generation="attempt-02", reaction="loved", rating=5)
    assert not r.is_error and gens[1].reaction == "loved" and "update_generation_reaction" in b.writes


# ── record_evaluation ─────────────────────────────────────────────────────────


async def test_record_evaluation_writes_the_record_and_sets_the_reaction(build: Callable[..., Built]) -> None:
    gens = make_gens(8)
    b = build(gens=gens, allow_writes=True)
    r = await run(b, "record_evaluation", **EV)
    assert not r.is_error, r.text
    assert b.writes == ["upsert_evaluation", "update_generation_reaction"]          # record first, then the reaction
    (e,) = b.evals
    assert e.entry_id == r.data["evaluation_id"] and e.gen_id == gens[2].entry_id and e.raw_feedback == EV["raw_feedback"]
    assert gens[2].reaction == "disliked" and gens[2].rating == 2 and gens[2].notes == "softer light"
    assert e.agent_status == "unresolved" == r.data["agent_status"]                  # flag unset: pre-fix
    assert any("seed may not match" in f.statement for f in e.findings)


async def test_record_evaluation_preview_shows_the_full_record_and_the_automatic_status(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8))
    text = await preview(b, "record_evaluation", **EV)
    for needle in ("attempt-03", "DISLIKED ★2", "the face reads plastic", "Change: softer light", "button eyes read as paint",
                   "agent_status set to unresolved automatically", "Also sets the generation's reaction"):
        assert needle in text
    assert b.writes == []                                                           # a preview writes nothing


async def test_record_evaluation_precheck_refuses_a_broken_record_before_any_prompt(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8))
    assert "open_parameter" in await precheck(b, "record_evaluation", **{**EV, "change": ["set denoise to 0.35"]})
    assert "Could not resolve" in await precheck(b, "record_evaluation", **{**EV, "generation": "attempt-77"})
    assert await precheck(b, "record_evaluation", **EV) is None


async def test_record_evaluation_is_idempotent_and_retrievable_three_ways(build: Callable[..., Built]) -> None:
    gens = make_gens(8)
    gens[4].parent_id, gens[4].chain_root_id = gens[2].entry_id, gens[2].entry_id
    b = build(gens=gens, allow_writes=True)
    await run(b, "record_evaluation", **EV)
    await run(b, "record_evaluation", **EV)                                          # a retry / re-confirm
    assert len(b.evals) == 1
    by_gen = await run(b, "list_evaluations", generation="attempt-03")
    by_chain = await run(b, "list_evaluations", chain_of="attempt-05")               # a child of attempt-03's chain
    by_project = await run(b, "list_evaluations")
    assert by_gen.data["evaluation_ids"] == by_chain.data["evaluation_ids"] == by_project.data["evaluation_ids"] == [b.evals[0].entry_id]
    assert "the face reads plastic" in by_gen.text
    assert (await run(b, "list_evaluations", generation="attempt-77")).is_error


async def test_a_failed_reaction_update_is_a_partial_write_result_and_the_proposal_is_not_offered_again(
    build: Callable[..., Built],
) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    b.store.update_generation_reaction = AsyncMock(side_effect=RuntimeError("qdrant down"))
    r = await run(b, "record_evaluation", **EV)
    assert r.is_error and r.data["partial"] and "was written" in r.text and len(b.evals) == 1


async def test_recall_returns_evaluations_as_a_fourth_kind(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(3), allow_writes=True)
    await run(b, "record_evaluation", **EV)
    r = await run(b, "recall", query="plastic face")
    assert "── Evaluations (1)" in r.text and r.data["evaluation_ids"] == [b.evals[0].entry_id]


# ── lessons and facts ─────────────────────────────────────────────────────────


async def test_add_lesson_enforces_the_rules_before_asking_and_when_writing(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(2), allow_writes=True)
    bad = {**LESSON, "layer": "prompt", "statement": "phrase the face precisely to keep identity"}
    assert "falsification_test" in await precheck(b, "add_lesson", **bad)
    r = await run(b, "add_lesson", **bad)
    assert r.is_error and b.lessons == []
    ok = await run(b, "add_lesson", **{**bad, "falsification_test": "a prompt-only change flips the face at fixed seed"})
    assert not ok.is_error and b.lessons[0].falsification_test and b.lessons[0].confirmed
    assert "layer=prompt" in await preview(b, "add_lesson", **bad)


async def test_validated_lesson_needs_an_existing_held_out_evaluation(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    await run(b, "record_evaluation", **EV)
    held = b.evals[0].entry_id
    v = {**LESSON, "claim_level": "validated", "evidence_n": 6}
    assert "held-out" in await precheck(b, "add_lesson", **v, held_out_eval_id="ghost")
    assert await precheck(b, "add_lesson", **v, held_out_eval_id=held) is None
    r = await run(b, "add_lesson", **v, held_out_eval_id=held, source_eval_ids=[held])
    assert b.lessons[0].claim_level == "validated" and b.lessons[0].derived_from == [held] and not r.is_error


async def test_add_fact_goes_through_propose_then_confirm(build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch) -> None:
    uks = MagicMock()
    uks.ensure_collection = AsyncMock()
    uks.propose_entry = AsyncMock(return_value=MagicMock(draft_id="d1"))
    uks.confirm_entry = AsyncMock(return_value="fact-1")
    monkeypatch.setattr(writes_mod, "UserKnowledgeStore", lambda ms: uks)
    b = build()
    r = await run(b, "add_fact", statement="Pods bill per second", domain="runpod_mechanics")
    assert r.data["entry_id"] == "fact-1"
    assert uks.propose_entry.await_args.args == ("Pods bill per second", "runpod_mechanics", "user_verified")
    assert uks.propose_entry.await_args.kwargs["source_ref"] == "manual:chat"
    uks.confirm_entry.assert_awaited_once_with("d1")
    assert "runpod_mechanics" in await preview(b, "add_fact", statement="s", domain="runpod_mechanics")


# ── destructive tools show the exact item first ──────────────────────────────


async def test_lesson_rm_by_prefix_shows_the_item_and_deletes_it(build: Callable[..., Built]) -> None:
    a = TechniqueLesson(statement="two LoRAs at 1.0 isolate identities", valence="positive", scope="model",
                        confirmed=True, entry_id="6f5638ea-0000-0000-0000-000000000001")
    other = TechniqueLesson(statement="keep cfg 1.0", valence="positive", scope="settings", confirmed=True)
    b = build(lessons=[a, other], allow_writes=True)
    p = await preview(b, "lesson_rm", lesson="6f5638ea")
    assert "two LoRAs at 1.0 isolate identities" in p and a.entry_id in p
    assert await precheck(b, "lesson_rm", lesson="6f5638ea") is None
    assert "no lesson matches" in await precheck(b, "lesson_rm", lesson="deadbeef")
    r = await run(b, "lesson_rm", lesson="6f5638ea")
    assert not r.is_error and [le.statement for le in b.lessons] == ["keep cfg 1.0"]


async def test_batch_rm(build: Callable[..., Built]) -> None:
    from visual_generation.batch_file import read_batch, write_batch
    from visual_generation.models import GenerationBatch

    b = build()
    keep, drop = VisualSpec(heading="Keep", prompt="k"), VisualSpec(heading="Drop", prompt="a foggy street")
    path = b.state.batch_path()
    write_batch(GenerationBatch(project="demo", specs=[keep, drop]), path)
    assert "Drop" in await preview(b, "batch_rm", spec_id=drop.spec_id) and "a foggy street" in await preview(b, "batch_rm", spec_id=drop.spec_id)
    assert "No spec with id" in await precheck(b, "batch_rm", spec_id="nope")
    r = await run(b, "batch_rm", spec_id=drop.spec_id)
    assert r.data["remaining"] == 1 and [s.heading for s in read_batch(path).specs] == ["Keep"]


async def test_model_rm(build: Callable[..., Built]) -> None:
    b = build()
    ModelRegistry().add(ModelAsset(name="scratch.safetensors", kind="lora", identity_bearing=True))
    p = await preview(b, "model_rm", name="scratch.safetensors")
    assert "[lora] scratch.safetensors" in p and "identity-bearing" in p and "pod file is untouched" in p
    assert "No registered asset" in await precheck(b, "model_rm", name="ghost")
    assert not (await run(b, "model_rm", name="scratch.safetensors")).is_error
    assert ModelRegistry().list_models() == []


async def test_canon_set_edit_rm_show_the_diff_and_change_the_file(build: Callable[..., Built]) -> None:
    from visual_generation.canon import ProjectCanon

    b = build()
    s = await preview(b, "canon_set", aliases=["Celeste", "the girl"], wardrobe="coat-v2")
    assert "Before: (no such subject)" in s and "wardrobe: coat-v2" in s
    assert not ProjectCanon("demo").path.exists()                                  # preview wrote nothing
    assert not (await run(b, "canon_set", aliases=["Celeste", "the girl"], wardrobe="coat-v2")).is_error
    assert "REPLACES" in await preview(b, "canon_set", aliases=["Celeste"], hair="auburn")

    e = await preview(b, "canon_edit", subject="celeste", hair="braid")
    assert "Before:" in e and "braid" in e and ProjectCanon("demo").load()[0].hair is None
    assert "No canon subject matches" in await precheck(b, "canon_edit", subject="ghost", hair="x")
    assert "Nothing to edit" in await precheck(b, "canon_edit", subject="celeste")
    await run(b, "canon_edit", subject="celeste", hair="braid")
    assert ProjectCanon("demo").load()[0].hair == "braid"

    assert "Celeste" in await preview(b, "canon_rm", alias="the girl")
    assert "No canon subject" in await precheck(b, "canon_rm", alias="ghost")
    await run(b, "canon_rm", alias="the girl")
    assert ProjectCanon("demo").load() == []
    assert "no project" in await precheck(build(project=None), "canon_rm", alias="x")


async def test_workflow_register_proposes_the_slot_map_then_stores(build: Callable[..., Built], flux_graph_file: Path) -> None:
    b = build(allow_writes=True)
    p = await preview(b, "workflow_register", graph_path=str(flux_graph_file), name="flux-test", descriptor="basic stills")
    assert "Inferred slots for 'flux-test'" in p and "Descriptor: basic stills" in p
    assert "No such file" in await precheck(b, "workflow_register", graph_path="/nope.json")
    r = await run(b, "workflow_register", graph_path=str(flux_graph_file), name="flux-test", descriptor="basic stills")
    assert not r.is_error and [t.name for t in b.templates] == ["flux-test"] and b.templates[0].descriptor == "basic stills"


# ── proposals: what is unwritten at /exit ────────────────────────────────────


async def test_propose_registers_proposals_and_writes_clear_them(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8), allow_writes=True)
    args = {**EV, "lessons": [{**LESSON, "layer": "conditioning_asset"}]}
    r = await run(b, "propose_interpretation", **args)
    assert not r.is_error and "Proposal only" in r.text and r.data["strike"]["count"] == 1
    pending = b.state.unwritten_proposals()
    assert {p.kind for p in pending} == {"evaluation", "lesson"} and {p.tool for p in pending} == {"record_evaluation", "add_lesson"}
    assert b.writes == []                                                              # proposing stores nothing
    ev_prop = next(p for p in pending if p.kind == "evaluation")
    assert ev_prop.payload["raw_feedback"] == EV["raw_feedback"] and "revised_spec" not in ev_prop.payload

    await run(b, "record_evaluation", **ev_prop.payload)
    assert [p.kind for p in b.state.unwritten_proposals()] == ["lesson"]
    await run(b, "add_lesson", **next(p for p in pending if p.kind == "lesson").payload)
    assert b.state.unwritten_proposals() == []
    cfg = build_chat_config(b.state)
    assert cfg.on_session_end is not None and cfg.on_session_end([]) == []


async def test_a_rejected_proposal_is_offered_again_at_exit(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8))
    await run(b, "propose_interpretation", **EV)
    cfg = build_chat_config(b.state)
    assert cfg.on_session_end is not None
    left = cfg.on_session_end([])
    assert len(left) == 1 and left[0].tool == "record_evaluation"


async def test_propose_returns_rule_violations_as_error_results_and_registers_nothing(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(8))
    r = await run(b, "propose_interpretation", **{**EV, "change": ["use cfg 7.5"]})
    assert r.is_error and "open_parameter" in r.text and b.state.unwritten_proposals() == []
    unknown = await run(b, "propose_interpretation", **{**EV, "generation": "attempt-99"})
    assert unknown.is_error and unknown.data["open_questions"]


# ── three strikes also guard the redraft tool ────────────────────────────────


async def test_redraft_is_refused_after_three_same_class_failures_until_a_question_is_recorded(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch
) -> None:
    gens = make_gens(4)
    spy = AsyncMock(return_value=DraftResult(spec=VisualSpec(prompt="p", heading="h"), template_name="t",
                                             template_modality="text2img", status="completed"))
    monkeypatch.setattr(craft_mod, "_redraft", spy)
    b = build(gens=gens, allow_writes=True)
    for i, fb in enumerate(("one", "two", "three")):
        await run(b, "record_evaluation", **{**EV, "raw_feedback": fb, "change": [], "rating": None,
                                              "generation": f"attempt-0{i + 1}"})
    # evaluations are on different generations; put them in one chain
    for g in gens:
        g.chain_root_id = gens[0].entry_id
    for e in b.evals:
        e.chain_root_id = gens[0].entry_id
    blocked = await run(b, "redraft", generation="attempt-04", change="calmer wording")
    assert blocked.is_error and "architecture question" in blocked.text and spy.await_count == 0
    assert blocked.data["strike"]["blocked"] is True

    q = {"layer_blamed": "prompt", "alternative_layer": "conditioning_asset", "question": "is it a routing gap?"}
    await run(b, "record_evaluation", **{**EV, "raw_feedback": "four", "change": [], "rating": None,
                                          "generation": "attempt-04", "architecture_question": q})
    for e in b.evals:
        e.chain_root_id = gens[0].entry_id
    ok = await run(b, "redraft", generation="attempt-04", change="calmer wording")
    assert not ok.is_error and spy.await_count == 1


async def test_record_evaluation_args_survive_a_json_round_trip_for_deferral() -> None:
    from visual_generation.chat.schemas import EvaluationInput

    again = EvaluationInput(**json.loads(EvaluationInput(**EV).model_dump_json()))
    assert again.raw_feedback == EV["raw_feedback"] and again.findings[0].layer.value == "conditioning_asset"
    assert isinstance(EvaluationEntry.model_fields["gen_id"].annotation, type)
