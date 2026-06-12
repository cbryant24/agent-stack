from __future__ import annotations

from edit_brief.brief import assemble_brief, build_structural_notations, render_brief
from edit_brief.models import (
    BeatGrid,
    BeatProposal,
    DiscoveredInputs,
    DiscoveredMusic,
    DiscoveredVOTake,
    SectionSteps,
    TimelineRow,
)
from edit_brief.retrieval import Finding, RetrievedContext

ROWS = [
    TimelineRow(section_id="intro", heading="Intro", start_sec=0.0, end_sec=3.0,
                vo_file="intro.mp3", timing_source="vo"),
    TimelineRow(section_id="outro", heading="Outro", start_sec=3.5, end_sec=8.5,
                timing_source="estimate"),
]


def _inputs(**kw):
    base = dict(project_id="proj", vo_takes=[], music=DiscoveredMusic(), assets=[])
    base.update(kw)
    return DiscoveredInputs(**base)


def test_notation_all_estimates_names_voiceover():
    rows = [TimelineRow(section_id="a", heading="A", start_sec=0, end_sec=4, timing_source="estimate")]
    notes = build_structural_notations(_inputs(), rows, None, RetrievedContext())
    assert any("ALL section timestamps are word-count ESTIMATES" in n for n in notes)


def test_notation_some_estimates_lists_sections():
    notes = build_structural_notations(_inputs(), ROWS, None, RetrievedContext())
    assert any("their timestamps are estimates: outro" in n for n in notes)


def test_notation_no_bpm_and_matched_bpm():
    no_bpm = build_structural_notations(_inputs(), ROWS, None, RetrievedContext(findings=[Finding("x", "y")]))
    assert any("No BPM available" in n for n in no_bpm)

    matched = build_structural_notations(
        _inputs(music=DiscoveredMusic(file="/m.wav", bpm=90, bpm_source="matched", matched_title="Calm")),
        ROWS,
        BeatGrid(bpm=90, beat_sec=0.667, bar_sec=2.667),
        RetrievedContext(findings=[Finding("x", "y")]),
    )
    assert any("is a PROPOSAL matched from music-curation" in n and "Calm" in n for n in matched)


def test_notation_no_findings_and_ambiguous_takes():
    inputs = _inputs(vo_takes=[DiscoveredVOTake(section_id="intro", ambiguous=True)])
    notes = build_structural_notations(inputs, ROWS, None, RetrievedContext())
    assert any("No technique findings retrieved" in n for n in notes)
    assert any("Multiple positively-reacted VO takes" in n and "intro" in n for n in notes)


def test_render_has_frontmatter_anchors_and_checkboxes():
    grid = BeatGrid(bpm=120, beat_sec=0.5, bar_sec=2.0,
                    boundary_proposals=[BeatProposal(section_id="outro", boundary_sec=3.5,
                                                     nearest_beat_sec=3.5, nearest_bar_sec=4.0)])
    sections = [
        SectionSteps(section_id="intro", heading="Intro", steps=["place intro.mp3 at 0.0s"]),
        SectionSteps(section_id="outro", heading="Outro", steps=["cut on beat"], notations=["estimate"]),
    ]
    brief = assemble_brief(
        "proj", "/s/script.md",
        _inputs(music=DiscoveredMusic(file="/m.wav", duration_sec=30.0, bpm=120, bpm_source="flag")),
        ROWS, grid, sections, RetrievedContext(findings=[Finding("x", "y")]), [],
    )
    md = render_brief(brief)
    assert md.startswith("---\nproject_id: proj")
    assert "version: 1" in md
    assert "bpm: 120 (flag)" in md
    assert '<a id="intro"></a>' in md          # stable anchor
    assert "(#intro)" in md                    # timeline links to the anchor
    assert "- [ ] place intro.mp3 at 0.0s" in md
    assert "BPM **120**" in md
    assert "> ⚠ estimate" in md                # per-section notation
