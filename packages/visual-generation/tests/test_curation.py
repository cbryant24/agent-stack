from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation import curation as cur
from visual_generation.batch_file import write_batch
from visual_generation.canon import ProjectCanon
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    EvaluationEntry,
    GenerationBatch,
    LoraRef,
    ModelAsset,
    TechniqueLesson,
    VisualSpec,
)


def lesson_store(held_out: bool = False) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_lesson = AsyncMock()
    store.get_evaluation = AsyncMock(return_value=MagicMock(spec=EvaluationEntry) if held_out else None)
    return store


def add(store: MagicMock, **kw) -> TechniqueLesson:
    base = dict(statement="keep denoise near 0.5", scope="settings", valence="positive")
    base.update(kw)
    return asyncio.run(cur.add_lesson(base.pop("statement"), base.pop("scope"), base.pop("valence"),
                                      store=store, **base))


# ── lesson rules (code, not prompt) ───────────────────────────────────────────


def test_plain_lesson_is_stored_confirmed_with_default_new_fields() -> None:
    store = lesson_store()
    le = add(store)
    assert le.confirmed and le.claim_level == "tuned" and le.layer is None
    store.upsert_lesson.assert_awaited_once_with(le)


@pytest.mark.parametrize("topic,statement", [
    ("identity", "wording the face precisely helps"),
    ("staging", "describe the blocking in the prompt"),
    ("set", "name the bar landmarks"),
    (None, "this phrasing keeps the same character across shots"),      # caught by wording
    (None, "put the set geometry in the first sentence"),
])
def test_prompt_layer_lesson_about_conditioning_topics_needs_a_falsification_test(topic, statement) -> None:
    store = lesson_store()
    with pytest.raises(cur.LessonRuleError, match="falsification_test"):
        add(store, statement=statement, layer="prompt", topic=topic)
    store.upsert_lesson.assert_not_awaited()
    ok = add(store, statement=statement, layer="prompt", topic=topic,
             falsification_test="same seed, prompt-only change flips the face: disproves it")
    assert ok.falsification_test and store.upsert_lesson.await_count == 1


def test_prompt_rule_only_bites_the_prompt_layer_and_conditioning_topics() -> None:
    store = lesson_store()
    add(store, statement="cfg 1 on turbo", layer="prompt", topic="other")            # not about conditioning
    add(store, statement="the face needs references", layer="conditioning_asset", topic="identity")
    add(store, statement="the face needs references", layer=None, topic="identity")  # no layer given
    assert store.upsert_lesson.await_count == 3


@pytest.mark.parametrize("kw,needle", [
    (dict(evidence_n=4, held_out_eval_id="e"), "evidence_n >= 5"),
    (dict(evidence_n=9), "held-out evaluation id"),
    (dict(evidence_n=9, held_out_eval_id="missing"), "held-out evaluation id"),
    (dict(), "evidence_n >= 5"),
])
def test_validated_needs_five_results_and_an_existing_held_out_evaluation(kw, needle) -> None:
    store = lesson_store(held_out=False)
    with pytest.raises(cur.LessonRuleError, match=needle):
        add(store, claim_level="validated", **kw)
    store.upsert_lesson.assert_not_awaited()


def test_validated_passes_with_n_and_a_real_held_out_evaluation() -> None:
    store = lesson_store(held_out=True)
    le = add(store, claim_level="validated", evidence_n=5, held_out_eval_id="e1", derived_from=["e0"])
    assert le.claim_level == "validated" and le.derived_from == ["e0"]
    store.get_evaluation.assert_awaited_once_with("e1")


def test_both_rules_can_fail_together_and_are_all_reported() -> None:
    with pytest.raises(cur.LessonRuleError) as e:
        add(lesson_store(), statement="identity wording", layer="prompt", topic="identity",
            claim_level="validated", evidence_n=1)
    msg = str(e.value)
    assert "falsification_test" in msg and "evidence_n >= 5" in msg and "held-out" in msg


# ── lesson lookup / removal ───────────────────────────────────────────────────


