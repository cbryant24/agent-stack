from __future__ import annotations

import pytest
from pydantic import ValidationError

from music_curation.constants import (
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TASTE,
    MEMORY_TYPE_TEMPLATE,
    REACTION_DISLIKED,
    REACTION_LIKED,
    REACTION_LOVED,
    REACTION_PENDING,
    REACTION_PROMPT_FAILED,
    STATUS_COMPLETE,
    STATUS_PENDING,
    STYLE_FIELD_MAX_CHARS,
)
from music_curation.models import (
    Generation,
    MusicResult,
    SoundReference,
    SunoPrompt,
    TasteLesson,
    Template,
    TastePendingDraft,
)


class TestGeneration:
    def test_defaults(self):
        gen = Generation(session_id="s1", style_field="lo-fi, jazz, 80 BPM")
        assert gen.memory_type == MEMORY_TYPE_GENERATION
        assert gen.reaction == REACTION_PENDING
        assert gen.status == STATUS_PENDING
        assert gen.chain_root_id == gen.entry_id
        assert gen.parent_id is None

    def test_chain_root_id_self_when_no_parent(self):
        gen = Generation(session_id="s1", style_field="lo-fi, jazz")
        assert gen.chain_root_id == gen.entry_id

    def test_chain_root_id_explicit(self):
        gen = Generation(session_id="s1", style_field="lo-fi", chain_root_id="parent-uuid")
        assert gen.chain_root_id == "parent-uuid"

    def test_style_field_too_long_raises(self):
        with pytest.raises(ValidationError):
            Generation(session_id="s1", style_field="x" * (STYLE_FIELD_MAX_CHARS + 1))

    def test_style_field_at_limit_ok(self):
        gen = Generation(session_id="s1", style_field="a" * STYLE_FIELD_MAX_CHARS)
        assert len(gen.style_field) == STYLE_FIELD_MAX_CHARS

    def test_to_payload_roundtrip(self):
        gen = Generation(
            session_id="sess",
            style_field="phonk, 135 BPM, heavy 808",
            reaction=REACTION_LOVED,
            bpm=135,
            language="French",
            lyrics_field="[Hook]\nWe outside",
        )
        payload = gen.to_payload()
        assert payload["memory_type"] == MEMORY_TYPE_GENERATION
        assert payload["reaction"] == REACTION_LOVED
        assert payload["status"] == STATUS_COMPLETE
        assert payload["bpm"] == 135
        assert payload["language"] == "French"

    def test_to_payload_pending_status(self):
        gen = Generation(session_id="s", style_field="lo-fi")
        payload = gen.to_payload()
        assert payload["status"] == STATUS_PENDING

    def test_from_payload(self):
        gen = Generation(session_id="sess", style_field="trap, 140 BPM", reaction=REACTION_LOVED)
        payload = gen.to_payload()
        restored = Generation.from_payload(payload)
        assert restored.entry_id == gen.entry_id
        assert restored.reaction == REACTION_LOVED
        assert restored.session_id == "sess"

    def test_entry_id_stable(self):
        gen = Generation(session_id="s", style_field="lo-fi")
        assert gen.entry_id == gen.chain_root_id  # self-reference on creation

    def test_with_parent(self):
        parent = Generation(session_id="s", style_field="lo-fi, 80 BPM")
        child = Generation(
            session_id="s",
            style_field="lo-fi, 75 BPM",
            parent_id=parent.entry_id,
            chain_root_id=parent.entry_id,
        )
        assert child.parent_id == parent.entry_id
        assert child.chain_root_id == parent.entry_id

    # ── Change 3: rating field ──
    def test_rating_defaults_none(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz")
        assert gen.rating is None

    def test_rating_valid_range(self):
        for r in (1, 2, 3, 4, 5):
            gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz", rating=r)
            assert gen.rating == r

    def test_rating_below_range_raises(self):
        with pytest.raises(ValidationError):
            Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz", rating=0)

    def test_rating_above_range_raises(self):
        with pytest.raises(ValidationError):
            Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz", rating=6)

    # ── Change 4: notes vs context fields ──
    def test_notes_and_context_default_none(self):
        gen = Generation(session_id="s", style_field="lo-fi, 80 BPM, jazz")
        assert gen.notes is None
        assert gen.context is None

    def test_notes_and_context_settable_together(self):
        gen = Generation(
            session_id="s", style_field="lo-fi, 80 BPM, jazz",
            notes="slow it down", context="the cowbell is exactly right",
        )
        assert gen.notes == "slow it down"
        assert gen.context == "the cowbell is exactly right"

    def test_legacy_user_note_maps_to_notes_on_read(self):
        # Back-compat for the user_note → notes rename.
        payload = {"session_id": "s", "style_field": "lo-fi, 80 BPM, jazz", "user_note": "legacy text"}
        gen = Generation.from_payload(payload)
        assert gen.notes == "legacy text"


class TestReactionVocabulary:
    """Change 1 + 2: liked replaces approved; disliked and prompt_failed are distinct."""

    def test_disliked_and_prompt_failed_are_distinct(self):
        assert REACTION_DISLIKED != REACTION_PROMPT_FAILED
        assert REACTION_DISLIKED == "disliked"
        assert REACTION_PROMPT_FAILED == "prompt_failed"

    def test_liked_value(self):
        assert REACTION_LIKED == "liked"

    def test_both_failure_modes_storable_and_not_interchangeable(self):
        g_disliked = Generation(session_id="s", style_field="trap, 140 BPM, 808", reaction=REACTION_DISLIKED)
        g_failed = Generation(session_id="s", style_field="trap, 140 BPM, 808", reaction=REACTION_PROMPT_FAILED)
        assert g_disliked.to_payload()["reaction"] == "disliked"
        assert g_failed.to_payload()["reaction"] == "prompt_failed"
        assert g_disliked.reaction != g_failed.reaction


class TestTemplate:
    def test_defaults(self):
        tmpl = Template(name="Lo-fi base", descriptor="mellow lo-fi", style_pattern="lo-fi, [BPM] BPM")
        assert tmpl.memory_type == MEMORY_TYPE_TEMPLATE
        assert tmpl.swap_variables == []

    def test_to_from_payload(self):
        tmpl = Template(
            name="Space template",
            descriptor="solo synthesizer space",
            style_pattern="space psychedelic, [BPM] BPM, solo synthesizer",
            swap_variables=["BPM"],
        )
        payload = tmpl.to_payload()
        restored = Template.from_payload(payload)
        assert restored.name == "Space template"
        assert restored.swap_variables == ["BPM"]


class TestTasteLesson:
    def test_defaults(self):
        lesson = TasteLesson(statement="User loves heavy bass", valence="positive", scope="instrumentation")
        assert lesson.memory_type == MEMORY_TYPE_TASTE
        assert lesson.confirmed is False

    def test_confirmed_flag(self):
        lesson = TasteLesson(statement="test", valence="negative", scope="genre", confirmed=True)
        assert lesson.confirmed is True

    def test_to_from_payload(self):
        lesson = TasteLesson(
            statement="Memphis cowbell is essential for phonk",
            valence="positive",
            scope="production",
            confirmed=True,
        )
        payload = lesson.to_payload()
        restored = TasteLesson.from_payload(payload)
        assert restored.statement == lesson.statement
        assert restored.confirmed is True


class TestSoundReference:
    def test_defaults(self):
        ref = SoundReference(description="heavy crushing 808 with Memphis phonk vibe")
        assert ref.qualities == []
        assert ref.linked_generation_ids == []

    def test_to_from_payload(self):
        ref = SoundReference(
            description="sparse flute loop over empty space",
            source_track="Mask Off",
            qualities=["sparse", "flute", "Memphis"],
        )
        payload = ref.to_payload()
        restored = SoundReference.from_payload(payload)
        assert restored.source_track == "Mask Off"
        assert restored.qualities == ["sparse", "flute", "Memphis"]


class TestSunoPrompt:
    def test_truncates_long_style(self):
        long_style = "lo-fi, " + ("jazz, " * 200)
        prompt = SunoPrompt(style_field=long_style)
        assert len(prompt.style_field) == STYLE_FIELD_MAX_CHARS

    def test_optional_lyrics(self):
        prompt = SunoPrompt(style_field="trap, 140 BPM")
        assert prompt.lyrics_field is None

    def test_with_lyrics(self):
        prompt = SunoPrompt(style_field="phonk", lyrics_field="[Hook]\nWe outside")
        assert prompt.lyrics_field.startswith("[Hook]")


class TestMusicResult:
    def test_construction(self):
        result = MusicResult(
            prompts=[SunoPrompt(style_field="lo-fi, 80 BPM")],
            theory_reasoning="This works because...",
            run_id="test-run",
            status="completed",
            cost_usd=0.05,
            items_processed=1,
            wall_time_sec=12.3,
        )
        assert result.status == "completed"
        assert len(result.prompts) == 1
        assert result.cross_references == []


class TestTastePendingDraft:
    def test_roundtrip(self):
        draft = TastePendingDraft(
            statement="French phonk vocals hit differently",
            valence="positive",
            scope="vocal",
            session_id="suno-prompts-five",
            source_path="/path/to/file.md",
        )
        d = draft.to_dict()
        restored = TastePendingDraft.from_dict(d)
        assert restored.statement == draft.statement
        assert restored.draft_id == draft.draft_id
