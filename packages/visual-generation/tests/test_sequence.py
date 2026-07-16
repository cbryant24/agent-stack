"""Tests for the per-scene FLF2V sequence file (visual_generation.sequence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from visual_generation.models import ClipSpec, Sequence
from visual_generation.sequence import (
    clip_to_spec,
    read_sequence,
    scaffold_sequence,
    validate_sequence,
    write_sequence,
)


def _clip(order: int, first: str, last: str, **overrides) -> ClipSpec:
    base = dict(
        clip_id=f"c{order}", heading=f"clip {order}", motion_prompt=f"action {order}",
        first_frame=first, last_frame=last, workflow_ref="wan22-flf2v",
        settings={"length": 81, "fps": 16}, seed=100 + order, order=order,
    )
    base.update(overrides)
    return ClipSpec(**base)


# ── round-trip ───────────────────────────────────────────────────────────────


def test_round_trip_is_lossless(tmp_path: Path) -> None:
    seq = Sequence(
        project="short-film", scene="bar", fps=16, clip_frames=81,
        clips=[_clip(1, "genA", "genB"), _clip(2, "genB", "genC")],
    )
    path = tmp_path / "bar.sequence.md"
    write_sequence(seq, path)
    restored = read_sequence(path)
    assert restored == seq  # lossless round-trip


def test_motion_prompt_is_the_body_not_duplicated(tmp_path: Path) -> None:
    seq = Sequence(project="p", scene="s", clips=[_clip(1, "a", "b", motion_prompt="a wolf turns")])
    path = tmp_path / "s.sequence.md"
    write_sequence(seq, path)
    text = path.read_text()
    assert "a wolf turns" in text
    # The body appears once (in prose), not inside the JSON metadata.
    assert text.count("a wolf turns") == 1


def test_malformed_clip_json_degrades_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "s.sequence.md"
    path.write_text(
        '<!-- vg-sequence: {"project": "p", "scene": "s", "fps": 16, "clip_frames": 81} -->\n\n'
        "## clip 1\n<!-- vg-clip: {garbled json -->\nthe body survives\n",
        encoding="utf-8",
    )
    seq = read_sequence(path)
    assert len(seq.clips) == 1
    assert seq.clips[0].motion_prompt == "the body survives"
    assert seq.clips[0].heading == "clip 1"


# ── structural validation ────────────────────────────────────────────────────


def test_valid_sequence_has_no_errors() -> None:
    seq = Sequence(clips=[_clip(1, "A", "B"), _clip(2, "B", "C"), _clip(3, "C", "D")])
    assert validate_sequence(seq) == []


def test_boundary_break_is_an_error() -> None:
    # clip 1 ends at B but clip 2 starts at X — not a shared boundary.
    seq = Sequence(clips=[_clip(1, "A", "B"), _clip(2, "X", "C")])
    errors = validate_sequence(seq)
    assert any("boundary break" in e for e in errors)


def test_non_contiguous_order_is_an_error() -> None:
    seq = Sequence(clips=[_clip(1, "A", "B"), _clip(3, "B", "C")])
    errors = validate_sequence(seq)
    assert any("contiguous" in e for e in errors)


def test_missing_frame_is_an_error() -> None:
    seq = Sequence(clips=[_clip(1, "A", "")])
    assert any("missing" in e for e in validate_sequence(seq))


def test_empty_sequence_is_an_error() -> None:
    assert validate_sequence(Sequence(clips=[])) == ["sequence has no clips"]


# ── scaffold ─────────────────────────────────────────────────────────────────


def test_scaffold_wires_shared_boundaries() -> None:
    seq = scaffold_sequence(["k1", "k2", "k3", "k4"], project="p", scene="bar", fps=16, clip_frames=81)
    assert len(seq.clips) == 3  # N keyframes → N-1 clips
    assert [c.order for c in seq.clips] == [1, 2, 3]
    assert seq.clips[0].first_frame == "k1" and seq.clips[0].last_frame == "k2"
    assert seq.clips[1].first_frame == "k2"  # shared boundary
    assert validate_sequence(seq) == []  # scaffolds are structurally valid by construction
    assert seq.clips[0].settings == {"length": 81, "fps": 16}


def test_scaffold_needs_two_keyframes() -> None:
    with pytest.raises(ValueError, match="at least 2 keyframes"):
        scaffold_sequence(["only-one"])


def test_scaffold_fills_motion_prompts_when_given() -> None:
    seq = scaffold_sequence(["a", "b", "c"], motion_prompts=["walk in", "turn around"])
    assert seq.clips[0].motion_prompt == "walk in"
    assert seq.clips[1].motion_prompt == "turn around"


# ── clip → spec bridge ───────────────────────────────────────────────────────


def test_clip_to_spec_builds_flf2v_source() -> None:
    seq = Sequence(project="short-film", scene="bar", fps=16, clip_frames=81,
                   clips=[_clip(1, "genA", "genB")])
    spec = clip_to_spec(seq.clips[0], seq)
    assert spec.workflow_ref == "wan22-flf2v"
    assert spec.source.from_generation == "genA"
    assert spec.source.last_from_generation == "genB"
    assert spec.settings["length"] == 81 and spec.settings["fps"] == 16
    assert spec.project == "short-film"
