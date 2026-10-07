from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from visual_generation.chat.interpretation import (
    EvalContext,
    InterpretationError,
    build_evaluation,
    build_interpretation,
    gather_context,
    recipe_text,
    render_entry,
    render_interpretation,
)
from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.schemas import (
    EvaluationInput,
    InterpretationInput,
    Reaction,
    Status,
)
from visual_generation.constants import REACTIONS
from visual_generation.evaluation import evaluation_id
from visual_generation.models import (
    EvaluationEntry,
    Evidence,
    Finding,
    Layer,
    LoraRef,
    VisualGeneration,
)

from .conftest import Built, make_gens  # type: ignore[import-not-found]

GOLDEN = Path(__file__).parent / "golden" / "feedback.jsonl"
NOW = "2026-10-06T12:00:00+00:00"


def ctx_for(gens: list[VisualGeneration], labels: dict[str, str | None] | None = None,
            prior: list[EvaluationEntry] | None = None, **kw: Any) -> EvalContext:
    r = LabelResolver(gens)
    labels = {"attempt-03": r.resolve("attempt-03").gen_id, **(labels or {})}
    return EvalContext(
        resolver=r, resolved={k: (v, "" if v else "no such attempt") for k, v in labels.items()},
        gens={g.entry_id: g for g in gens}, prior_evals=prior or [], project="demo", session_id="sess-1",
        engine_provider="claude", engine_model="claude-sonnet-4-6", now=NOW, since="2000-01-01", **kw)


def inp(**kw: Any) -> InterpretationInput:
    base: dict[str, Any] = dict(generation="attempt-03", raw_feedback="the face reads plastic",
                                reaction="disliked")
    base.update(kw)
    return InterpretationInput(**base)


def finding(layer: Layer = Layer.CONDITIONING_ASSET, ev: Evidence = Evidence.OBSERVED, text: str = "eyes") -> Finding:
    return Finding(layer=layer, evidence=ev, statement=text, basis="attempt-03 asset")


GENS = make_gens(8)


# ── schema ────────────────────────────────────────────────────────────────────


def test_the_model_facing_reaction_vocabulary_is_the_stores() -> None:
    from typing import get_args

    assert list(get_args(Reaction)) == REACTIONS
    assert "unresolved" in get_args(Status) and "agent-pass" in get_args(Status)


def test_interpretation_input_extends_the_evaluation_input() -> None:
    assert set(EvaluationInput.model_fields) < set(InterpretationInput.model_fields)
    assert {"revised_spec", "lessons", "open_questions"} <= set(InterpretationInput.model_fields)
    json.dumps(InterpretationInput.model_json_schema())
    with pytest.raises(ValueError):
        inp(reaction="meh")
    with pytest.raises(ValueError):
        inp(rating=9)


# ── the evaluation: code fills the system fields, the model does not ──────────


def test_the_evaluation_gets_its_system_fields_from_code() -> None:
    entry, qs = build_evaluation(inp(rating=2, question="does the pose hold?", change=["softer light"],
                                     findings=[finding()], strike_class="bleed"), ctx_for(GENS))
    g = GENS[2]
    assert entry.gen_id == g.entry_id and entry.chain_root_id == g.chain_root_id and entry.project == "demo"
    assert (entry.session_id, entry.engine_provider, entry.engine_model) == ("sess-1", "claude", "claude-sonnet-4-6")
    assert entry.created_at == NOW and entry.raw_feedback == "the face reads plastic"
    assert entry.entry_id == evaluation_id(g.entry_id, "disliked", "the face reads plastic")
    assert (entry.reaction, entry.rating, entry.question, entry.strike_class) == ("disliked", 2, "does the pose hold?", "bleed")
    assert qs == []


def test_keep_constraints_resolve_labels_and_unresolved_ones_become_questions() -> None:
    ctx = ctx_for(GENS, {"attempt-07": LabelResolver(GENS).resolve("attempt-07").gen_id, "attempt-99": None})
    entry, qs = build_evaluation(inp(keep=[{"attribute": "jaw", "source": "attempt-07"},
                                           {"attribute": "coat", "source": "attempt-99"}]), ctx)
    assert [(k.attribute, k.source_gen_id) for k in entry.keep] == [("jaw", GENS[6].entry_id)]
    assert len(qs) == 1 and "attempt-99" in qs[0] and "coat" in qs[0]


