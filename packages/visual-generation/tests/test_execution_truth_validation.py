"""Entry-gate item 5: out-of-range values are rejected at plan time, before any spend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from visual_generation.batch_file import write_batch
from visual_generation.generate import plan_generation_sync
from visual_generation.models import GenerationBatch, LoraRef, VisualSource, VisualSpec
from visual_generation.validation import BOUNDS, validate_spec


def spec(**kw) -> VisualSpec:
    base = dict(prompt="a plain red mug", seed=7, width=1024, height=1024,
                settings={"steps": 8, "cfg": 1.0}, workflow_ref="flux-txt2img", project="proj")
    base.update(kw)
    return VisualSpec(**base)


def with_settings(**settings) -> VisualSpec:
    return spec(settings=settings)


# ── the bounds, both edges ────────────────────────────────────────────────────


@pytest.mark.parametrize("key,ok,bad", [
    ("steps", [1, 8, 150], [0, -1, 151, 1000]),
    ("cfg", [0, 1.0, 30], [-0.1, 30.5, 100]),
    ("denoise", [0, 0.5, 1], [-0.01, 1.01, 5]),
    ("flux_guidance", [0, 3.5, 20], [-1, 20.5]),
    ("fps", [1, 16, 120], [0, 121]),
    ("length", [1, 5, 81, 513], [0, 2, 80, 514, 517]),     # 4n+1, 1..513
])
def test_setting_bounds_accept_the_edges_and_reject_outside(key, ok, bad) -> None:
    for v in ok:
        assert validate_spec(with_settings(**{key: v})) == [], (key, v)
    for v in bad:
        problems = validate_spec(with_settings(**{key: v}))
        assert len(problems) == 1 and key in problems[0], (key, v, problems)


def test_steps_must_be_whole_numbers() -> None:
    assert validate_spec(with_settings(steps=8.0)) == []              # an integral float is fine
    assert "whole number" in validate_spec(with_settings(steps=8.5))[0]


@pytest.mark.parametrize("bad", ["8", None, True, [8]])
def test_non_numeric_settings_are_rejected(bad) -> None:
    problems = validate_spec(with_settings(steps=bad))
    assert len(problems) == 1 and "must be a number" in problems[0]


def test_unknown_and_free_form_settings_are_left_alone() -> None:
    assert validate_spec(with_settings(sampler="res_multistep", scheduler="simple", shift=99)) == []


@pytest.mark.parametrize("w,h,ok", [
    (64, 64, True), (1024, 1024, True), (4096, 4096, True), (832, 1216, True),
    (1001, 1024, False), (1024, 1001, False), (56, 1024, False), (1024, 4104, False), (0, 1024, False),
])
def test_size_must_be_a_multiple_of_8_within_64_and_4096(w, h, ok) -> None:
    problems = validate_spec(spec(width=w, height=h))
    assert (problems == []) is ok, problems


def test_unset_size_is_not_checked() -> None:
    assert validate_spec(spec(width=None, height=None)) == []


@pytest.mark.parametrize("strength,ok", [(0, True), (0.8, True), (1.0, True), (4.0, True),
                                         (-0.1, False), (4.01, False)])
def test_lora_strength_bounds(strength, ok) -> None:
    problems = validate_spec(spec(lora_stack=[LoraRef(name="a.safetensors", strength=strength)]))
    assert (problems == []) is ok
    if not ok:
        assert "a.safetensors" in problems[0] and "strength" in problems[0]


@pytest.mark.parametrize("seed,ok", [(0, True), (123456789, True), (2**64 - 1, True), (-1, False), (2**64, False)])
def test_a_fixed_seed_must_fit_a_64_bit_unsigned_integer(seed, ok) -> None:
    assert (validate_spec(spec(seed=seed)) == []) is ok


def test_every_problem_is_reported_at_once_with_the_value_and_the_bound() -> None:
    problems = validate_spec(spec(width=1001, settings={"steps": 500, "cfg": -1, "denoise": 3}))
    assert len(problems) == 4
    assert any("steps" in p and "500" in p and "150" in p for p in problems)
    assert any("width" in p and "1001" in p for p in problems)


def test_the_bounds_are_the_documented_defaults() -> None:
    assert (BOUNDS["steps"], BOUNDS["cfg"], BOUNDS["denoise"]) == ((1, 150), (0, 30), (0, 1))
    assert BOUNDS["lora_strength"] == (0, 4) and BOUNDS["size"] == (64, 4096)


# ── the refinement default is part of what runs, so it is checked too ─────────


def test_the_effective_denoise_default_is_validated(monkeypatch) -> None:
    import visual_generation.validation as v

    monkeypatch.setitem(v.BOUNDS, "denoise", (0.6, 1))        # the 0.5 default would now be out of range
    refine = spec(source=VisualSource(from_generation="g"))
    assert any("denoise" in p for p in v.validate_spec(refine, effective=True))
    assert v.validate_spec(spec(), effective=True) == []        # no source: no default is injected


# ── the plan rejects before any spend ─────────────────────────────────────────


def _plan(tmp_path: Path, template, sp: VisualSpec):
    path = tmp_path / "b.batch.md"
    write_batch(GenerationBatch(project="proj", specs=[sp]), path)
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=template)
    store.recent_generation_costs = AsyncMock(return_value=[])
    store.get_model = lambda n: None
    return plan_generation_sync(path, all_sections=True, gpu_rate=3.0, store=store, memory_store=MagicMock())


def test_an_out_of_range_spec_is_skipped_with_every_reason(tmp_path: Path, flux_template) -> None:
    plan = _plan(tmp_path, flux_template, spec(settings={"steps": 500, "cfg": 1.0}, width=1001))
    assert plan.plans == [] and len(plan.skipped) == 1
    reason = plan.skip_reasons[plan.skipped[0]]
    assert "steps" in reason and "500" in reason and "width" in reason and reason.startswith("Skipped ")


def test_an_in_range_spec_is_planned_unchanged(tmp_path: Path, flux_template) -> None:
    plan = _plan(tmp_path, flux_template, spec(settings={"steps": 20, "cfg": 1.0, "flux_guidance": 3.5}))
    assert len(plan.plans) == 1 and plan.skipped == []


def test_nothing_is_clamped_the_spec_is_refused_not_edited(tmp_path: Path, flux_template) -> None:
    plan = _plan(tmp_path, flux_template, spec(settings={"steps": 151}))
    assert plan.plans == []                                   # no graph exists to hold a clamped 150


def test_quick_rejects_an_out_of_range_value_before_submitting(flux_template) -> None:
    from visual_generation.quick import QuickInvalidSpec, quick_generate_sync

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_template_by_name = AsyncMock(return_value=flux_template)
    store.get_model = lambda n: None
    client = MagicMock()
    with pytest.raises(QuickInvalidSpec, match="steps"):
        quick_generate_sync("a mug", endpoint="x", template_name="flux-txt2img", seed=1, store=store,
                            client=client, settings={"steps": 999})
    client.submit.assert_not_called()
