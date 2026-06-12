from __future__ import annotations

import pytest

from feedback_iteration.parser import BriefParseError, _slugify, parse_brief, parse_timestamp

EXPECTED_ANCHORS = [
    "opening-image",
    "the-problem-we-don-t-name",
    "what-focus-actually-is",
    "the-calm-underneath",
    "a-different-way-to-work",
    "what-you-get-back",
    "close",
]


def test_slugify_matches_edit_brief_contract():
    assert _slugify("Opening image") == "opening-image"
    assert _slugify("The problem we don't name") == "the-problem-we-don-t-name"
    assert _slugify("What focus actually is") == "what-focus-actually-is"
    assert _slugify("Close") == "close"
    assert _slugify("!!!") == "section"


def test_parse_timestamp_roundtrips():
    assert parse_timestamp("00:00.000") == 0.0
    assert parse_timestamp("00:08.400") == 8.4
    assert parse_timestamp("01:13.700") == 73.7
    assert parse_timestamp("40.700s") == 40.7


def test_parses_real_artifact_structure(real_brief_text):
    pb = parse_brief(real_brief_text, "script-draft.edit-brief.md")
    assert pb.project_id == "script-draft"
    assert pb.frontmatter.version == 1
    assert [s.section_id for s in pb.sections] == EXPECTED_ANCHORS
    assert [r.section_id for r in pb.timeline_rows] == EXPECTED_ANCHORS
    # The anchors round-trip the slugify contract against the headings.
    for s in pb.sections:
        assert _slugify(s.heading_text) == s.section_id
    assert pb.version_log_span is None  # the real artifact has no version log yet


def test_section_spans_slice_back_to_source(real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    calm = pb.section_by_id("the-calm-underneath")
    assert calm is not None
    # heading timespan slices to the exact " — start → end" suffix
    assert calm.start_sec == 40.7
    assert calm.end_sec == 57.5
    assert real_brief_text[calm.heading_timespan.start:calm.heading_timespan.end] == " — 00:40.700 → 00:57.500"
    # step text spans slice back to the step body verbatim
    s8 = next(s for s in calm.steps if s.number == 8)
    assert real_brief_text[s8.text_span.start:s8.text_span.end] == s8.text
    assert real_brief_text[s8.line_span.start:s8.line_span.end].startswith("- [ ] 8.")
    assert s8.checked is False
    # notations are captured and separated from steps
    assert any("Studio-only" in n.text for n in calm.notations)


def test_timeline_cell_spans(real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    row = pb.row_by_id("what-you-get-back")
    assert row is not None
    assert real_brief_text[row.start_span.start:row.start_span.end] == "01:13.700"
    assert real_brief_text[row.end_span.start:row.end_span.end] == "01:28.500"
    assert row.start_sec == 73.7


def test_checkbox_span_and_checked_state():
    text = (
        "---\nproject_id: t\nversion: 2\n---\n\n"
        '<a id="s"></a>\n### S — 00:00.000 → 00:05.000\n\n'
        "- [x] 1. done step\n- [ ] 2. todo step\n"
    )
    pb = parse_brief(text, "x")
    sec = pb.sections[0]
    assert [s.checked for s in sec.steps] == [True, False]
    box = sec.steps[0].checkbox_span
    assert text[box.start:box.end] == "[x]"
    assert pb.frontmatter.version == 2


def test_missing_frontmatter_raises():
    with pytest.raises(BriefParseError):
        parse_brief("# no frontmatter here\n", "x")