def test_a_generation_made_before_verified_execution_is_marked_unresolved() -> None:
    ctx = ctx_for(GENS)
    ctx.since = None                                          # flag unset: nothing is trusted yet
    entry, _ = build_evaluation(inp(agent_status="agent-pass"), ctx)
    assert entry.agent_status == "unresolved"
    assert any(f.layer is Layer.AGENT_CORRECTNESS and "seed may not match" in f.statement for f in entry.findings)
    ctx.since = "2000-01-01"                                  # verified long ago: left alone
    assert build_evaluation(inp(agent_status="agent-pass"), ctx)[0].agent_status == "agent-pass"


def test_keep_and_change_text_are_rendered_for_the_gate() -> None:
    ctx = ctx_for(GENS, {"attempt-07": GENS[6].entry_id})
    entry, _ = build_evaluation(inp(rating=2, change=["softer light"], required_outcomes=["two puppets visible"],
                                    keep=[{"attribute": "jaw", "source": "attempt-07"}], findings=[finding()],
                                    strike_class="bleed"), ctx)
    text = render_entry(entry, ctx.resolver)
    for needle in ("attempt-03", "DISLIKED ★2", "the face reads plastic", "Keep: jaw (from attempt-07",
                   "Change: softer light", "Required outcome: two puppets visible", "Finding (observed) [conditioning_asset]",
                   "Strike class: bleed"):
        assert needle in text


# ── rule 4: numbers come from the record or the director ─────────────────────


def test_an_invented_number_in_change_is_rejected_with_the_way_out() -> None:
    with pytest.raises(InterpretationError, match="open_parameter"):
        build_evaluation(inp(change=["lower denoise to 0.35"]), ctx_for(GENS))


def test_numbers_from_the_directors_words_or_the_recipe_are_fine() -> None:
    g = GENS[2]
    g.settings = {"steps": 8, "denoise": 0.5}
    g.seed = 4471
    g.lora_stack = [LoraRef(name="narrator", strength=1.0)]
    g.width, g.height = 832, 1216
    ctx = ctx_for(GENS)
    build_evaluation(inp(raw_feedback="keep denoise 0.5 but fix the face", change=["keep denoise 0.5"]), ctx)
    build_evaluation(inp(change=["same seed 4471, same steps 8, same size 832"]), ctx)
    build_evaluation(inp(change=["keep the jaw from attempt-07 and #12"]), ctx)       # labels are not values
    assert "4471" in recipe_text(g) and "narrator 1.0" in recipe_text(g)


def test_revised_spec_changes_obey_the_same_rule_but_open_parameters_may_hold_numbers() -> None:
    ctx = ctx_for(GENS)
    bad = inp(revised_spec={"base": "attempt-03", "mode": "redraft", "changes": ["use cfg 4.5"]})
    with pytest.raises(InterpretationError, match="revised_spec.changes"):
        build_interpretation(bad, ctx)
    ok = inp(revised_spec={"base": "attempt-03", "mode": "redraft", "changes": ["lower the cfg"],
                           "open_parameters": ["new cfg value (was 1.0)"]})
    fi = build_interpretation(ok, ctx)
    assert fi.revised_spec is not None and fi.revised_spec.open_parameters == ["new cfg value (was 1.0)"]


# ── rule 3: three strikes ─────────────────────────────────────────────────────


def prior_failures(n: int, cls: str = "bleed", gen: VisualGeneration | None = None) -> list[EvaluationEntry]:
    g = gen or GENS[2]
    return [EvaluationEntry(gen_id=g.entry_id, chain_root_id=g.chain_root_id, reaction="disliked",
                            raw_feedback=f"f{i}", strike_class=cls, created_at=f"2026-10-01T00:00:{i:02d}+00:00")
            for i in range(1, n + 1)]


def redraft(**kw: Any) -> InterpretationInput:
    base = dict(strike_class="bleed", revised_spec={"base": "attempt-03", "mode": "redraft", "changes": ["calmer wording"]})
    base.update(kw)
    return inp(**base)


