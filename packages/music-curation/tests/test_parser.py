from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from music_curation.constants import (
    REACTION_LIKED,
    REACTION_DISLIKED,
    REACTION_LIKED_WITH_CHANGES,
    REACTION_LOST_TRACK,
    REACTION_LOVED,
)
from music_curation.parser import (
    _extract_bpm,
    _extract_language,
    _infer_reaction,
    _is_valid_suno_style,
    parse_file,
    parse_session_file,
)


# ── Unit tests for helper functions ──────────────────────────────────────────

class TestExtractBpm:
    def test_simple_bpm(self):
        assert _extract_bpm("lo-fi, 80 BPM, jazz") == 80

    def test_range_bpm(self):
        assert _extract_bpm("phonk, 80-90 BPM") == 85

    def test_dash_bpm(self):
        assert _extract_bpm("trap, 135–140 BPM, heavy") == 137

    def test_no_bpm(self):
        assert _extract_bpm("cinematic, strings, emotional") is None

    def test_bpm_case_insensitive(self):
        assert _extract_bpm("lo-fi, 72 bpm") == 72


class TestExtractLanguage:
    def test_french(self):
        assert _extract_language("lo-fi, French female vocals, 80 BPM") == "French"

    def test_japanese(self):
        assert _extract_language("phonk, Japanese female vocals, Tokyo night vibes") == "Japanese"

    def test_none(self):
        assert _extract_language("lo-fi, trap, heavy bass") is None

    def test_multilingual(self):
        # First matching language pattern wins (order-dependent)
        result = _extract_language("multilingual, French and Japanese vocals")
        assert result in ("French", "Japanese", "Multilingual")


class TestInferReaction:
    def test_loved(self):
        assert _infer_reaction("USER LOVED THIS — great track") == REACTION_LOVED

    def test_disliked_emoji(self):
        assert _infer_reaction("❌ User didn't like") == REACTION_DISLIKED

    def test_liked_with_changes_emoji(self):
        assert _infer_reaction("⚠️ liked but wanted adjustments") == REACTION_LIKED_WITH_CHANGES

    def test_approved_recommended(self):
        assert _infer_reaction("(Recommended) good version") == REACTION_LIKED

    def test_approved_status_field(self):
        assert _infer_reaction("**Status:** ✅ User liked") == REACTION_LIKED

    def test_loved_before_disliked(self):
        # When both appear, loved wins (checked first)
        assert _infer_reaction("USER LOVED THIS ❌") == REACTION_LOVED

    def test_default_lost_track(self):
        assert _infer_reaction("Some neutral description") == REACTION_LOST_TRACK

    def test_section_framing_overrides_lost_track(self, tmp_path):
        # Section-level framing overrides is applied in _collect_prompts_from_section,
        # not directly in _infer_reaction. Test at the session parse level.
        md = tmp_path / "framed.md"
        md.write_text(textwrap.dedent("""
            # Session

            ## Final Approved Prompts

            ### Neutral Prompt
            ```
            Lo-fi hip-hop, 80 BPM, jazz piano, vinyl crackle, mellow drums
            ```
        """))
        from music_curation.parser import parse_session_file
        session = parse_session_file(md)
        assert len(session.prompts) == 1
        assert session.prompts[0].reaction == REACTION_LIKED

    def test_liked_inline_parenthetical(self):
        assert _infer_reaction("Floating & Cosmic (Variation 1 — liked)") == REACTION_LIKED

    def test_liked_with_changes_not_overridden_by_liked(self):
        assert _infer_reaction("liked but too slow") == REACTION_LIKED_WITH_CHANGES


