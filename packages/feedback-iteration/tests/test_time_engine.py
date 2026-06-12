from __future__ import annotations

import pytest

from feedback_iteration.time_engine import (
    EngineRow,
    _fmt,
    adjust_section_duration,
    measure_gaps,
    set_section_duration,
    shift_section,
)

# The real artifact's first three sections + their recurring 0.500s gaps.
def _rows() -> list[EngineRow]:
    return [
        EngineRow("a", 0.0, 8.4),
        EngineRow("b", 8.9, 24.1),
        EngineRow("c", 24.6, 40.2),
    ]


def test_fmt_matches_edit_brief():
    assert _fmt(0.0) == "00:00.000"
    assert _fmt(8.4) == "00:08.400"
    assert _fmt(73.7) == "01:13.700"


def test_measure_gaps_preserves_per_pair_gaps():
    assert measure_gaps(_rows()) == [0.0, 0.5, 0.5]


def test_adjust_duration_tightens_and_cascades_downstream():
    cm = adjust_section_duration(_rows(), "b", delta=-2.0)
    rows = {r.section_id: (r.start, r.end) for r in cm.rows}
    assert rows["a"] == (0.0, 8.4)          # upstream untouched
    assert rows["b"] == (8.9, 22.1)         # resized: end pulled in 2.0
    assert rows["c"] == (22.6, 38.2)        # downstream shifted -2.0, gap preserved
    kinds = {c.section_id: c.kind for c in cm.changes}
    assert kinds == {"a": "unchanged", "b": "resized", "c": "shifted"}
    # boundary_subs has only changed values, never the 0.500 gap
    olds = {old for old, _ in cm.boundary_subs}
    assert 0.5 not in olds
    assert (24.1, 22.1) in cm.boundary_subs   # b end
    assert (24.6, 22.6) in cm.boundary_subs   # c start
    assert (40.2, 38.2) in cm.boundary_subs   # c end


def test_adjust_duration_longer():
    cm = adjust_section_duration(_rows(), "a", delta=3.0)
    rows = {r.section_id: (r.start, r.end) for r in cm.rows}
    assert rows["a"] == (0.0, 11.4)
    assert rows["b"] == (11.9, 27.1)
    assert rows["c"] == (27.6, 43.2)


def test_set_duration_computes_delta():
    cm = set_section_duration(_rows(), "b", new_length=10.0)  # was 15.2 → -5.2
    rows = {r.section_id: (r.start, r.end) for r in cm.rows}
    assert rows["b"] == (8.9, 18.9)
    assert rows["c"] == (19.4, 35.0)


def test_shift_section_moves_without_resizing():
    cm = shift_section(_rows(), "c", delta=1.0)
    rows = {r.section_id: (r.start, r.end) for r in cm.rows}
    assert rows["a"] == (0.0, 8.4)
    assert rows["b"] == (8.9, 24.1)
    assert rows["c"] == (25.6, 41.2)          # moved +1.0, length unchanged (15.6)
    kinds = {c.section_id: c.kind for c in cm.changes}
    assert kinds["c"] == "shifted"


def test_shift_first_section_rejected():
    with pytest.raises(ValueError):
        shift_section(_rows(), "a", delta=1.0)


def test_negative_length_rejected():
    with pytest.raises(ValueError):
        adjust_section_duration(_rows(), "a", delta=-100.0)


def test_unknown_section_raises():
    with pytest.raises(KeyError):
        adjust_section_duration(_rows(), "nope", delta=1.0)


def test_zero_delta_is_noop():
    cm = adjust_section_duration(_rows(), "b", delta=0.0)
    assert cm.boundary_subs == []
    assert not cm.touched


def test_rounding_to_three_dp():
    cm = adjust_section_duration([EngineRow("a", 0.0, 1.0), EngineRow("b", 1.5, 2.0)], "a", delta=0.1)
    rows = {r.section_id: (r.start, r.end) for r in cm.rows}
    assert rows["a"] == (0.0, 1.1)
    assert rows["b"] == (1.6, 2.1)