def test_a_fourth_same_class_redraft_is_refused_until_an_architecture_question_is_recorded() -> None:
    ctx = ctx_for(GENS, prior=prior_failures(2))             # two before + this one = three failures
    with pytest.raises(InterpretationError, match="architecture question"):
        build_interpretation(redraft(), ctx)
    q = {"layer_blamed": "prompt", "alternative_layer": "conditioning_asset", "question": "is the bleed a routing gap?"}
    fi = build_interpretation(redraft(architecture_question=q), ctx)
    assert fi.revised_spec is not None and fi.strike.count == 0 and not fi.strike.blocked


def test_strike_rule_does_not_block_other_layers_other_classes_or_fewer_failures() -> None:
    ctx = ctx_for(GENS, prior=prior_failures(2))
    for mode in ("new_draft", "inpaint", "refine_img2img"):                       # a change of layer is the way out
        build_interpretation(redraft(revised_spec={"base": "attempt-03", "mode": mode, "changes": ["mask the eyes"]}), ctx)
    build_interpretation(redraft(strike_class="seed-choice"), ctx)                # a different class
    build_interpretation(redraft(), ctx_for(GENS, prior=prior_failures(1)))        # only two failures so far
    build_interpretation(redraft(reaction="liked_with_changes"), ctx)              # a positive reaction ends the run
    build_interpretation(redraft(strike_class=None), ctx)                          # no class declared


def test_the_evaluation_is_still_recorded_when_a_redraft_is_refused() -> None:
    """The failure itself is evidence; only the next same-class redraft is blocked."""
    entry, _ = build_evaluation(redraft(), ctx_for(GENS, prior=prior_failures(2)))
    assert entry.strike_class == "bleed"


def test_the_strike_count_is_reported() -> None:
    fi = build_interpretation(inp(strike_class="bleed"), ctx_for(GENS, prior=prior_failures(1)))
    assert (fi.strike.strike_class, fi.strike.count, fi.strike.blocked) == ("bleed", 2, False)


# ── rules 1 and 2: lessons ────────────────────────────────────────────────────


def lesson(**kw: Any) -> dict[str, Any]:
    base = dict(statement="describe the narrator's face in more detail", scope="prompt", valence="positive",
                layer="prompt", topic="identity")
    base.update(kw)
    return base


def test_a_prompt_layer_identity_lesson_needs_a_falsification_test() -> None:
    with pytest.raises(InterpretationError, match="lesson 1.*falsification_test"):
        build_interpretation(inp(lessons=[lesson()]), ctx_for(GENS))
    fi = build_interpretation(inp(lessons=[lesson(falsification_test="same seed, prompt-only change flips the face")]),
                              ctx_for(GENS))
    assert len(fi.lessons) == 1


def test_validated_needs_five_results_and_a_held_out_evaluation_that_exists() -> None:
    kw = dict(layer="conditioning_asset", topic="identity", claim_level="validated")
    with pytest.raises(InterpretationError, match="evidence_n >= 5"):
        build_interpretation(inp(lessons=[lesson(**kw, evidence_n=3, held_out_eval_id="e1")]), ctx_for(GENS, known_eval_ids={"e1"}))
    with pytest.raises(InterpretationError, match="held-out"):
        build_interpretation(inp(lessons=[lesson(**kw, evidence_n=6, held_out_eval_id="ghost")]), ctx_for(GENS, known_eval_ids={"e1"}))
    ok = build_interpretation(inp(lessons=[lesson(**kw, evidence_n=6, held_out_eval_id="e1")]), ctx_for(GENS, known_eval_ids={"e1"}))
    assert ok.lessons[0].claim_level == "validated"


def test_lessons_cite_this_evaluation_by_default() -> None:
    fi = build_interpretation(inp(lessons=[lesson(layer="conditioning_asset")]), ctx_for(GENS))
    assert fi.lessons[0].source_eval_ids == [fi.evaluation.entry_id]
    own = build_interpretation(inp(lessons=[lesson(layer="conditioning_asset", source_eval_ids=["x"])]), ctx_for(GENS))
    assert own.lessons[0].source_eval_ids == ["x"]


