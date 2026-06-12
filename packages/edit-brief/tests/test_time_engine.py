"""Exhaustive, deterministic tests of the pure time engine — no mocks, no I/O.

This is the load-bearing competence: all timing is computed here, never by the
LLM. Every arithmetic branch is pinned.
"""
from __future__ import annotations

import pytest

from edit_brief.time_engine import build_beat_grid, section_timestamps

S = [("a", "A"), ("b", "B"), ("c", "C")]


def test_all_vo_durations_cumulate_with_gap():
    rows = section_timestamps(
        S, durations=[3.0, 5.0, 2.0], word_counts=[0, 0, 0], gap=0.5, words_per_sec=2.5
    )
    assert [(r.start_sec, r.end_sec) for r in rows] == [
        (0.0, 3.0),       # first: no leading gap
        (3.5, 8.5),       # +0.5 gap, then 5.0
        (9.0, 11.0),      # +0.5 gap, then 2.0
    ]
    assert all(r.timing_source == "vo" for r in rows)


def test_zero_gap_is_back_to_back():
    rows = section_timestamps(
        S, durations=[3.0, 5.0, 2.0], word_counts=[0, 0, 0], gap=0.0, words_per_sec=2.5
    )
    assert [(r.start_sec, r.end_sec) for r in rows] == [
        (0.0, 3.0), (3.0, 8.0), (8.0, 10.0)
    ]


def test_missing_duration_falls_back_to_word_estimate():
    rows = section_timestamps(
        [("a", "A")], durations=[None], word_counts=[25], gap=0.5, words_per_sec=2.5
    )
    assert rows[0].timing_source == "estimate"
    assert rows[0].end_sec == 10.0  # 25 words / 2.5 wps


def test_mixed_vo_and_estimate():
    rows = section_timestamps(
        S, durations=[3.0, None, 2.0], word_counts=[0, 10, 0], gap=1.0, words_per_sec=2.5
    )
    assert rows[0].timing_source == "vo"
    assert rows[1].timing_source == "estimate"
    assert rows[2].timing_source == "vo"
    # section b: start 4.0 (3 + 1 gap), length 10/2.5=4.0 → end 8.0
    assert (rows[1].start_sec, rows[1].end_sec) == (4.0, 8.0)
    # section c: start 9.0 (8 + 1 gap), length 2.0 → end 11.0
    assert (rows[2].start_sec, rows[2].end_sec) == (9.0, 11.0)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        section_timestamps(S, durations=[1.0], word_counts=[0, 0, 0], gap=0.5, words_per_sec=2.5)


def test_nonpositive_words_per_sec_raises():
    with pytest.raises(ValueError):
        section_timestamps(
            [("a", "A")], durations=[None], word_counts=[5], gap=0.0, words_per_sec=0
        )


# ── beat grid ─────────────────────────────────────────────────────────────────


def test_beat_grid_math_120bpm():
    grid = build_beat_grid(120, [("a", 0.0), ("b", 3.4)])
    assert grid is not None
    assert grid.beat_sec == 0.5          # 60/120
    assert grid.bar_sec == 2.0           # 4 beats
    props = {p.section_id: p for p in grid.boundary_proposals}
    # boundary 3.4 → nearest beat = round(3.4/0.5)*0.5 = 3.5 ; nearest bar = round(3.4/2)*2 = 4.0
    assert props["b"].nearest_beat_sec == 3.5
    assert props["b"].nearest_bar_sec == 4.0


def test_beat_grid_none_without_bpm():
    assert build_beat_grid(None, [("a", 0.0)]) is None
    assert build_beat_grid(0, [("a", 0.0)]) is None


def test_beat_grid_drops_boundaries_past_track_end_and_notes_it():
    grid = build_beat_grid(120, [("a", 0.0), ("b", 50.0)], track_duration=30.0)
    assert grid is not None
    ids = [p.section_id for p in grid.boundary_proposals]
    assert ids == ["a"]                  # b is past the 30s track end
    assert grid.note is not None and "after the music track ends" in grid.note