class TestIsValidSunoStyle:
    def test_valid_style(self):
        assert _is_valid_suno_style("lo-fi hip-hop, 80 BPM, jazz piano, vinyl crackle")

    def test_rejects_template_pattern(self):
        assert not _is_valid_suno_style("[Genre Tags] [BPM] [Instrumentation] [Mood]")

    def test_rejects_workflow_description(self):
        assert not _is_valid_suno_style("Base Version → Sad Version → Lo-Fi Variant")

    def test_rejects_empty(self):
        assert not _is_valid_suno_style("")

    def test_rejects_no_commas_no_bpm(self):
        assert not _is_valid_suno_style("just some text without descriptors")

    def test_valid_with_bpm_no_commas(self):
        assert _is_valid_suno_style("lo-fi 80 BPM chill")

    def test_rejects_high_variable_ratio(self):
        # >30% [Variable] slots
        assert not _is_valid_suno_style("[A] [B] [C] lo-fi")


# ── Integration tests against seed fixture files ──────────────────────────────

SEED_DIR = Path(__file__).parent.parent.parent.parent / "seed" / "music-curation"


def _seed_file(name: str) -> Path:
    return SEED_DIR / name


@pytest.mark.skipif(not SEED_DIR.exists(), reason="seed files not present")
class TestSeedFileOne:
    """suno-prompts-one.md — Iteration 1/2/3 chain with H2-level sub-fields."""

    def setup_method(self):
        self.session = parse_file(_seed_file("suno-prompts-one.md"))

    def test_extracts_three_prompts(self):
        assert len(self.session.prompts) == 3

    def test_iteration_names(self):
        names = [p.name for p in self.session.prompts]
        assert any("Hard Trap" in n for n in names)
        assert any("Southern" in n or "Atlanta" in n for n in names)
        assert any("Metro" in n or "Gothic" in n for n in names)

    def test_chain_parent_indices(self):
        prompts = self.session.prompts
        assert prompts[0].parent_index is None
        assert prompts[1].parent_index == 0
        assert prompts[2].parent_index == 1

    def test_iteration_three_approved(self):
        assert self.session.prompts[2].reaction == REACTION_LIKED

    def test_bpm_extracted(self):
        assert self.session.prompts[0].bpm == 140

    def test_has_suno_facts(self):
        assert len(self.session.suno_facts) > 0

    def test_parentheses_fact(self):
        statements = [f.statement for f in self.session.suno_facts]
        assert any("parenthes" in s.lower() for s in statements)


@pytest.mark.skipif(not SEED_DIR.exists(), reason="seed files not present")
class TestSeedFileFive:
    """suno-prompts-five.md — 10-prompt session with explicit ✅/❌/⚠️ reactions."""

    def setup_method(self):
        self.session = parse_file(_seed_file("suno-prompts-five.md"))

    def test_extracts_ten_prompts(self):
        assert len(self.session.prompts) == 10

    def test_first_two_disliked(self):
        assert self.session.prompts[0].reaction == REACTION_DISLIKED
        assert self.session.prompts[1].reaction == REACTION_DISLIKED

    def test_third_liked_with_changes(self):
        assert self.session.prompts[2].reaction == REACTION_LIKED_WITH_CHANGES

    def test_fourth_loved(self):
        assert self.session.prompts[3].reaction == REACTION_LOVED

    def test_prompt_ten_inherits_style(self):
        p10 = self.session.prompts[9]
        p9 = self.session.prompts[8]
        assert p10.style_field == p9.style_field

    def test_prompt_ten_has_lyrics(self):
        p10 = self.session.prompts[9]
        assert p10.lyrics_field is not None
        assert len(p10.lyrics_field) > 20

    def test_prompt_ten_parent_is_nine(self):
        p10 = self.session.prompts[9]
        assert p10.parent_index == 8

    def test_french_language_detected(self):
        french_prompts = [p for p in self.session.prompts if p.language == "French"]
        assert len(french_prompts) >= 1

    def test_japanese_language_detected(self):
        japanese_prompts = [p for p in self.session.prompts if p.language == "Japanese"]
        assert len(japanese_prompts) >= 1

    def test_suno_facts_extracted(self):
        assert len(self.session.suno_facts) >= 3

    def test_taste_lessons_extracted(self):
        assert len(self.session.taste_lessons) >= 1


