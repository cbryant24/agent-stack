from __future__ import annotations

import logging

from voiceover_direction.parser import parse_script, parse_script_text


def test_splits_each_heading_into_a_section() -> None:
    text = "# Intro\nHello there.\n\n# Body\nThe main point.\n\n# Outro\nGoodbye.\n"
    parsed = parse_script_text(text)
    assert [s.section_id for s in parsed.sections] == ["intro", "body", "outro"]
    assert parsed.sections[0].heading == "Intro"
    assert parsed.sections[0].body == "Hello there."


def test_section_id_is_a_deterministic_slug() -> None:
    text = "## A Warm, Friendly Welcome!\nBody.\n"
    parsed = parse_script_text(text)
    assert parsed.sections[0].section_id == "a-warm-friendly-welcome"


def test_parser_uses_shallowest_heading_level_present() -> None:
    # H2-based script splits at H2; deeper H3s stay inside the body.
    text = "## Section One\nIntro line.\n### A subpoint\ndetail\n\n## Section Two\nmore\n"
    parsed = parse_script_text(text)
    assert [s.section_id for s in parsed.sections] == ["section-one", "section-two"]
    assert "### A subpoint" in parsed.sections[0].body
    assert "detail" in parsed.sections[0].body


def test_duplicate_headings_get_unique_suffixes() -> None:
    text = "# Beat\nfirst\n\n# Beat\nsecond\n\n# Beat\nthird\n"
    parsed = parse_script_text(text)
    assert [s.section_id for s in parsed.sections] == ["beat", "beat-2", "beat-3"]


def test_inline_emotion_tags_pass_through_verbatim() -> None:
    text = "# Intro\n[whispers] Welcome back. [excited] Let's go!\n"
    parsed = parse_script_text(text)
    assert parsed.sections[0].body == "[whispers] Welcome back. [excited] Let's go!"


def test_preamble_is_skipped_with_warning(caplog) -> None:
    text = "Some narration with no heading yet.\n\n# Intro\nThe real intro.\n"
    with caplog.at_level(logging.WARNING):
        parsed = parse_script_text(text, source_path="script.md")
    assert [s.section_id for s in parsed.sections] == ["intro"]
    assert parsed.sections[0].body == "The real intro."
    assert any("before the first heading" in r.message for r in caplog.records)


def test_no_headings_warns_and_returns_empty(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        parsed = parse_script_text("Just prose, no headings at all.")
    assert parsed.sections == []
    assert any("no markdown headings" in r.message for r in caplog.records)


def test_empty_text_returns_empty_without_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        parsed = parse_script_text("   \n  ")
    assert parsed.sections == []
    assert caplog.records == []


def test_parse_script_reads_file(tmp_path) -> None:
    p = tmp_path / "script.md"
    p.write_text("# Intro\nHello.\n", encoding="utf-8")
    parsed = parse_script(p)
    assert parsed.source_path == str(p)
    assert parsed.sections[0].section_id == "intro"
