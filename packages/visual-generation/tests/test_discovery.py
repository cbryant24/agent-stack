"""Tests for project-document compilation (visual_generation.discovery)."""

from __future__ import annotations

from pathlib import Path

from visual_generation.discovery import (
    compile_creative_input,
    discover_scenes,
    extract_scene,
    list_scenes,
)

_DIRECTED = """\
# Celeste — directed

## Rooftop confrontation
The narrator stands at the edge, neon below. Tense, wide.

## Quiet aftermath
Rain eases. A close, still moment.
"""


def _seed_project(base: Path, project: str = "celeste", **docs: str) -> Path:
    folder = base / project
    folder.mkdir(parents=True)
    for name, text in docs.items():
        (folder / f"{name}.md").write_text(text, encoding="utf-8")
    return folder


# ── scene parsing ────────────────────────────────────────────────────────────


def test_list_and_extract_scene() -> None:
    assert list_scenes(_DIRECTED) == ["Rooftop confrontation", "Quiet aftermath"]
    section = extract_scene(_DIRECTED, "rooftop")
    assert section is not None
    assert "neon below" in section
    assert "Rain eases" not in section  # bounded to the one section
    assert extract_scene(_DIRECTED, "nonexistent") is None


def test_discover_scenes_prefers_directed(tmp_path: Path) -> None:
    _seed_project(tmp_path, directed=_DIRECTED, script="## Only Script Scene\nx")
    assert discover_scenes("celeste", projects_dir=tmp_path) == [
        "Rooftop confrontation",
        "Quiet aftermath",
    ]
    assert discover_scenes("missing", projects_dir=tmp_path) == []


# ── compile_creative_input ─────────────────────────────────────────────────────


def test_compile_points_only_no_project(tmp_path: Path) -> None:
    c = compile_creative_input(None, ["wide shot", "dusk"], None, None, projects_dir=tmp_path)
    assert "wide shot" in c.text
    assert c.sources == []
    assert c.query == "wide shot; dusk"


def test_compile_folds_docs_and_scene(tmp_path: Path) -> None:
    _seed_project(
        tmp_path, directed=_DIRECTED, brief="A neon-noir short.", techniques="Use rim light.",
    )
    c = compile_creative_input(
        None, ["wide shot"], "celeste", "rooftop", projects_dir=tmp_path
    )
    # Narrative doc narrowed to the scene; context docs whole.
    assert "neon below" in c.text
    assert "Rain eases" not in c.text
    assert "A neon-noir short." in c.text
    assert "Use rim light." in c.text
    assert "directed.md (scene: rooftop)" in c.sources
    assert "brief.md" in c.sources and "techniques.md" in c.sources
    # Retrieval query stays short (points + scene), not the whole doc.
    assert "wide shot" in c.query and "rooftop" in c.query
    assert "neon below" not in c.query


def test_compile_missing_scene_falls_back_to_whole_doc(tmp_path: Path) -> None:
    _seed_project(tmp_path, directed=_DIRECTED)
    c = compile_creative_input(None, ["x"], "celeste", "no-such-scene", projects_dir=tmp_path)
    # Scene not found → whole narrative doc is included, labeled without a scene.
    assert "Rooftop confrontation" in c.text
    assert "Quiet aftermath" in c.text
    assert "directed.md" in c.sources


def test_compile_empty_when_nothing_provided(tmp_path: Path) -> None:
    c = compile_creative_input(None, None, "celeste", None, projects_dir=tmp_path)
    assert c.text == ""
    assert c.sources == []
