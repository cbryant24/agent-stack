"""Tests for deterministic project canon (visual_generation.canon)."""

from __future__ import annotations

from pathlib import Path

from visual_generation.canon import ProjectCanon, canon_loras_for, enforce_canon, scene_cast
from visual_generation.models import LoraRef

_NARRATOR = "a young African American man with deep caramel-brown skin, long black yarn dreadlocks falling to the middle of his back"


def _seed_canon(base: Path, project: str = "celeste") -> ProjectCanon:
    store = ProjectCanon(project, base_dir=base)
    store.set_subject(
        aliases=["the narrator", "narrator", "@narrator"],
        locked=_NARRATOR,
        forbid=["short hair", "shoulder-length hair"],
    )
    return store


# ── JSON store round-trip ───────────────────────────────────────────────────────


def test_store_round_trip(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    subjects = store.load()
    assert len(subjects) == 1
    assert subjects[0].locked == _NARRATOR
    assert "the narrator" in subjects[0].aliases

    # Upsert by primary alias replaces, doesn't duplicate.
    store.set_subject(aliases=["the narrator"], locked="updated")
    subjects = store.load()
    assert len(subjects) == 1
    assert subjects[0].locked == "updated"

    assert store.remove("the narrator") is True
    assert store.load() == []
    assert store.remove("the narrator") is False


# ── enforce_canon ────────────────────────────────────────────────────────────────


def test_no_project_or_no_file_is_noop(tmp_path: Path) -> None:
    assert enforce_canon("a narrator on a roof", None, base_dir=tmp_path) == (
        "a narrator on a roof",
        [],
    )
    # project given but no canon file → no-op
    assert enforce_canon("the narrator", "missing", base_dir=tmp_path) == ("the narrator", [])


def test_injects_locked_when_plain_alias_named(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    out, applied = enforce_canon("the narrator stands on a rooftop at dusk", "celeste", base_dir=tmp_path)
    assert _NARRATOR in out
    assert "middle of his back" in out
    assert any("injected canon" in a for a in applied)


def test_expands_token_alias(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    out, applied = enforce_canon("@narrator, close-up portrait", "celeste", base_dir=tmp_path)
    assert out.startswith(_NARRATOR)
    assert "@narrator" not in out
    assert any("expanded" in a for a in applied)


def test_strips_forbidden_phrasing(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    out, applied = enforce_canon(
        "the narrator with short hair on a rooftop", "celeste", base_dir=tmp_path
    )
    assert "short hair" not in out
    assert _NARRATOR in out
    assert any("removed forbidden phrasing" in a for a in applied)


def test_noop_when_subject_not_named(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    out, applied = enforce_canon("a neon alley, rain, no people", "celeste", base_dir=tmp_path)
    assert out == "a neon alley, rain, no people"
    assert applied == []


def test_idempotent_when_locked_already_present(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    prompt = f"the narrator, {_NARRATOR}, on a rooftop"
    out, applied = enforce_canon(prompt, "celeste", base_dir=tmp_path)
    # Locked text already present → no second injection.
    assert out.count("middle of his back") == 1
    assert not any("injected canon" in a for a in applied)


# ── character LoRA (canon_loras_for) ─────────────────────────────────────────────


def _seed_canon_with_lora(base: Path, project: str = "celeste") -> ProjectCanon:
    store = ProjectCanon(project, base_dir=base)
    store.set_subject(
        aliases=["the narrator", "narrator", "@narrator"],
        locked=_NARRATOR,
        forbid=["short hair"],
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
    # Locked text present (post-enforce_canon state) → the LoRA is pinned.
    loras = canon_loras_for(f"the narrator, {_NARRATOR}, on a rooftop", "celeste", base_dir=tmp_path)
    assert [lr.name for lr in loras] == ["celeste-narrator.safetensors"]
    assert loras[0].strength == 0.8


def test_canon_loras_empty_when_subject_absent(tmp_path: Path) -> None:
    _seed_canon_with_lora(tmp_path)
    assert canon_loras_for("a neon alley, rain, no people", "celeste", base_dir=tmp_path) == []


def test_canon_loras_empty_when_subject_has_no_lora(tmp_path: Path) -> None:
    _seed_canon(tmp_path)  # narrator, but no lora set
    assert canon_loras_for(f"the narrator, {_NARRATOR}", "celeste", base_dir=tmp_path) == []


def test_canon_loras_noop_without_project_or_file(tmp_path: Path) -> None:
    assert canon_loras_for("the narrator", None, base_dir=tmp_path) == []
    assert canon_loras_for("the narrator", "missing", base_dir=tmp_path) == []


# ── scene_cast (canon as a composition input) ────────────────────────────────────


def _seed_two_subjects(base: Path) -> None:
    store = ProjectCanon("celeste", base_dir=base)
    store.set_subject(aliases=["the narrator", "narrator", "@narrator", "Chris", "the man"],
                      locked=_NARRATOR)
    store.set_subject(aliases=["Celeste", "the waitress"],
                      locked="a felt puppet of a young woman with yarn hair past her shoulders")


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


def test_update_subject_changes_only_locked_preserving_the_rest(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)  # narrator: 3 aliases, 2 forbids
    updated = store.update_subject("the narrator", locked="a SHORT stocky puppet")
    assert updated.locked == "a SHORT stocky puppet"
    assert updated.aliases == ["the narrator", "narrator", "@narrator"]  # untouched
    assert updated.forbid == ["short hair", "shoulder-length hair"]       # untouched
    # Persisted, not just returned.
    assert store.load()[0].locked == "a SHORT stocky puppet"


def test_update_subject_selected_by_any_alias_adds_and_removes(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    # Select by a non-primary alias; add an alias + a forbid, drop one forbid.
    updated = store.update_subject(
        "@narrator", add_aliases=["Chris"], add_forbid=["lanky"], remove_forbid=["short hair"],
    )
    assert "Chris" in updated.aliases
    assert updated.forbid == ["shoulder-length hair", "lanky"]


def test_update_subject_dedupes_aliases_case_insensitively(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    updated = store.update_subject("the narrator", add_aliases=["NARRATOR", "Chris"])
    assert updated.aliases.count("narrator") == 1  # "NARRATOR" not re-added
    assert "Chris" in updated.aliases


def test_update_subject_cannot_remove_last_alias(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="at least one alias"):
        store.update_subject("the narrator", remove_aliases=["the narrator", "narrator", "@narrator"])


def test_update_subject_unknown_selector_raises_with_known_aliases(tmp_path: Path) -> None:
    _seed_canon(tmp_path)
    store = ProjectCanon("celeste", base_dir=tmp_path)
    import pytest
    with pytest.raises(ValueError, match="No canon subject matches 'ghost'"):
        store.update_subject("ghost", locked="x")


def test_update_subject_sets_and_clears_lora(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)  # narrator, no lora
    with_lora = store.update_subject("the narrator", lora=LoraRef(name="narr.safetensors", strength=0.8))
    assert with_lora.lora is not None and with_lora.lora.name == "narr.safetensors"
    # Clearing leaves the rest intact.
    cleared = store.update_subject("the narrator", clear_lora=True)
    assert cleared.lora is None
    assert cleared.locked == with_lora.locked


def test_update_subject_lora_and_clear_are_mutually_exclusive(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="not both"):
        store.update_subject("the narrator", lora=LoraRef(name="x"), clear_lora=True)


def test_update_subject_preserves_lora_when_editing_other_fields(tmp_path: Path) -> None:
    store = _seed_canon(tmp_path)
    store.update_subject("the narrator", lora=LoraRef(name="narr.safetensors", strength=0.8))
    # Editing the locked text must NOT drop the pinned LoRA.
    updated = store.update_subject("the narrator", locked="new descriptor")
    assert updated.locked == "new descriptor"
    assert updated.lora is not None and updated.lora.name == "narr.safetensors"
