from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation import evaluation as ev
from visual_generation.models import (
    ArchitectureQuestion,
    EvaluationEntry,
    Evidence,
    Finding,
    Layer,
    TechniqueLesson,
    VisualGeneration,
)
from visual_generation.store import VisualGenerationStore


def entry(gen: VisualGeneration | None = None, **kw) -> EvaluationEntry:
    base = dict(gen_id="g1", chain_root_id="root", project="p", reaction="disliked",
                raw_feedback="face reads plastic", created_at="2026-10-01T00:00:01+00:00")
    if gen is not None:
        base.update(gen_id=gen.entry_id, chain_root_id=gen.chain_root_id, project=gen.project)
    base.update(kw)
    return EvaluationEntry(**base)


# ── model ─────────────────────────────────────────────────────────────────────


def test_evaluation_payload_round_trips_and_uses_the_store_conventions() -> None:
    e = entry(findings=[Finding(layer=Layer.CONDITIONING_ASSET, evidence=Evidence.OBSERVED, statement="eyes")],
              architecture_question=ArchitectureQuestion(
                  layer_blamed=Layer.PROMPT, alternative_layer=Layer.CONDITIONING_ASSET, question="why?"))
    p = e.to_payload()
    assert p["memory_type"] == "evaluation" and p["entry_id"] == e.entry_id        # not `kind` / `eval_id`
    assert p["findings"][0]["layer"] == "conditioning_asset"                        # JSON-safe enums
    assert EvaluationEntry.from_payload(p) == e


def test_unknown_payload_keys_are_ignored_and_old_lessons_load_unchanged() -> None:
    assert EvaluationEntry.from_payload({**entry().to_payload(), "future_field": 1}).gen_id == "g1"
    old = {"memory_type": "technique_lesson", "entry_id": "x", "statement": "s", "valence": "positive",
           "scope": "settings", "confirmed": True, "derived_from": [], "created_at": "2026-01-01"}
    le = TechniqueLesson.from_payload(old)
    assert (le.layer, le.evidence_n, le.falsification_test, le.claim_level) == (None, None, None, "tuned")


def test_architecture_question_must_name_a_different_layer() -> None:
    with pytest.raises(ValueError, match="different"):
        ArchitectureQuestion(layer_blamed=Layer.PROMPT, alternative_layer=Layer.PROMPT, question="q")


def test_rating_range_and_embed_text() -> None:
    with pytest.raises(ValueError):
        entry(rating=9)
    e = entry(findings=[Finding(layer=Layer.OUTCOME, evidence=Evidence.INFERRED, statement="too dark")])
    assert e.embed_text == "face reads plastic\ntoo dark"


# ── ids ───────────────────────────────────────────────────────────────────────


def test_evaluation_id_is_stable_for_retries_and_distinct_otherwise() -> None:
    a = ev.evaluation_id("g", "disliked", "text")
    assert a == ev.evaluation_id("g", "disliked", "text")
    assert a != ev.evaluation_id("g", "liked", "text") != ev.evaluation_id("h", "liked", "text")


# ── trusted-execution marking ───────────────────────────────────────────────


def test_unset_flag_marks_every_generation_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ev.EXECUTION_TRUTH_ENV, raising=False)
    gen = VisualGeneration(caption="c", seed=7)
    out = ev.apply_execution_truth(entry(gen), gen)
    assert out.agent_status == "unresolved"
    f = out.findings[-1]
    assert f.layer is Layer.AGENT_CORRECTNESS and f.evidence is Evidence.UNRESOLVED
    assert "seed may not match the submitted graph" in f.statement


def test_flag_date_splits_old_from_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ev.EXECUTION_TRUTH_ENV, "2026-10-04")
    old = VisualGeneration(caption="c", created_at="2026-10-03T23:59:00+00:00")
    new = VisualGeneration(caption="c", created_at="2026-10-04T00:00:01+00:00")
    assert ev.apply_execution_truth(entry(old), old).agent_status == "unresolved"
    assert ev.apply_execution_truth(entry(new, agent_status="agent-pass"), new).agent_status == "agent-pass"