def test_lookup_and_remove_lesson() -> None:
    le = TechniqueLesson(statement="s", valence="negative", scope="model", confirmed=True)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_lesson = AsyncMock(return_value=le)
    store.delete_lesson = AsyncMock()
    assert asyncio.run(cur.lookup_lesson(le.entry_id, store)) is le
    assert asyncio.run(cur.remove_lesson(le.entry_id, store, lesson=le)) is le
    store.delete_lesson.assert_awaited_once_with(le.entry_id)
    store.get_lesson = AsyncMock(return_value=None)
    with pytest.raises(LookupError, match="No technique lesson"):
        asyncio.run(cur.lookup_lesson("nope", store))
    store.get_lesson = AsyncMock(side_effect=ValueError("generation"))
    with pytest.raises(ValueError, match="generation"):                     # never deletes other kinds
        asyncio.run(cur.lookup_lesson("gen-id", store))


def test_resolve_lesson_id_accepts_a_unique_prefix_only() -> None:
    a = TechniqueLesson(statement="a", valence="positive", entry_id="6f5638ea-0000-0000-0000-000000000001")
    b = TechniqueLesson(statement="b", valence="positive", entry_id="6f5638eb-0000-0000-0000-000000000002")
    store = MagicMock()
    store.list_lessons = AsyncMock(return_value=[a, b])
    assert asyncio.run(cur.resolve_lesson_id("6f5638ea", store)) == a.entry_id
    assert asyncio.run(cur.resolve_lesson_id(b.entry_id, store)) == b.entry_id
    for bad, needle in (("6f5638", "no lesson matches"), ("6f5638e", "no lesson matches"), ("zzzzzzzz", "no lesson matches")):
        with pytest.raises(LookupError, match=needle):
            asyncio.run(cur.resolve_lesson_id(bad, store))
    store.list_lessons = AsyncMock(return_value=[
        TechniqueLesson(statement="a", valence="positive", entry_id="abcdef01-1"),
        TechniqueLesson(statement="b", valence="positive", entry_id="abcdef01-2")])
    with pytest.raises(LookupError, match="matches 2"):
        asyncio.run(cur.resolve_lesson_id("abcdef01", store))


# ── facts: the propose-then-confirm path stores what the CLI used to ──────────


def _uks(captured: list):
    from agent_runtime import UserKnowledgeStore

    mem = MagicMock()
    mem.ensure_collection = AsyncMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mem.upsert_raw_points = AsyncMock(side_effect=lambda c, pts: captured.extend(p.payload for p in pts))
    return UserKnowledgeStore(mem)


def test_add_fact_stores_the_same_payload_as_bulk_load_verified() -> None:
    bulk: list = []
    asyncio.run(_uks(bulk).bulk_load_verified(
        [{"statement": "ComfyUI needs --listen", "domain": "comfyui_mechanics",
          "source_type": "user_verified", "confidence": "medium"}], source_ref="manual:cli"))
    new: list = []
    entry_id = asyncio.run(cur.add_fact("ComfyUI needs --listen", "comfyui_mechanics",
                                        uks=_uks(new), confidence="medium"))
    volatile = {"entry_id", "created_at", "updated_at"}
    strip = lambda p: {k: v for k, v in p.items() if k not in volatile}  # noqa: E731
    assert strip(new[0]) == strip(bulk[0])
    assert new[0]["entry_id"] == entry_id and new[0]["source_ref"] == "manual:cli"


def test_add_fact_leaves_no_draft_behind(tmp_path: Path) -> None:
    from agent_runtime.config import get_config

    asyncio.run(cur.add_fact("fact", "runpod_mechanics", uks=_uks([]), source_ref="manual:chat"))
    assert list((get_config().agent_data_dir / "drafts" / "user_knowledge").glob("*.json")) == []


# ── batch, model ──────────────────────────────────────────────────────────────


def test_remove_batch_spec(tmp_path: Path) -> None:
    path = tmp_path / "b.md"
    a, b = VisualSpec(heading="A", prompt="a"), VisualSpec(heading="B", prompt="b")
    write_batch(GenerationBatch(project="p", specs=[a, b]), path)
    _, target = cur.find_batch_spec(path, b.spec_id)
    assert target.heading == "B"
    removed, remaining = cur.remove_batch_spec(path, b.spec_id)
    assert removed.spec_id == b.spec_id and remaining == 1
    with pytest.raises(LookupError, match="Known: " + a.spec_id):
        cur.find_batch_spec(path, "nope")


