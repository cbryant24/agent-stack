"""Test the digest session-primer command (read-only, store mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

from visual_generation import cli as cli_mod
from visual_generation.models import TechniqueLesson, VisualGeneration


def test_digest_renders_generations_lessons_and_pending(monkeypatch) -> None:
    loved = VisualGeneration(caption="neon alley", project="celeste", reaction="loved", rating=5)
    pending = VisualGeneration(caption="rooftop dusk", project="celeste")  # default reaction=pending
    lesson = TechniqueLesson(statement="CFG>7 washes skin", valence="negative", scope="settings", confirmed=True)

    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_generations = AsyncMock(return_value=[loved])
    store.list_lessons = AsyncMock(return_value=[lesson])
    store.list_pending = AsyncMock(return_value=[pending])
    monkeypatch.setattr(cli_mod, "_get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli_mod.cli, ["digest", "celeste"])

    assert result.exit_code == 0, result.output
    assert "Digest for 'celeste'" in result.output
    assert "LOVED" in result.output and "neon alley" in result.output
    assert "Awaiting your reaction" in result.output and "rooftop dusk" in result.output
    assert "CFG>7 washes skin" in result.output
    store.list_generations.assert_awaited_once_with(project="celeste")


def test_digest_empty_project(monkeypatch) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_generations = AsyncMock(return_value=[])
    store.list_lessons = AsyncMock(return_value=[])
    store.list_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(cli_mod, "_get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli_mod.cli, ["digest", "fresh"])
    assert result.exit_code == 0, result.output
    assert "none yet" in result.output
