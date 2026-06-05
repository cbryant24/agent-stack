from __future__ import annotations

import pytest
from pydantic import ValidationError

from voiceover_direction.constants import (
    MEMORY_TYPE_DIRECTION_LESSON,
    MEMORY_TYPE_TAKE,
    REACTION_PENDING,
    STATUS_COMPLETE,
    STATUS_PENDING,
)
from voiceover_direction.models import (
    CharacterUsage,
    DirectionLesson,
    Take,
    VoiceoverResult,
    VoiceProfile,
)


def _take(**overrides) -> Take:
    base = dict(
        text="Welcome back to the channel.",
        voice_id="voice-1",
        model="eleven_v3",
        section_id="intro",
        project_id="proj-1",
    )
    base.update(overrides)
    return Take(**base)


# ── Take ─────────────────────────────────────────────────────────────────────


def test_take_discriminator_and_defaults() -> None:
    take = _take()
    assert take.memory_type == MEMORY_TYPE_TAKE
    assert take.reaction == REACTION_PENDING
    assert take.status == STATUS_PENDING
    assert take.settings == {}
    assert take.emotion_tags == []


def test_take_root_sets_chain_root_to_self() -> None:
    take = _take()
    assert take.chain_root_id == take.entry_id
    assert take.parent_take_id is None


def test_take_child_keeps_parents_root_within_section() -> None:
    root = _take()
    child = _take(
        parent_take_id=root.entry_id,
        chain_root_id=root.chain_root_id,
        section_id=root.section_id,
    )
    assert child.chain_root_id == root.entry_id
    assert child.entry_id != root.entry_id


def test_take_chains_are_section_scoped() -> None:
    # A new section starts its own chain even when re-directing the "same" idea.
    intro_root = _take(section_id="intro")
    outro_root = _take(section_id="outro")
    assert intro_root.chain_root_id == intro_root.entry_id
    assert outro_root.chain_root_id == outro_root.entry_id
    assert intro_root.chain_root_id != outro_root.chain_root_id


def test_take_status_derived_from_reaction_in_payload() -> None:
    pending = _take().to_payload()
    assert pending["status"] == STATUS_PENDING

    reacted = _take(reaction="loved").to_payload()
    assert reacted["status"] == STATUS_COMPLETE


def test_take_payload_round_trip_preserves_settings_and_lineage() -> None:
    take = _take(
        settings={"stability": "creative"},
        emotion_tags=["[whispers]"],
        character_count=27,
        parent_take_id="parent-x",
        chain_root_id="root-x",
    )
    restored = Take.from_payload(take.to_payload())
    assert restored.settings == {"stability": "creative"}
    assert restored.emotion_tags == ["[whispers]"]
    assert restored.parent_take_id == "parent-x"
    assert restored.chain_root_id == "root-x"
    assert restored.text == take.text


def test_take_rating_bounds() -> None:
    _take(rating=1)
    _take(rating=5)
    with pytest.raises(ValidationError):
        _take(rating=0)
    with pytest.raises(ValidationError):
        _take(rating=6)


def test_take_from_payload_ignores_unknown_keys() -> None:
    payload = _take().to_payload()
    payload["some_future_field"] = "ignored"
    restored = Take.from_payload(payload)
    assert not hasattr(restored, "some_future_field")


# ── DirectionLesson ──────────────────────────────────────────────────────────


def test_direction_lesson_discriminator_and_round_trip() -> None:
    lesson = DirectionLesson(
        statement="Use a slower pace for emotional beats.",
        valence="positive",
        scope="pacing",
        confirmed=True,
    )
    assert lesson.memory_type == MEMORY_TYPE_DIRECTION_LESSON
    restored = DirectionLesson.from_payload(lesson.to_payload())
    assert restored.statement == lesson.statement
    assert restored.scope == "pacing"
    assert restored.confirmed is True


def test_direction_lesson_scope_default_and_validation() -> None:
    lesson = DirectionLesson(statement="x", valence="negative")
    assert lesson.scope == "general"
    with pytest.raises(ValidationError):
        DirectionLesson(statement="x", valence="sideways")  # type: ignore[arg-type]


# ── VoiceProfile ─────────────────────────────────────────────────────────────


def test_voice_profile_dict_round_trip() -> None:
    vp = VoiceProfile(
        voice_id="21m00Tcm",
        name="Rachel",
        category="stock",
        labels={"accent": "american"},
        description="calm narrator",
    )
    restored = VoiceProfile.from_dict(vp.to_dict())
    assert restored == vp


def test_voice_profile_category_validation() -> None:
    with pytest.raises(ValidationError):
        VoiceProfile(voice_id="v", name="n", category="premade")  # type: ignore[arg-type]


# ── CharacterUsage / VoiceoverResult ─────────────────────────────────────────


def test_character_usage_shape() -> None:
    usage = CharacterUsage(
        character_count=1000,
        character_limit=10000,
        characters_remaining=9000,
    )
    assert usage.characters_remaining == 9000
    assert usage.next_reset_unix is None


def test_voiceover_result_defaults() -> None:
    result = VoiceoverResult(take_id="t-1")
    assert result.audio_path is None
    assert result.character_cost == 0
    assert result.remaining_characters is None
