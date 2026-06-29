"""Tests for deterministic project canon (visual_generation.canon)."""

from __future__ import annotations

from pathlib import Path

from visual_generation.canon import ProjectCanon, enforce_canon

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
