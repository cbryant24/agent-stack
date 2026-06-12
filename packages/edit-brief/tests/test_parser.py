from __future__ import annotations

from edit_brief.parser import parse_script_text

SCRIPT = """A logline before the heading.

Music: minimal ambient piano, slow breathing room, no percussion

# Opening image
[quiet] There's a tab open. [pause] You know the one.

# The problem we don't name
We talk about focus like a skill.

# The problem we don't name
A duplicate heading body.
"""


def test_splits_on_h1_and_slugs():
    p = parse_script_text(SCRIPT)
    # Slug matches voiceover-direction's _slugify exactly (apostrophe → separator),
    # so the anchors line up with the section ids that agent already produced.
    assert [s.section_id for s in p.sections] == [
        "opening-image",
        "the-problem-we-don-t-name",
        "the-problem-we-don-t-name-2",  # duplicate gets -2 suffix
    ]
    assert p.sections[0].heading == "Opening image"


def test_captures_music_hint_from_preamble():
    p = parse_script_text(SCRIPT)
    assert p.music_hint == "minimal ambient piano, slow breathing room, no percussion"


def test_word_count_strips_inline_tags():
    p = parse_script_text(SCRIPT)
    # "There's a tab open. You know the one." → 8 words, [quiet]/[pause] removed
    assert p.sections[0].word_count == 8


def test_no_headings_returns_empty_sections_but_still_reads_hint():
    p = parse_script_text("Music: lofi beats\n\njust prose, no headings")
    assert p.sections == []
    assert p.music_hint == "lofi beats"


def test_no_music_hint_is_none():
    p = parse_script_text("# Only\nbody")
    assert p.music_hint is None
