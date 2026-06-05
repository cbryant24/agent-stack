from __future__ import annotations

from pathlib import Path

from voiceover_direction.directed_script import read_directed_script, write_directed_script
from voiceover_direction.models import DirectedScript, DirectedSection


def _script() -> DirectedScript:
    return DirectedScript(
        project_id="ep-12",
        domain="tech",
        source_path="ep-12.md",
        created_at="2026-06-03T00:00:00+00:00",
        sections=[
            DirectedSection(
                section_id="intro",
                heading="Intro",
                text="[whispers] Welcome back to the channel. [excited] Let's dive in.",
                voice_id="voice-1",
                model="eleven_v3",
                settings={"stability": "creative", "nested": {"a": 1}},
                notes="warm, slow",
            ),
            DirectedSection(
                section_id="main-point",
                heading="Main Point",
                text="Here's the thing nobody tells you. [pause]",
                voice_id=None,
                model="eleven_v3",
                settings={},
                notes="Suggested voice: calm female narrator",
            ),
        ],
    )


def test_round_trip_equals_original(tmp_path: Path) -> None:
    original = _script()
    path = tmp_path / "ep-12.directed.md"
    write_directed_script(original, path)
    restored = read_directed_script(path)
    assert restored == original


def test_round_trip_preserves_nested_settings_and_none_voice(tmp_path: Path) -> None:
    original = _script()
    path = tmp_path / "out.md"
    write_directed_script(original, path)
    restored = read_directed_script(path)
    assert restored.sections[0].settings == {"stability": "creative", "nested": {"a": 1}}
    assert restored.sections[1].voice_id is None


def test_inline_tags_preserved_in_prose(tmp_path: Path) -> None:
    original = _script()
    path = tmp_path / "out.md"
    write_directed_script(original, path)
    restored = read_directed_script(path)
    assert "[whispers]" in restored.sections[0].text
    assert "[pause]" in restored.sections[1].text


def test_headings_visible_metadata_invisible_in_source(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    write_directed_script(_script(), path)
    raw = path.read_text(encoding="utf-8")
    assert "## Intro" in raw
    assert "<!-- vo-meta:" in raw
    assert "<!-- vo-script:" in raw


def test_hand_edit_extra_whitespace_and_added_note_still_reads(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    write_directed_script(_script(), path)
    raw = path.read_text(encoding="utf-8")
    # Simulate a human tweak: extra blank lines around the prose.
    edited = raw.replace(
        "[whispers] Welcome back",
        "\n\n[whispers] Welcome back",
    )
    path.write_text(edited, encoding="utf-8")
    restored = read_directed_script(path)
    assert restored.sections[0].text.startswith("[whispers] Welcome back")
