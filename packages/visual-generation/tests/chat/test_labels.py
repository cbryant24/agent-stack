from __future__ import annotations

import pytest

from visual_generation.chat.labels import LabelResolver
from visual_generation.models import VisualGeneration


def gens(n: int) -> list[VisualGeneration]:
    return [
        VisualGeneration(caption=f"c{i}", created_at=f"2026-01-01T00:00:{i:02d}+00:00") for i in range(1, n + 1)
    ]


@pytest.mark.parametrize("label", ["attempt-02", "attempt-2", "Attempt 2", "ATTEMPT_02", "#2", "  attempt-02  "])
def test_attempt_spellings_resolve_to_the_same_generation(label: str) -> None:
    g = gens(3)
    assert LabelResolver(g).resolve(label).gen_id == g[1].entry_id


def test_attempts_are_numbered_oldest_first_regardless_of_input_order() -> None:
    g = gens(3)
    r = LabelResolver(list(reversed(g)))
    assert r.resolve("attempt-1").gen_id == g[0].entry_id
    assert r.resolve("latest").gen_id == g[2].entry_id and r.resolve("last").gen_id == g[2].entry_id


def test_out_of_range_and_zero_are_unresolved_with_a_reason() -> None:
    r = LabelResolver(gens(3))
    for label in ("attempt-9", "attempt-0", "#0"):
        res = r.resolve(label)
        assert res.gen_id is None and "3 attempt(s)" in res.reason


def test_full_id_and_unique_prefix() -> None:
    g = gens(3)
    r = LabelResolver(g)
    assert r.resolve(g[0].entry_id).gen_id == g[0].entry_id
    assert r.resolve(g[1].entry_id[:8]).gen_id == g[1].entry_id
    assert r.resolve(g[1].entry_id[:8].upper()).gen_id == g[1].entry_id


def test_short_prefix_is_not_guessed() -> None:
    g = gens(3)
    res = LabelResolver(g).resolve(g[0].entry_id[:5])
    assert res.gen_id is None and "not an attempt label" in res.reason


def test_ambiguous_prefix_is_not_guessed() -> None:
    a = VisualGeneration(caption="a", entry_id="abcdef01-0000-0000-0000-000000000001")
    b = VisualGeneration(caption="b", entry_id="abcdef01-0000-0000-0000-000000000002")
    res = LabelResolver([a, b]).resolve("abcdef01")
    assert res.gen_id is None and "matches 2" in res.reason


@pytest.mark.parametrize("label", ["", "   ", None, "the red one", "attempt-", "attempt-x"])
def test_junk_never_resolves(label: str | None) -> None:
    assert LabelResolver(gens(3)).resolve(label).gen_id is None


def test_latest_with_no_generations() -> None:
    res = LabelResolver([]).resolve("latest")
    assert res.gen_id is None and "no generations" in res.reason


def test_display_and_name_of() -> None:
    g = gens(12)
    r = LabelResolver(g)
    assert r.name_of(g[6].entry_id) == "attempt-07"
    assert r.display(g[6].entry_id) == f"attempt-07 ({g[6].entry_id[:8]})"
    assert r.name_of("not-in-project") is None
    assert r.display("not-in-project-xyz") == "not-in-p"
