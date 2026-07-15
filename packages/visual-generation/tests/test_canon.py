"""Tests for the project canon subject registry (visual_generation.canon)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_generation.canon import (
    ProjectCanon,
    canon_loras_for,
    scene_cast,
    subjects_matching,
)
from visual_generation.models import LoraRef

_LEGACY_LOCKED = "a young African American man with deep caramel-brown skin, long black yarn dreadlocks falling to the middle of his back"


def _seed_canon(base: Path, project: str = "celeste") -> ProjectCanon:
    store = ProjectCanon(project, base_dir=base)
    store.set_subject(
        aliases=["the narrator", "narrator", "@narrator"],
        id="narrator_v1",
        wardrobe="narrator_wardrobe_v1",
    )
    return store


def _seed_legacy_file(base: Path, project: str = "celeste") -> Path:
    """Hand-write a canon file in the pre-cleanup shape (locked/forbid present) —
    mirrors the real celeste-you-dangerous.json on disk."""
    path = base / f"{project}.json"
    path.write_text(
        json.dumps(
            {
                "subjects": [
                    {
                        "aliases": ["the narrator", "narrator", "@narrator"],
                        "locked": _LEGACY_LOCKED,
                        "forbid": ["short hair", "shoulder-length hair"],
                        "lora": {"name": "narrator-zimage.safetensors", "strength": 2.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


# ── JSON store round-trip ───────────────────────────────────────────────────────


def test_store_round_trip(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    subjects = store.load()
    assert len(subjects) == 1
    assert "the narrator" in subjects[0].aliases
    assert subjects[0].id == "narrator_v1"
    assert subjects[0].wardrobe == "narrator_wardrobe_v1"
    assert subjects[0].reference_pack is None

    # Upsert by primary alias replaces, doesn't duplicate.
    store.set_subject(aliases=["the narrator"], id="narrator_v2")
    subjects = store.load()
    assert len(subjects) == 1
    assert subjects[0].id == "narrator_v2"
    assert subjects[0].wardrobe is None  # full replace by design

    assert store.remove("the narrator") is True
    assert store.load() == []
    assert store.remove("the narrator") is False


def test_legacy_json_with_locked_and_forbid_loads_and_round_trips(tmp_path: Path) -> None:
    _seed_legacy_file(tmp_path)
    store = ProjectCanon("celeste", base_dir=tmp_path)
    subjects = store.load()
    assert len(subjects) == 1
    subj = subjects[0]
    # Not declared fields — but tolerated as extras and present in the dump.
    assert "locked" not in type(subj).model_fields
    assert subj.model_dump()["locked"] == _LEGACY_LOCKED
    assert subj.model_dump()["forbid"] == ["short hair", "shoulder-length hair"]
    assert subj.lora is not None and subj.lora.strength == 2.0
    # A rewrite keeps the legacy fields verbatim.
    store._write(subjects)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["subjects"][0]["locked"] == _LEGACY_LOCKED
    assert raw["subjects"][0]["forbid"] == ["short hair", "shoulder-length hair"]


def test_legacy_fields_survive_update_subject(tmp_path: Path) -> None:
    _seed_legacy_file(tmp_path)
    store = ProjectCanon("celeste", base_dir=tmp_path)
    store.update_subject("the narrator", wardrobe="narrator_wardrobe_v1")
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["subjects"][0]["locked"] == _LEGACY_LOCKED  # model_copy preserved extras
    assert raw["subjects"][0]["wardrobe"] == "narrator_wardrobe_v1"


def test_subjects_matching_resolves_selectors(tmp_path: Path) -> None:
    _seed_two_subjects(tmp_path)
    got = subjects_matching(["the waitress"], "celeste", base_dir=tmp_path)
    assert [s.aliases[0] for s in got] == ["Celeste"]
    assert subjects_matching(["nobody"], "celeste", base_dir=tmp_path) == []
    assert subjects_matching([], "celeste", base_dir=tmp_path) == []


# ── character LoRA (canon_loras_for) ─────────────────────────────────────────────


def _seed_canon_with_lora(base: Path, project: str = "celeste") -> ProjectCanon:
    store = ProjectCanon(project, base_dir=base)
    store.set_subject(
        aliases=["the narrator", "narrator", "@narrator"],
        id="narrator_v1",
        lora=LoraRef(name="celeste-narrator.safetensors", strength=0.8),
    )
    return store


def test_lora_round_trips_through_store(tmp_path: Path) -> None:
    _seed_canon_with_lora(tmp_path)
    subj = ProjectCanon("celeste", base_dir=tmp_path).load()[0]
    assert subj.lora is not None
    assert subj.lora.name == "celeste-narrator.safetensors"
    assert subj.lora.strength == 0.8


def test_canon_loras_returned_when_subject_present(tmp_path: Path) -> None:
    _seed_canon_with_lora(tmp_path)
    # Presence = the prompt names an alias.
    loras = canon_loras_for("the narrator on a rooftop at dusk", "celeste", base_dir=tmp_path)
    assert [lr.name for lr in loras] == ["celeste-narrator.safetensors"]
    assert loras[0].strength == 0.8


def test_subject_presence_is_alias_only(tmp_path: Path) -> None:
    # A prompt containing the legacy locked text but naming NO alias pins nothing —
    # presence is alias-only after the locked-injection removal.
    _seed_legacy_file(tmp_path)
    loras = canon_loras_for(
        f"a rooftop portrait, {_LEGACY_LOCKED}, dusk light", "celeste", base_dir=tmp_path
    )
    assert loras == []


def test_canon_loras_force_pins_unnamed_subject(tmp_path: Path) -> None:
    _seed_canon_with_lora(tmp_path)
    # Not named in the prompt — but forced (matches the @narrator alias without the @).
    loras = canon_loras_for(
        "a wide empty neon cityscape, no people", "celeste",
        base_dir=tmp_path, force=["narrator"],
    )
    assert [lr.name for lr in loras] == ["celeste-narrator.safetensors"]


def test_canon_loras_empty_when_subject_absent(tmp_path: Path) -> None:
    _seed_canon_with_lora(tmp_path)
    assert canon_loras_for("a neon alley, rain, no people", "celeste", base_dir=tmp_path) == []


def test_canon_loras_empty_when_subject_has_no_lora(tmp_path: Path) -> None:
    _seed_canon(tmp_path)  # narrator, but no lora set
    assert canon_loras_for("the narrator at the bar", "celeste", base_dir=tmp_path) == []


def test_canon_loras_noop_without_project_or_file(tmp_path: Path) -> None:
    assert canon_loras_for("the narrator", None, base_dir=tmp_path) == []
    assert canon_loras_for("the narrator", "missing", base_dir=tmp_path) == []


# ── scene_cast (canon as a composition input) ────────────────────────────────────


def _seed_two_subjects(base: Path) -> None:
    store = ProjectCanon("celeste", base_dir=base)
    store.set_subject(
        aliases=["the narrator", "narrator", "@narrator", "Chris", "the man"],
        id="narrator_v1",
    )
    store.set_subject(aliases=["Celeste", "the waitress"], id="celeste_v1")


def test_scene_cast_returns_subject_named_by_any_alias(tmp_path: Path) -> None:
    _seed_two_subjects(tmp_path)
    # The scene names "Chris" (an alias of the narrator) but never names Celeste.
    scene = "a Black American man named Chris is in Argentina, alone, missing home."
    cast = scene_cast(scene, "celeste", base_dir=tmp_path)
    assert [c.aliases[0] for c in cast] == ["the narrator"]


def test_scene_cast_excludes_subjects_not_named(tmp_path: Path) -> None:
    _seed_two_subjects(tmp_path)
    assert scene_cast("a wide empty neon cityscape at dusk, no people", "celeste",
                      base_dir=tmp_path) == []


def test_scene_cast_noop_without_project_file_or_text(tmp_path: Path) -> None:
    _seed_two_subjects(tmp_path)
    assert scene_cast("Chris at the bar", None, base_dir=tmp_path) == []
    assert scene_cast("Chris at the bar", "missing", base_dir=tmp_path) == []
    assert scene_cast("", "celeste", base_dir=tmp_path) == []


# ── update_subject (surgical edits — the canon edit backend) ──────────────────────


def test_update_subject_changes_one_asset_field_preserving_the_rest(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)  # narrator: 3 aliases, id + wardrobe set
    updated = store.update_subject("the narrator", wardrobe="narrator_wardrobe_v2")
    assert updated.wardrobe == "narrator_wardrobe_v2"
    assert updated.aliases == ["the narrator", "narrator", "@narrator"]  # untouched
    assert updated.id == "narrator_v1"                                    # untouched
    # Persisted, not just returned.
    assert store.load()[0].wardrobe == "narrator_wardrobe_v2"


def test_update_subject_selected_by_any_alias_adds_and_removes(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    # Select by a non-primary alias; add an alias + set a region in the same call.
    updated = store.update_subject(
        "@narrator", add_aliases=["Chris"], region="narrator_mask",
    )
    assert "Chris" in updated.aliases
    assert updated.region == "narrator_mask"


def test_update_subject_empty_string_clears_asset_field(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)  # wardrobe set at seed
    updated = store.update_subject("the narrator", wardrobe="")
    assert updated.wardrobe is None
    assert store.load()[0].wardrobe is None


def test_update_subject_dedupes_aliases_case_insensitively(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    updated = store.update_subject("the narrator", add_aliases=["NARRATOR", "Chris"])
    assert updated.aliases.count("narrator") == 1  # "NARRATOR" not re-added
    assert "Chris" in updated.aliases


def test_update_subject_cannot_remove_last_alias(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    with pytest.raises(ValueError, match="at least one alias"):
        store.update_subject("the narrator", remove_aliases=["the narrator", "narrator", "@narrator"])


def test_update_subject_unknown_selector_raises_with_known_aliases(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    store = ProjectCanon("celeste", base_dir=tmp_path)
    with pytest.raises(ValueError, match="No canon subject matches 'ghost'"):
        store.update_subject("ghost", id="x")


def test_update_subject_sets_and_clears_lora(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)  # narrator, no lora
    with_lora = store.update_subject("the narrator", lora=LoraRef(name="narr.safetensors", strength=0.8))
    assert with_lora.lora is not None and with_lora.lora.name == "narr.safetensors"
    # Clearing leaves the rest intact.
    cleared = store.update_subject("the narrator", clear_lora=True)
    assert cleared.lora is None
    assert cleared.id == with_lora.id


def test_update_subject_lora_and_clear_are_mutually_exclusive(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    with pytest.raises(ValueError, match="not both"):
        store.update_subject("the narrator", lora=LoraRef(name="x"), clear_lora=True)


def test_update_subject_preserves_lora_when_editing_other_fields(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    store.update_subject("the narrator", lora=LoraRef(name="narr.safetensors", strength=0.8))
    # Editing an asset field must NOT drop the pinned LoRA.
    updated = store.update_subject("the narrator", id="narrator_v2")
    assert updated.id == "narrator_v2"
    assert updated.lora is not None and updated.lora.name == "narr.safetensors"