def test_marking_is_idempotent_and_keeps_existing_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ev.EXECUTION_TRUTH_ENV, raising=False)
    gen = VisualGeneration(caption="c")
    mine = Finding(layer=Layer.OUTCOME, evidence=Evidence.OBSERVED, statement="mine")
    once = ev.apply_execution_truth(entry(gen, findings=[mine]), gen)
    twice = ev.apply_execution_truth(once, gen)
    assert len(once.findings) == 2 == len(twice.findings) and once.findings[0] == mine


def test_a_bad_flag_value_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ev.EXECUTION_TRUTH_ENV, "soon")
    with pytest.raises(ValueError, match="ISO date"):
        ev.execution_truth_verified_since()


# ── strikes ───────────────────────────────────────────────────────────────────


def ev_at(n: int, reaction: str = "disliked", cls: str | None = "bleed", **kw) -> EvaluationEntry:
    return entry(reaction=reaction, strike_class=cls, created_at=f"2026-10-01T00:00:{n:02d}+00:00",
                 raw_feedback=f"f{n}", **kw)


def test_three_negative_same_class_evaluations_block() -> None:
    assert not ev.strike_status([ev_at(1), ev_at(2)]).blocked
    s = ev.strike_status([ev_at(1), ev_at(2), ev_at(3)])
    assert s.blocked and s.count == 3 and s.strike_class == "bleed"


def test_render_failed_counts_and_a_positive_reaction_resets() -> None:
    assert ev.strike_status([ev_at(1), ev_at(2, "render_failed"), ev_at(3)]).count == 3
    assert ev.strike_status([ev_at(1), ev_at(2), ev_at(3, "liked_with_changes")]).count == 0
    assert ev.strike_status([ev_at(1), ev_at(2, "loved"), ev_at(3)]).count == 1


def test_other_classes_are_ignored_and_none_means_no_status() -> None:
    mixed = [ev_at(1), ev_at(2, cls="seed"), ev_at(3), ev_at(4, cls=None), ev_at(5)]
    assert ev.strike_status(mixed, "bleed").count == 3
    assert ev.strike_status([ev_at(1, cls=None)]) == ev.StrikeStatus()


def test_a_recorded_architecture_question_resets_the_count() -> None:
    q = ArchitectureQuestion(layer_blamed=Layer.PROMPT, alternative_layer=Layer.CONDITIONING_ASSET, question="q")
    s = ev.strike_status([ev_at(1), ev_at(2), ev_at(3), ev_at(4, architecture_question=q)])
    assert s.count == 0 and not s.blocked
    again = ev.strike_status([ev_at(1), ev_at(2), ev_at(3), ev_at(4, architecture_question=q), ev_at(5), ev_at(6), ev_at(7)])
    assert again.blocked and again.count == 3


def test_status_defaults_to_the_latest_class_regardless_of_input_order() -> None:
    assert ev.strike_status([ev_at(3), ev_at(1), ev_at(2)]).blocked


# ── numbers ───────────────────────────────────────────────────────────────────


def test_numbers_must_come_from_the_director_or_the_recipe() -> None:
    allowed = "make it softer, denoise 0.5 was fine. recipe: seed 4471 steps 8"
    assert ev.ungrounded_numbers(["keep denoise 0.5", "seed 4471"], allowed) == []
    assert ev.ungrounded_numbers(["lower denoise to 0.35", "use steps 12"], allowed) == ["0.35", "12"]


def test_attempt_labels_are_not_numeric_values() -> None:
    assert ev.ungrounded_numbers(["keep the jaw from attempt-07 and #12"], "fix it") == []
    assert ev.ungrounded_numbers(["words only"], "") == []


# ── record_evaluation ─────────────────────────────────────────────────────────