def test_open_questions_merge_and_unresolved_bases_ask() -> None:
    fi = build_interpretation(
        inp(open_questions=["Which scene?", "Which scene?"], revised_spec={"base": "attempt-99", "mode": "redraft", "changes": ["x"]}),
        ctx_for(GENS, {"attempt-99": None}))
    assert fi.open_questions.count("Which scene?") == 1
    assert any("attempt-99" in q for q in fi.open_questions)
    assert fi.revised_spec is not None and fi.revised_spec.base_gen_id is None


def test_render_says_proposal_only_and_lists_everything() -> None:
    ctx = ctx_for(GENS)
    fi = build_interpretation(inp(strike_class="bleed", findings=[finding()], lessons=[lesson(layer="conditioning_asset")],
                                  revised_spec={"base": "attempt-03", "mode": "inpaint", "changes": ["mask the eyes"],
                                                "open_parameters": ["denoise for the mask"]},
                                  open_questions=["Is this the narrator?"]), ctx)
    text = render_interpretation(fi, ctx.resolver)
    for needle in ("Strikes for 'bleed': 1 of 3", "Proposed revision (inpaint)", "director to decide: denoise for the mask",
                   "1 lesson candidate(s)", "never auto-confirmed", "Open questions:", "Is this the narrator?",
                   "Proposal only: nothing was stored."):
        assert needle in text


# ── gathering the context (the reads) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_gather_context_resolves_labels_and_loads_the_chain(build: Callable[..., Built]) -> None:
    gens = make_gens(4)
    root = gens[0]
    gens[2].parent_id, gens[2].chain_root_id = root.entry_id, root.entry_id
    prior = prior_failures(2, gen=gens[2])
    b = build(gens=gens, evals=prior)
    b.state.session = type("S", (), {"session_id": "s9", "engine": type("E", (), {"provider": "openai", "model": "gpt-5-mini"})()})()
    ctx = await gather_context(b.state, inp(generation="attempt-03", keep=[{"attribute": "jaw", "source": "attempt-01"},
                                                                        {"attribute": "x", "source": "attempt-44"}]))
    assert ctx.resolved["attempt-03"][0] == gens[2].entry_id and ctx.resolved["attempt-44"][0] is None
    assert [e.raw_feedback for e in ctx.prior_evals] == ["f1", "f2"]
    assert (ctx.session_id, ctx.engine_provider, ctx.engine_model) == ("s9", "openai", "gpt-5-mini")
    assert ctx.project == "demo"


@pytest.mark.asyncio
async def test_gather_context_refuses_an_unknown_generation_with_an_open_question(build: Callable[..., Built]) -> None:
    with pytest.raises(InterpretationError) as e:
        await gather_context(build(gens=make_gens(2)).state, inp(generation="attempt-09"))
    assert e.value.open_questions and "attempt-09" in str(e.value)


@pytest.mark.asyncio
async def test_gather_context_checks_which_held_out_ids_exist(build: Callable[..., Built]) -> None:
    held = prior_failures(1)
    b = build(gens=GENS_COPY(), evals=held)
    ctx = await gather_context(b.state, inp(lessons=[lesson(layer="conditioning_asset", held_out_eval_id=held[0].entry_id),
                                                    lesson(statement="other", layer="outcome", held_out_eval_id="ghost")]))
    assert ctx.known_eval_ids == {held[0].entry_id}


def GENS_COPY() -> list[VisualGeneration]:
    return make_gens(8)


# ── golden file (format only; the live check is test_golden_live.py) ─────────


def golden_cases() -> list[dict[str, object]]:
    return [json.loads(x) for x in GOLDEN.read_text().splitlines() if x.strip() and not x.startswith("#")]


def test_golden_file_has_the_documented_format() -> None:
    cases = golden_cases()
    assert len(cases) >= 3
    for c in cases:
        assert isinstance(c["feedback"], str) and c["feedback"].strip()
        labels = c.get("context_labels", [])
        assert isinstance(labels, list) and all(isinstance(x, str) for x in labels)
        assert isinstance(c.get("attempts", 8), int)
