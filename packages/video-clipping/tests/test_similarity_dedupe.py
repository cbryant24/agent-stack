from __future__ import annotations

import pytest

from video_clipping.models import ClipDecision
from video_clipping.similarity.dedupe import dedupe

from tests.fakes import _pseudo_vector


def _dec(seg_id: str, summary: str) -> ClipDecision:
    return ClipDecision(
        segment_id=seg_id,
        action="include",
        refined_start=0.0,
        refined_end=10.0,
        theme_match=0.7,
        confidence=0.7,
        one_line_summary=summary,
    )


def test_dedupe_flips_duplicate_to_exclude() -> None:
    a = _dec("s1", "wide granite summit view")
    b = _dec("s2", "wildflowers on the ledge")
    c = _dec("s3", "wide granite summit view")  # identical to a
    vectors = [_pseudo_vector(d.one_line_summary) for d in (a, b, c)]

    kept, duped = dedupe([a, b, c], vectors)

    assert [d.segment_id for d in kept] == ["s1", "s2"]
    assert [d.segment_id for d in duped] == ["s3"]
    assert duped[0].action == "exclude"
    assert duped[0].exclude_reason == "duplicate_of_previous"


def test_dedupe_keeps_all_distinct() -> None:
    items = [_dec(f"s{i}", f"unique summary {i}") for i in range(4)]
    vectors = [_pseudo_vector(d.one_line_summary) for d in items]
    kept, duped = dedupe(items, vectors)
    assert len(kept) == 4
    assert duped == []


def test_dedupe_empty_input() -> None:
    kept, duped = dedupe([], [])
    assert kept == []
    assert duped == []


def test_dedupe_length_mismatch_raises() -> None:
    a = _dec("s1", "x")
    with pytest.raises(ValueError):
        dedupe([a], [])


def test_dedupe_preserves_ordering() -> None:
    # First-seen wins.
    a = _dec("s1", "same summary")
    b = _dec("s2", "same summary")
    vectors = [_pseudo_vector(d.one_line_summary) for d in (a, b)]
    kept, duped = dedupe([a, b], vectors)
    assert kept[0].segment_id == "s1"
    assert duped[0].segment_id == "s2"