@pytest.mark.skipif(not SEED_DIR.exists(), reason="seed files not present")
class TestSeedFileSeven:
    """suno-prompts-seven.md — H4-level prompts, reference collection."""

    def setup_method(self):
        self.session = parse_file(_seed_file("suno-prompts-seven.md"))

    def test_extracts_15_prompts(self):
        assert len(self.session.prompts) == 15

    def test_all_approved(self):
        reactions = {p.reaction for p in self.session.prompts}
        assert reactions == {REACTION_LIKED}

    def test_includes_nujabes_primary(self):
        names = [p.name for p in self.session.prompts]
        assert any("Primary" in n or "Samurai" in n for n in names)

    def test_includes_museum(self):
        names = [p.name for p in self.session.prompts]
        assert any("Museum" in n for n in names)

    def test_bpm_extracted_from_h4_prompts(self):
        bpms = [p.bpm for p in self.session.prompts if p.bpm is not None]
        assert len(bpms) >= 10


@pytest.mark.skipif(not SEED_DIR.exists(), reason="seed files not present")
class TestSeedFileThree:
    """suno-prompts-three.md — inline text reactions."""

    def setup_method(self):
        self.session = parse_file(_seed_file("suno-prompts-three.md"))

    def test_six_prompts(self):
        assert len(self.session.prompts) == 6

    def test_liked_maps_to_liked(self):
        # "(Variation 1 — liked)" → liked
        variation1 = next(p for p in self.session.prompts if "Variation 1" in p.name)
        assert variation1.reaction == REACTION_LIKED

    def test_liked_not_overall_maps_to_liked_with_changes(self):
        variation2 = next(p for p in self.session.prompts if "Variation 2" in p.name)
        assert variation2.reaction == REACTION_LIKED_WITH_CHANGES

    def test_too_slow_maps_to_liked_with_changes(self):
        variation3 = next(p for p in self.session.prompts if "Variation 3" in p.name)
        assert variation3.reaction == REACTION_LIKED_WITH_CHANGES

    def test_suno_facts_from_learnings(self):
        assert len(self.session.suno_facts) >= 5
        statements = [f.statement for f in self.session.suno_facts]
        assert any("Solo synthesizer" in s or "solo" in s.lower() for s in statements)


@pytest.mark.skipif(not SEED_DIR.exists(), reason="seed files not present")
class TestReadme:
    """AI-Music-Generation-README.md — taste + suno_facts + explicit templates."""

    def setup_method(self):
        self.session = parse_file(_seed_file("AI-Music-Generation-README.md"))

    def test_no_prompts(self):
        assert len(self.session.prompts) == 0

    def test_has_suno_facts(self):
        assert len(self.session.suno_facts) >= 3

    def test_has_explicit_taste_lessons(self):
        assert len(self.session.taste_lessons) >= 5
        assert all(t.is_explicit for t in self.session.taste_lessons)

    def test_has_explicit_templates(self):
        explicit = [t for t in self.session.templates if t.is_explicit]
        assert len(explicit) >= 3

    def test_templates_have_expected_names(self):
        names = [t.name for t in self.session.templates]
        # The README Quick Reference Prompts and Style Variation Templates are extracted
        assert any("Reference" in n or "Variation" in n or "Template" in n for n in names)


# ── Inline fixture tests (no seed files required) ────────────────────────────

def _make_md(content: str) -> Path:
    """Write inline markdown to a temp file for testing."""
    import tempfile
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    f.write(textwrap.dedent(content))
    f.close()
    return Path(f.name)


