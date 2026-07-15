from __future__ import annotations

from visual_generation.lora_guard import (
    DEFAULT_STRENGTH_WARN,
    prune_noncanon_identity,
    strength_warnings,
)
from visual_generation.models import LoraRef


def _ident(*names: str):
    s = set(names)
    return lambda n: n in s


# ── strength_warnings ─────────────────────────────────────────────────────────


def test_sane_stack_has_no_warnings() -> None:
    stack = [LoraRef(name="a.safetensors", strength=1.0), LoraRef(name="b.safetensors", strength=0.9)]
    assert strength_warnings(stack) == []


def test_per_entry_ceiling_warns_and_names_the_lora() -> None:
    stack = [LoraRef(name="narrator.safetensors", strength=2.0)]
    warns = strength_warnings(stack)
    assert len(warns) == 1
    assert "narrator.safetensors" in warns[0]
    assert "overrides prompt adherence" in warns[0]
    assert "bleeds" in warns[0]


def test_exactly_at_ceiling_warns() -> None:
    stack = [LoraRef(name="x.safetensors", strength=DEFAULT_STRENGTH_WARN)]
    assert strength_warnings(stack)


def test_just_under_ceiling_is_silent() -> None:
    stack = [LoraRef(name="x.safetensors", strength=DEFAULT_STRENGTH_WARN - 0.01)]
    assert strength_warnings(stack) == []


def test_custom_ceiling_can_tighten_for_a_model() -> None:
    # A Turbo model might warn earlier (wants ~1.0).
    stack = [LoraRef(name="turbo-lora.safetensors", strength=1.2)]
    assert strength_warnings(stack) == []  # under universal default
    assert strength_warnings(stack, ceiling=1.1)  # tightened for this model


def test_two_identity_loras_always_draw_stacking_advisory() -> None:
    # Even a "clean" 1.0 + 1.0 pair warns: dual-identity stacking is deprecated
    # outright (audit §6) — no strength pair isolates identities in a single pass.
    stack = [
        LoraRef(name="narrator.safetensors", strength=1.0),
        LoraRef(name="celeste.safetensors", strength=1.0),
    ]
    warns = strength_warnings(stack, is_identity=_ident("narrator.safetensors", "celeste.safetensors"))
    assert len(warns) == 1
    assert "deprecated" in warns[0]
    assert "sequential masked" in warns[0]


def test_stacking_advisory_ignores_non_identity() -> None:
    stack = [
        LoraRef(name="narrator.safetensors", strength=1.0),
        LoraRef(name="detail.safetensors", strength=1.0),  # not identity
    ]
    warns = strength_warnings(stack, is_identity=_ident("narrator.safetensors"))
    assert warns == []


def test_no_stacking_advisory_without_identity_predicate() -> None:
    # With no is_identity predicate the stacking check is skipped entirely —
    # otherwise every 2-LoRA stack (character + detail) would misfire.
    stack = [
        LoraRef(name="a.safetensors", strength=1.0),
        LoraRef(name="b.safetensors", strength=1.0),
    ]
    assert strength_warnings(stack) == []


# ── prune_noncanon_identity ───────────────────────────────────────────────────


def test_prune_drops_alternate_checkpoint_keeps_canon_pin() -> None:
    stack = [
        LoraRef(name="narrator-turbo-2500.safetensors", strength=0.85),  # LLM's stray alt
        LoraRef(name="narrator-turbo.safetensors", strength=1.0),  # canon pin
    ]
    is_identity = _ident("narrator-turbo-2500.safetensors", "narrator-turbo.safetensors")
    kept, notes = prune_noncanon_identity(stack, {"narrator-turbo.safetensors"}, is_identity=is_identity)
    assert [lr.name for lr in kept] == ["narrator-turbo.safetensors"]
    assert len(notes) == 1
    assert "narrator-turbo-2500.safetensors" in notes[0]


def test_prune_drops_superseded_era_lora_that_is_a_prefix_of_the_pin() -> None:
    # base-era `narrator-coraline` is a prefix of the pinned `narrator-coraline-turbo`
    # → same character, superseded file, must be pruned (prefix in the OTHER direction).
    stack = [
        LoraRef(name="narrator-coraline.safetensors", strength=1.0),  # superseded base era
        LoraRef(name="narrator-coraline-turbo.safetensors", strength=1.0),  # canon pin
    ]
    is_identity = _ident("narrator-coraline.safetensors", "narrator-coraline-turbo.safetensors")
    kept, notes = prune_noncanon_identity(
        stack, {"narrator-coraline-turbo.safetensors"}, is_identity=is_identity
    )
    assert [lr.name for lr in kept] == ["narrator-coraline-turbo.safetensors"]
    assert len(notes) == 1


def test_prune_keeps_different_characters_in_a_two_shot() -> None:
    # narrator + celeste both pinned — a legit two-shot, nothing dropped.
    stack = [
        LoraRef(name="narrator-turbo.safetensors", strength=1.0),
        LoraRef(name="celeste-turbo.safetensors", strength=1.0),
    ]
    pins = {"narrator-turbo.safetensors", "celeste-turbo.safetensors"}
    kept, notes = prune_noncanon_identity(stack, pins, is_identity=_ident(*pins))
    assert [lr.name for lr in kept] == [lr.name for lr in stack]
    assert notes == []


def test_prune_keeps_identity_lora_with_no_colliding_pin() -> None:
    # Project pins narrator only; an inherited celeste-family identity LoRA that
    # collides with NO pin is left alone (canon has no authority to override it).
    stack = [LoraRef(name="celeste-felt.safetensors", strength=0.7)]
    kept, notes = prune_noncanon_identity(
        stack, {"narrator-turbo.safetensors"}, is_identity=_ident("celeste-felt.safetensors")
    )
    assert [lr.name for lr in kept] == ["celeste-felt.safetensors"]
    assert notes == []


def test_prune_no_pins_keeps_everything() -> None:
    # No canon file / no pins → no authority to prune any identity LoRA.
    stack = [LoraRef(name="felt.safetensors", strength=0.7)]
    kept, notes = prune_noncanon_identity(stack, set(), is_identity=_ident("felt.safetensors"))
    assert [lr.name for lr in kept] == ["felt.safetensors"]
    assert notes == []


def test_prune_keeps_non_identity_loras() -> None:
    stack = [
        LoraRef(name="detail.safetensors", strength=0.6),  # style/detail, not identity
        LoraRef(name="celeste-turbo.safetensors", strength=1.0),  # canon pin
    ]
    is_identity = _ident("celeste-turbo.safetensors")  # detail is NOT identity
    kept, notes = prune_noncanon_identity(stack, {"celeste-turbo.safetensors"}, is_identity=is_identity)
    assert [lr.name for lr in kept] == ["detail.safetensors", "celeste-turbo.safetensors"]
    assert notes == []


def test_prune_preserves_order_and_is_noop_on_clean_stack() -> None:
    stack = [
        LoraRef(name="narrator-turbo.safetensors", strength=1.0),
        LoraRef(name="celeste-turbo.safetensors", strength=1.0),
    ]
    pins = {"narrator-turbo.safetensors", "celeste-turbo.safetensors"}
    is_identity = _ident(*pins)
    kept, notes = prune_noncanon_identity(stack, pins, is_identity=is_identity)
    assert [lr.name for lr in kept] == [lr.name for lr in stack]
    assert notes == []
