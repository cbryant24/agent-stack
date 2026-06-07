"""Integration: prove script.md is consumed by voiceover-direction unchanged.

This imports the real voiceover-direction parser (a test-only dependency) and
feeds it our serialized output, asserting the contract holds end to end:
sections split correctly, slugged ids match, inline emotion tags survive, and the
logline / music-hint / cut-trailer preamble is skipped rather than narrated.
"""
from __future__ import annotations

from concept_script.models import BriefSection, VideoBrief
from concept_script.serialize import to_script_md
from voiceover_direction.parser import parse_script_text


def _brief() -> VideoBrief:
    return VideoBrief(
        logline="Why your build is slow (and the one fix nobody mentions).",
        music_hint="tense synth, building",
        cut_trailer=["Deleted the false start about IDEs"],
        sections=[
            BriefSection(heading="Cold Open", prose="[urgent] Your build takes nine minutes. [pause] It shouldn't."),
            BriefSection(heading="The Real Cause", prose="[matter-of-fact] It isn't your machine."),
        ],
    )


def test_sections_split_and_ids_match() -> None:
    parsed = parse_script_text(to_script_md(_brief()))
    assert [s.heading for s in parsed.sections] == ["Cold Open", "The Real Cause"]
    # voiceover-direction derives ids by slugifying the heading.
    assert [s.section_id for s in parsed.sections] == ["cold-open", "the-real-cause"]


def test_inline_emotion_tags_survive() -> None:
    parsed = parse_script_text(to_script_md(_brief()))
    assert "[urgent]" in parsed.sections[0].body
    assert "[pause]" in parsed.sections[0].body


def test_preamble_not_narrated() -> None:
    parsed = parse_script_text(to_script_md(_brief()))
    bodies = " ".join(s.body for s in parsed.sections)
    headings = " ".join(s.heading for s in parsed.sections)
    # Logline, music hint, and cut trailer must not leak into any narrated body.
    assert "Why your build is slow" not in bodies
    assert "Music:" not in bodies
    assert "director note cuts applied" not in bodies
    assert "Deleted the false start" not in bodies
    assert "Music:" not in headings
