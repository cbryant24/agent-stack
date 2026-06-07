from __future__ import annotations

from concept_script.models import BriefSection, ConceptResult, VideoBrief


def test_videobrief_defaults() -> None:
    brief = VideoBrief(logline="x")
    assert brief.sections == []
    assert brief.music_hint is None
    assert brief.cut_trailer == []


def test_briefsection_fields() -> None:
    s = BriefSection(heading="Intro", prose="[calm] hi")
    assert s.heading == "Intro"
    assert s.prose == "[calm] hi"


def test_conceptresult_roundtrips_brief() -> None:
    brief = VideoBrief(logline="x", sections=[BriefSection(heading="A", prose="p")])
    result = ConceptResult(
        brief=brief,
        run_id="r1",
        status="completed",
        cost_usd=0.0,
        wall_time_sec=1.0,
    )
    assert result.brief.sections[0].heading == "A"
    assert result.script_path is None