def fake_store(gen: VisualGeneration | None) -> tuple[VisualGenerationStore, MagicMock, list[str]]:
    calls: list[str] = []
    mem = MagicMock()
    mem.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    mem.ensure_collection = AsyncMock()
    mem.upsert_raw_points = AsyncMock(side_effect=lambda *a, **k: calls.append("upsert_evaluation"))
    mem.set_payload = AsyncMock(side_effect=lambda *a, **k: calls.append("set_payload"))
    mem.retrieve_points = AsyncMock(return_value=[MagicMock(payload=gen.to_payload())] if gen else [])
    return VisualGenerationStore(mem), mem, calls


def test_record_evaluation_writes_then_sets_the_reaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ev.EXECUTION_TRUTH_ENV, "2000-01-01")
    gen = VisualGeneration(caption="c")
    store, mem, calls = fake_store(gen)
    out = asyncio.run(ev.record_evaluation(entry(gen, rating=2, change=["softer light"]), store=store))
    assert calls == ["upsert_evaluation", "set_payload"]                      # evaluation first
    payload = mem.set_payload.await_args.args[2]
    assert payload["reaction"] == "disliked" and payload["rating"] == 2
    assert payload["notes"] == "softer light" and payload["context"] == "face reads plastic"
    assert out.agent_status is None                                           # verified era: untouched


def test_record_evaluation_marks_pre_fix_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ev.EXECUTION_TRUTH_ENV, raising=False)
    gen = VisualGeneration(caption="c")
    store, mem, _ = fake_store(gen)
    out = asyncio.run(ev.record_evaluation(entry(gen), store=store))
    assert out.agent_status == "unresolved"
    written = mem.upsert_raw_points.await_args.args[1][0].payload
    assert written["agent_status"] == "unresolved"


def test_record_evaluation_rejects_unknown_generations_and_bad_reactions() -> None:
    store, mem, calls = fake_store(None)
    with pytest.raises(LookupError, match="no generation"):
        asyncio.run(ev.record_evaluation(entry(), store=store))
    with pytest.raises(ValueError, match="reaction must be one of"):
        asyncio.run(ev.record_evaluation(entry(reaction="pending"), store=store))
    assert calls == []                                                        # nothing written


def test_a_failure_setting_the_reaction_is_reported_as_a_partial_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ev.EXECUTION_TRUTH_ENV, "2000-01-01")
    gen = VisualGeneration(caption="c")
    store, mem, calls = fake_store(gen)
    mem.set_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    with pytest.raises(ev.EvaluationPartialWrite) as e:
        asyncio.run(ev.record_evaluation(entry(gen), store=store))
    assert calls == ["upsert_evaluation"] and "was written" in str(e.value) and "safe" in str(e.value)
    assert e.value.entry.gen_id == gen.entry_id


def test_store_evaluation_methods_filter_by_gen_chain_and_project() -> None:
    store, mem, _ = fake_store(None)
    mem._client.scroll = AsyncMock(return_value=([MagicMock(payload=entry().to_payload())], None))
    out = asyncio.run(store.list_evaluations(gen_id="g1", chain_root_id="root", project="p"))
    assert [e.gen_id for e in out] == ["g1"]
    conds = {c.key: c.match.value for c in mem._client.scroll.await_args.kwargs["scroll_filter"].must}
    assert conds == {"memory_type": "evaluation", "gen_id": "g1", "chain_root_id": "root", "project": "p"}
    mem.query_by_vector = AsyncMock(return_value=[("id", 0.9, entry().to_payload())])
    hits = asyncio.run(store.search_evaluations("plastic", project="p"))
    assert hits[0][2].raw_feedback == "face reads plastic"
    assert {c.key for c in mem.query_by_vector.await_args.kwargs["filters"].must} == {"memory_type", "project"}


def test_get_evaluation_ignores_other_memory_types() -> None:
    store, mem, _ = fake_store(None)
    mem.retrieve_points = AsyncMock(return_value=[MagicMock(payload=VisualGeneration(caption="c").to_payload())])
    assert asyncio.run(store.get_evaluation("x")) is None
    mem.retrieve_points = AsyncMock(return_value=[MagicMock(payload=entry().to_payload())])
    assert asyncio.run(store.get_evaluation("x")).raw_feedback == "face reads plastic"
