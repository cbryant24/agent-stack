from __future__ import annotations

from technique_research.models import (
    GapOutcome,
    TechniqueDomain,
    TechniqueFinding,
    TechniqueReport,
)


def _finding(**over) -> TechniqueFinding:
    base = dict(
        technique="Speed ramping",
        description="Vary playback speed across a clip for emphasis.",
        why_it_matters="Gives the edit punch on beat drops.",
        application_notes="Use Resolve retime controls on the cut.",
        toolset_fit="DaVinci Resolve free",
        upgrade_flag="Optical-flow retiming is smoother in Resolve Studio",
        source_refs=["tutorial-research run r1"],
        goal_context="a punchy AMV",
        domain_context="AMV",
        scope="editing",
    )
    base.update(over)
    return TechniqueFinding(**base)


def test_finding_roundtrips_through_memory_point_payload() -> None:
    f = _finding()
    mp = f.to_memory_point("run-123")

    # Stored in the text space under the right ownership.
    assert mp.source_type == "agent_summary"
    assert mp.processed_by_agent == "technique-research"
    assert mp.processed_in_run == "run-123"
    assert mp.text == "Speed ramping: Vary playback speed across a clip for emphasis."
    assert mp.domain_tags == ["AMV"]

    # The structured fields survive a metadata round-trip.
    f2 = TechniqueFinding.from_payload(mp.metadata)
    assert f2 == f


def test_from_payload_ignores_unknown_keys() -> None:
    payload = _finding().to_payload()
    payload["legacy_field"] = "ignored"
    f2 = TechniqueFinding.from_payload(payload)
    assert f2.technique == "Speed ramping"


def test_report_surfaces_upgrade_flag_only_when_present() -> None:
    with_flag = TechniqueReport(goal="g", techniques=[_finding()])
    without = TechniqueReport(goal="g", techniques=[_finding(upgrade_flag=None)])
    assert "Paid/Studio" in with_flag.to_markdown()
    assert "Paid/Studio" not in without.to_markdown()


def test_report_consumer_section_follows_scope() -> None:
    assert "## For the brief" in TechniqueReport(goal="g", scope="editing").to_markdown()
    assert "## For generation" in TechniqueReport(goal="g", scope="generation").to_markdown()


def test_preview_report_is_marked() -> None:
    rep = TechniqueReport(goal="g", preview=True)
    assert "Preview (`--plan-only`)" in rep.to_markdown()


def test_default_filename_is_slugged() -> None:
    rep = TechniqueReport(goal="A Video Like X!")
    assert rep.default_filename().endswith("-a-video-like-x.md")


def test_gap_outcome_renders_delegation() -> None:
    rep = TechniqueReport(
        goal="g",
        gaps=[GapOutcome(domain_name="Color", delegated=True, status="completed",
                         run_id="r9", items_processed=2)],
    )
    md = rep.to_markdown()
    assert "Color" in md and "delegated to tutorial-research" in md and "r9" in md


def test_domain_defaults() -> None:
    d = TechniqueDomain(name="Color grading", why_it_matters="look", search_query="color grading")
    assert d.priority == 1 and d.scope == "editing"
