from __future__ import annotations

import pytest

from feedback_iteration.models import Span
from feedback_iteration.parser import parse_brief
from feedback_iteration.patcher import (
    Replace,
    apply_patches,
    set_checkbox,
    substitute_prose_boundaries,
)


def test_empty_patch_roundtrips(real_brief_text):
    assert apply_patches(real_brief_text, []) == real_brief_text


def test_multi_span_splice_is_order_independent():
    text = "0123456789"
    patches = [Replace(Span(2, 4), "AA"), Replace(Span(6, 8), "BB")]
    assert apply_patches(text, patches) == "01AA45BB89"
    assert apply_patches(text, list(reversed(patches))) == "01AA45BB89"


def test_overlapping_spans_raise():
    text = "0123456789"
    with pytest.raises(ValueError):
        apply_patches(text, [Replace(Span(2, 5), "X"), Replace(Span(4, 7), "Y")])


def test_single_step_rewrite_touches_only_that_step(real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    calm = pb.section_by_id("the-calm-underneath")
    s1 = next(s for s in calm.steps if s.number == 1)
    out = apply_patches(real_brief_text, [Replace(s1.text_span, "REPLACED")])
    # exactly the one step body changed; everything else byte-identical
    assert out.count("REPLACED") == 1
    assert len(out) == len(real_brief_text) - (s1.text_span.end - s1.text_span.start) + len("REPLACED")
    # a different section's steps are untouched
    assert "move the playhead to 58.000s" in out


def test_prose_substitution_retimes_changed_boundaries_only(real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    section = pb.section_by_id("the-calm-underneath")
    # pretend this section shifted: start 40.700→38.700, end 57.500→55.500
    subs = [(40.700, 38.700), (57.500, 55.500), (40.200, 38.200)]
    patches = substitute_prose_boundaries(section, subs)
    out = apply_patches(real_brief_text, patches)
    calm_text = out[section.block_span.start:section.block_span.end]
    assert "38.700s" in calm_text and "40.700s" not in calm_text
    assert "55.500s" in calm_text
    # the 0.500s gap token is never a boundary → never rewritten
    assert "0.500s gap" in calm_text
    # the unchanged intra-clip duration is left alone
    assert "duration = 16.800s" in calm_text


def test_checkbox_flip_touches_three_chars():
    text = (
        "---\nproject_id: t\nversion: 1\n---\n\n"
        '<a id="s"></a>\n### S — 00:00.000 → 00:05.000\n\n- [x] 1. done\n'
    )
    pb = parse_brief(text, "x")
    step = pb.sections[0].steps[0]
    out = apply_patches(text, [set_checkbox(step, False)])
    assert "- [ ] 1. done" in out
    assert len(out) == len(text)
