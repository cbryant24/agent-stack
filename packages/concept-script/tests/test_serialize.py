from __future__ import annotations

from concept_script.models import BriefSection, VideoBrief
from concept_script.serialize import from_script_md, to_script_md


def _brief(**kw) -> VideoBrief:
    defaults = dict(
        logline="A short film about why deadlines lie.",
        sections=[
            BriefSection(heading="Intro", prose="[reflective] Here's the thing. [pause] Nobody admits it."),
            BriefSection(heading="The Turn", prose="[building] But then it clicks."),
        ],
    )
    defaults.update(kw)
    return VideoBrief(**defaults)


def test_logline_and_sections_render() -> None:
    text = to_script_md(_brief())
    assert text.startswith("A short film about why deadlines lie.")
    assert "# Intro" in text
    assert "# The Turn" in text
    assert "[reflective]" in text  # inline emotion tags preserved verbatim


def test_logline_precedes_first_heading() -> None:
    # The logline must live in the preamble so the voiceover parser skips it.
    text = to_script_md(_brief())
    assert text.index("A short film") < text.index("# Intro")


def test_music_hint_in_preamble() -> None:
    text = to_script_md(_brief(music_hint="warm lo-fi, sparse piano"))
    assert "Music: warm lo-fi, sparse piano" in text
    assert text.index("Music:") < text.index("# Intro")


def test_no_music_hint_omits_line() -> None:
    text = to_script_md(_brief(music_hint=None))
    assert "Music:" not in text


def test_no_cut_trailer_omits_block() -> None:
    # Absent when no director note fired (default _brief has no cuts).
    text = to_script_md(_brief())
    assert "director note cuts applied" not in text


def test_cut_trailer_in_preamble() -> None:
    text = to_script_md(_brief(cut_trailer=["Deleted the closing pricing tangent"]))
    assert "director note cuts applied" in text
    assert "- Deleted the closing pricing tangent" in text
    # Must precede the first heading so it is not narrated.
    assert text.index("director note cuts applied") < text.index("# Intro")


def test_round_trip() -> None:
    original = _brief(music_hint="warm lo-fi", cut_trailer=["Cut A", "Cut B"])
    recovered = from_script_md(to_script_md(original))
    assert recovered.logline == original.logline
    assert recovered.music_hint == original.music_hint
    assert recovered.cut_trailer == original.cut_trailer
    assert [s.heading for s in recovered.sections] == [s.heading for s in original.sections]
    assert [s.prose for s in recovered.sections] == [s.prose for s in original.sections]