class TestInlineSessionParsing:
    def test_flat_code_block(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(textwrap.dedent("""
            # Test Session

            ## Version 1

            ```
            Lo-fi hip-hop, 80 BPM, jazz piano, vinyl crackle, tape saturation, chill vibes
            ```
        """))
        session = parse_session_file(md)
        assert len(session.prompts) == 1
        assert session.prompts[0].bpm == 80
        assert session.prompts[0].reaction == REACTION_LOST_TRACK

    def test_subfield_h3_layout(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(textwrap.dedent("""
            # Iteration Test

            ## Iteration 1 — Hard Style

            ### Style of Music
            ```
            Trap, 140 BPM, heavy 808 bass, dark atmosphere, street anthem energy
            ```

            ### Lyrics
            ```
            [Hook]
            We outside
            ```
        """))
        session = parse_session_file(md)
        assert len(session.prompts) == 1
        p = session.prompts[0]
        assert p.bpm == 140
        assert p.lyrics_field is not None
        assert "We outside" in p.lyrics_field

    def test_iteration_chain_detection(self, tmp_path):
        md = tmp_path / "iterations.md"
        md.write_text(textwrap.dedent("""
            # Session

            ## Iteration 1 — First

            ### Style of Music
            ```
            Lo-fi, 80 BPM, jazz piano, vinyl crackle, mellow drums
            ```

            ## Iteration 2 — Refined

            ### Style of Music
            ```
            Lo-fi, 75 BPM, muted jazz piano, heavy vinyl crackle, slow drums
            ```

            ## Iteration 3 — Final ✅ Recommended

            ### Style of Music
            ```
            Lo-fi, 72 BPM, detuned jazz piano, vinyl crackle, sparse drums
            ```
        """))
        session = parse_session_file(md)
        assert len(session.prompts) == 3
        assert session.prompts[0].parent_index is None
        assert session.prompts[1].parent_index == 0
        assert session.prompts[2].parent_index == 1
        assert session.prompts[2].reaction == REACTION_LIKED

    def test_h4_prompts(self, tmp_path):
        md = tmp_path / "h4.md"
        md.write_text(textwrap.dedent("""
            # Lo-Fi Collection

            ## Prompts Created

            ### 1. Sad Vibes

            #### Slow Version
            ```
            Lo-fi, 65 BPM, minor key, vinyl crackle, muted drums, sad atmosphere
            ```

            #### Melancholic Version
            ```
            Lo-fi, 60 BPM, suspended chords, tape hiss, hollow bass, grief mood
            ```
        """))
        session = parse_session_file(md)
        assert len(session.prompts) == 2
        assert all(p.reaction == REACTION_LIKED for p in session.prompts)

    def test_suno_fact_extraction(self, tmp_path):
        md = tmp_path / "learnings.md"
        md.write_text(textwrap.dedent("""
            # Session

            ## Prompts Created

            ```
            Lo-fi, 80 BPM, jazz piano, vinyl crackle, tape saturation
            ```

            ## Key Learnings

            - Suno tends to add drums even when mood keywords suggest stillness
            - Use "no drums" explicitly to prevent rhythm sections
            - Always include BPM for consistent tempo control
        """))
        session = parse_session_file(md)
        # Only bullets with explicit Suno triggers are classified as suno_facts
        assert len(session.suno_facts) >= 1
        statements = [f.statement for f in session.suno_facts]
        assert any("suno" in s.lower() or "drum" in s.lower() for s in statements)

    def test_template_pattern_not_extracted_as_prompt(self, tmp_path):
        md = tmp_path / "template.md"
        md.write_text(textwrap.dedent("""
            # Prompt Patterns

            ## Prompt Structure

            ```
            [Genre Tags] [Tempo/Feel] [Instrumentation] [Mood/Atmosphere] [Production Texture]
            ```
        """))
        session = parse_session_file(md)
        # Should be detected as template, not generation
        assert len(session.prompts) == 0

    def test_style_and_lyrics_together(self, tmp_path):
        md = tmp_path / "full.md"
        md.write_text(textwrap.dedent("""
            # Session

            ## Prompts Created

            ### Lo-Fi Phonk ✅ User liked

            **Style of Music:**
            ```
            Lo-fi phonk, 80 BPM, warm 808, Memphis cowbell, vinyl crackle, dusty texture
            ```

            **Lyrics:**
            ```
            [Instrumental Intro]
            [Vocal Hook]
            Lost in the night
            ```
        """))
        session = parse_session_file(md)
        assert len(session.prompts) == 1
        p = session.prompts[0]
        assert p.lyrics_field is not None
        assert "Lost in the night" in p.lyrics_field
        assert p.reaction == REACTION_LIKED
