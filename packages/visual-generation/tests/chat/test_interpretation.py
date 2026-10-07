from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_generation.chat.interpretation import InterpretationError, interpret, render_interpretation
from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.schemas import InterpretationInput, ObservationInput
from visual_generation.models import VisualGeneration

GOLDEN = Path(__file__).parent / "golden" / "feedback.jsonl"


def resolver(n: int = 8) -> LabelResolver:
    return LabelResolver([
        VisualGeneration(caption=f"c{i}", created_at=f"2026-01-01T00:00:{i:02d}+00:00") for i in range(1, n + 1)
    ])


def obs(**kw: object) -> ObservationInput:
    base: dict[str, object] = dict(
        layer="production_quality", category="prompt", attribution="prompt", claim="too plastic",
    )
    base.update(kw)
    return ObservationInput(**base)  # type: ignore[arg-type]


def test_resolves_labels_and_keeps_the_claims() -> None:
    r = resolver()
    fi = interpret(InterpretationInput(feedback="f", observations=[obs(label="attempt-07")]), r)
    o = fi.observations[0]
    assert o.resolved_gen_id == r.resolve("attempt-07").gen_id and fi.open_questions == []
    assert (o.layer, o.category, o.attribution, o.claim) == ("production_quality", "prompt", "prompt", "too plastic")


def test_unresolved_label_becomes_an_open_question_never_a_guessed_id() -> None:
    fi = interpret(InterpretationInput(feedback="f", observations=[obs(label="attempt-99")]), resolver(3))
    assert fi.observations[0].resolved_gen_id is None
    assert len(fi.open_questions) == 1 and "attempt-99" in fi.open_questions[0]


def test_questions_are_merged_and_deduplicated() -> None:
    fi = interpret(InterpretationInput(
        feedback="f", open_questions=["Is this the narrator?", "Is this the narrator?"],
        observations=[obs(label="attempt-99"), obs(label="attempt-99")],
    ), resolver(3))
    assert fi.open_questions.count("Is this the narrator?") == 1
    assert sum("attempt-99" in q for q in fi.open_questions) == 1


def test_observation_without_a_label_is_fine() -> None:
    fi = interpret(InterpretationInput(feedback="f", observations=[obs()]), resolver())
    assert fi.observations[0].resolved_gen_id is None and fi.open_questions == []


def test_suggested_redraft_resolves_or_asks() -> None:
    r = resolver()
    ok = interpret(InterpretationInput(feedback="f", observations=[obs()],
                                       suggested_redraft={"label": "attempt-02", "change": "softer light"}), r)  # type: ignore[arg-type]
    assert ok.suggested_redraft is not None and ok.suggested_redraft.resolved_gen_id == r.resolve("attempt-02").gen_id
    bad = interpret(InterpretationInput(feedback="f", observations=[obs()],
                                        suggested_redraft={"label": "nope", "change": "x"}), r)  # type: ignore[arg-type]
    assert bad.suggested_redraft is not None and bad.suggested_redraft.resolved_gen_id is None
    assert any("redraft" in q for q in bad.open_questions)


@pytest.mark.parametrize("category", ["identity", "staging", "set"])
def test_conditioning_first_rejects_a_prompt_blame_without_evidence(category: str) -> None:
    with pytest.raises(InterpretationError, match="conditioning"):
        interpret(InterpretationInput(feedback="f", observations=[obs(category=category, attribution="prompt")]), resolver())


@pytest.mark.parametrize("category", ["identity", "staging", "set"])
def test_conditioning_first_accepts_conditioning_or_evidence(category: str) -> None:
    interpret(InterpretationInput(feedback="f", observations=[obs(category=category, attribution="conditioning")]), resolver())
    interpret(InterpretationInput(feedback="f", observations=[
        obs(category=category, attribution="prompt", evidence="same seed, prompt-only change flipped it")]), resolver())


def test_other_categories_need_no_evidence() -> None:
    for category in ("prompt", "settings", "model", "other"):
        interpret(InterpretationInput(feedback="f", observations=[obs(category=category, attribution="settings")]), resolver())


def test_enums_are_enforced_by_the_schema() -> None:
    with pytest.raises(ValueError):
        ObservationInput(layer="vibes", category="prompt", attribution="prompt", claim="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        obs(status="certain")


def test_render_says_nothing_was_stored_and_lists_open_questions() -> None:
    r = resolver()
    fi = interpret(InterpretationInput(feedback="the face is off", observations=[
        obs(label="attempt-03", claim="button eyes read as plastic"), obs(label="attempt-77")]), r)
    text = render_interpretation(fi, r)
    assert "button eyes read as plastic" in text and "attempt-03" in text and "attempt-77: unresolved" in text
    assert "Open questions:" in text and "Proposal only: nothing was stored." in text


def test_the_tool_schema_is_valid_json_schema() -> None:
    schema = InterpretationInput.model_json_schema()
    assert {"feedback", "observations"} <= set(schema["required"])
    json.dumps(schema)


# ── the golden file (format check only; the live test in test_golden_live.py uses it) ──


def golden_cases() -> list[dict[str, object]]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip() and not line.startswith("#")]


def test_golden_file_has_the_documented_format() -> None:
    cases = golden_cases()
    assert len(cases) >= 3
    for c in cases:
        assert isinstance(c["feedback"], str) and c["feedback"].strip()
        labels = c.get("context_labels", [])
        assert isinstance(labels, list) and all(isinstance(x, str) for x in labels)
        assert isinstance(c.get("attempts", 8), int)