def test_remove_model(tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path / "m.json")
    reg.add(ModelAsset(name="x.safetensors", kind="lora", identity_bearing=True))
    assert cur.lookup_model("x.safetensors", reg).identity_bearing
    assert cur.remove_model("x.safetensors", reg).name == "x.safetensors"
    assert reg.list_models() == []
    with pytest.raises(LookupError, match="No registered asset"):
        cur.remove_model("x.safetensors", reg)


# ── canon: plan (no write) matches apply ──────────────────────────────────────


def test_canon_plan_writes_nothing_and_set_matches_the_plan(tmp_path: Path) -> None:
    canon = ProjectCanon("proj", base_dir=tmp_path)
    plan = cur.plan_canon_set("proj", ["Celeste", "the girl"], wardrobe="coat-v2", canon=canon)
    assert plan.before is None and not plan.existed and not canon.path.exists()
    done = cur.set_canon_subject("proj", ["Celeste", "the girl"], wardrobe="coat-v2", canon=canon)
    assert done.after == plan.after and canon.load() == [plan.after]
    replace = cur.plan_canon_set("proj", ["Celeste"], hair="auburn", canon=canon)
    assert replace.existed and replace.before.wardrobe == "coat-v2" and replace.after.wardrobe is None


def test_canon_edit_plan_shows_before_after_without_writing(tmp_path: Path) -> None:
    canon = ProjectCanon("proj", base_dir=tmp_path)
    canon.set_subject(["Celeste"], hair="bun")
    before_file = canon.path.read_text()
    plan = cur.plan_canon_edit("proj", "celeste", cur.CanonEdit(hair="braid", add_aliases=["the girl"]), canon=canon)
    assert plan.before.hair == "bun" and plan.after.hair == "braid" and plan.after.aliases == ["Celeste", "the girl"]
    assert canon.path.read_text() == before_file
    text = cur.render_canon_change(plan)
    assert "Before:" in text and "After:" in text and "braid" in text and "bun" in text
    done = cur.edit_canon_subject("proj", "celeste", cur.CanonEdit(hair="braid", add_aliases=["the girl"]), canon=canon)
    assert done.after == plan.after and canon.load()[0].hair == "braid"
    with pytest.raises(ValueError, match="No canon subject matches"):
        cur.plan_canon_edit("proj", "ghost", cur.CanonEdit(hair="x"), canon=canon)


def test_canon_edit_is_empty_and_remove(tmp_path: Path) -> None:
    assert cur.CanonEdit().is_empty() and not cur.CanonEdit(clear_lora=True).is_empty()
    canon = ProjectCanon("proj", base_dir=tmp_path)
    canon.set_subject(["Celeste", "the girl"])
    assert cur.find_canon_subject("proj", "THE GIRL", canon).aliases[0] == "Celeste"
    assert cur.remove_canon_subject("proj", "ghost", canon) is None
    assert cur.remove_canon_subject("proj", "the girl", canon).aliases[0] == "Celeste"
    assert canon.load() == []


def test_parse_lora() -> None:
    assert cur.parse_lora("n:0.8") == LoraRef(name="n", strength=0.8) and cur.parse_lora("n").strength == 1.0
    for bad in ("", ":1", "n:x"):
        with pytest.raises(ValueError):
            cur.parse_lora(bad)


# ── workflow: propose, then confirm ───────────────────────────────────────────


def test_workflow_plan_then_commit(flux_graph, tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path / "m.json")
    plan = cur.plan_workflow(flux_graph, "flux-test", reg)
    assert plan.slot_map and plan.missing_models == plan.required_models      # empty registry
    text = cur.render_workflow_plan(plan)
    assert "Inferred slots for 'flux-test'" in text and "→ node" in text
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_template = AsyncMock()
    tmpl = asyncio.run(cur.commit_workflow(plan, "basic stills", store))
    assert tmpl.name == "flux-test" and tmpl.descriptor == "basic stills" and tmpl.slot_map == plan.slot_map
    store.upsert_template.assert_awaited_once_with(tmpl)


def test_load_graph_file_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(ValueError, match="Not valid JSON"):
        cur.load_graph_file(bad)
    bad.write_text(json.dumps([]))
    with pytest.raises(ValueError, match="API-format graph"):
        cur.load_graph_file(bad)
