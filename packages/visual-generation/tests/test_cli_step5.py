"""Step-5 CLI surface — inspect, direct writes, tutor (CliRunner + mocks)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from visual_generation.cli import cli
from visual_generation.explain import ExplainResult
from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate
from visual_generation.research import ResearchOutcome


def _gen(**overrides) -> VisualGeneration:
    base = dict(caption="neon wolf", prompt="a neon wolf", asset_path="/data/wolf.png",
                model="flux1-dev.safetensors", settings={"steps": 20})
    base.update(overrides)
    return VisualGeneration(**base)


# ── review-pending / chain show / recall ──────────────────────────────────────


def test_review_pending(monkeypatch) -> None:
    pend = _gen(reaction="pending", status="pending")
    monkeypatch.setattr("visual_generation.cli.list_pending_sync", lambda **k: [pend])
    result = CliRunner().invoke(cli, ["review-pending"])
    assert result.exit_code == 0, result.output
    assert "pending generation(s)" in result.output
    assert "wolf.png" in result.output


def test_review_pending_empty(monkeypatch) -> None:
    monkeypatch.setattr("visual_generation.cli.list_pending_sync", lambda **k: [])
    result = CliRunner().invoke(cli, ["review-pending"])
    assert result.exit_code == 0
    assert "No pending generations." in result.output


def test_chain_show(monkeypatch) -> None:
    root = _gen(reaction="loved", rating=5)
    monkeypatch.setattr("visual_generation.cli.get_chain_sync", lambda rid, **k: [root])
    result = CliRunner().invoke(cli, ["chain", "show", root.entry_id])
    assert result.exit_code == 0, result.output
    assert root.entry_id[:12] in result.output
    assert "LOVED ★5" in result.output


def test_chain_show_empty(monkeypatch) -> None:
    monkeypatch.setattr("visual_generation.cli.get_chain_sync", lambda rid, **k: [])
    result = CliRunner().invoke(cli, ["chain", "show", "root-xyz"])
    assert result.exit_code == 0
    assert "No generations found" in result.output


def test_recall(monkeypatch) -> None:
    gen = _gen(reaction="loved", rating=5)
    lesson = TechniqueLesson(statement="CFG>7 washes skin", valence="negative",
                             scope="settings", confirmed=True)
    tmpl = WorkflowTemplate(name="flux-txt2img", descriptor="basic flux")
    monkeypatch.setattr(
        "visual_generation.cli.recall_sync",
        lambda q, **k: ([(gen.entry_id, 0.9, gen)], [(lesson.entry_id, 0.8, lesson)],
                        [(tmpl.entry_id, 0.7, tmpl)]),
    )
    result = CliRunner().invoke(cli, ["recall", "neon wolf"])
    assert result.exit_code == 0, result.output
    assert "Prior Generations" in result.output
    assert "Technique Lessons" in result.output
    assert "Workflow Templates" in result.output


# ── lesson add / fact add ──────────────────────────────────────────────────────


def test_lesson_add_round_trips_with_scope_and_valence(monkeypatch) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_lesson = AsyncMock()
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(
        cli, ["lesson", "add", "Euler+simple is reliable on flux",
              "--scope", "settings", "--valence", "positive"],
    )
    assert result.exit_code == 0, result.output
    lesson: TechniqueLesson = store.upsert_lesson.call_args.args[0]
    assert lesson.statement == "Euler+simple is reliable on flux"
    assert lesson.scope == "settings"
    assert lesson.valence == "positive"
    assert lesson.confirmed is True  # the command IS the confirmation


def test_lesson_add_rejects_bad_scope(monkeypatch) -> None:
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (MagicMock(), MagicMock()))
    result = CliRunner().invoke(cli, ["lesson", "add", "x", "--scope", "bogus"])
    assert result.exit_code != 0  # closed-vocab via click.Choice


# ── lesson list / lesson rm ─────────────────────────────────────────────────────


def _lesson(**overrides) -> TechniqueLesson:
    base = dict(statement="Euler+simple is reliable on flux", valence="positive",
                scope="settings", confirmed=True)
    base.update(overrides)
    return TechniqueLesson(**base)


def test_lesson_list_shows_stored_lessons(monkeypatch) -> None:
    le = _lesson()
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.list_lessons = AsyncMock(return_value=[le])
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli, ["lesson", "list"])
    assert result.exit_code == 0, result.output
    assert le.entry_id in result.output  # the id is the whole point
    assert "Euler+simple is reliable on flux" in result.output
    assert store.list_lessons.call_args.kwargs["confirmed_only"] is True


def test_lesson_rm_deletes_targeted_lesson(monkeypatch) -> None:
    le = _lesson()
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_lesson = AsyncMock(return_value=le)
    store.delete_lesson = AsyncMock()
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli, ["lesson", "rm", le.entry_id, "--yes"])
    assert result.exit_code == 0, result.output
    assert store.delete_lesson.call_args.args[0] == le.entry_id
    assert "Removed technique lesson" in result.output


def test_lesson_rm_refuses_non_lesson(monkeypatch) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_lesson = AsyncMock(side_effect=ValueError("generation"))
    store.delete_lesson = AsyncMock()
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli, ["lesson", "rm", "some-generation-id"])
    assert result.exit_code != 0
    assert "not a technique_lesson" in result.output
    store.delete_lesson.assert_not_called()


def test_lesson_rm_errors_on_missing_id(monkeypatch) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_lesson = AsyncMock(return_value=None)
    store.delete_lesson = AsyncMock()
    monkeypatch.setattr("visual_generation.cli._get_stores", lambda: (store, MagicMock()))

    result = CliRunner().invoke(cli, ["lesson", "rm", "nope"])
    assert result.exit_code != 0
    assert "No technique lesson with id" in result.output
    store.delete_lesson.assert_not_called()


def test_fact_add_writes_to_user_knowledge_with_domain(monkeypatch) -> None:
    uks = MagicMock()
    uks.ensure_collection = AsyncMock()
    uks.bulk_load_verified = AsyncMock(return_value=["uk-entry-1"])
    monkeypatch.setattr("agent_runtime.UserKnowledgeStore", lambda *a, **k: uks)
    monkeypatch.setattr("agent_runtime.get_memory_store", lambda: MagicMock())

    result = CliRunner().invoke(
        cli, ["fact", "add", "Pods bill per-second of uptime", "--domain", "runpod_mechanics"],
    )
    assert result.exit_code == 0, result.output
    entries, kwargs = uks.bulk_load_verified.call_args.args, uks.bulk_load_verified.call_args.kwargs
    payload = entries[0][0]
    assert payload["domain"] == "runpod_mechanics"
    assert payload["statement"] == "Pods bill per-second of uptime"
    assert kwargs["source_ref"] == "manual:cli"
    assert "uk-entry-1" in result.output


def test_fact_add_rejects_unknown_domain(monkeypatch) -> None:
    result = CliRunner().invoke(cli, ["fact", "add", "x", "--domain", "suno_mechanics"])
    assert result.exit_code != 0  # not a visual-generation mechanics domain


def test_fact_add_requires_domain() -> None:
    result = CliRunner().invoke(cli, ["fact", "add", "x"])
    assert result.exit_code != 0  # --domain is required


# ── fact ingest-docs ─────────────────────────────────────────────────────────


def test_fact_ingest_docs_dry_run_parses_without_writing(monkeypatch, tmp_path) -> None:
    # A tiny staged doc: H1 page title + one H2 section (the candidate).
    doc = tmp_path / "comfyui.md"
    doc.write_text(
        "# ComfyUI Notes\n\n## KSampler\n\nEuler + simple is a reliable default on Flux.\n",
        encoding="utf-8",
    )
    # Guard: dry-run must hit no live store. Any store construction is a failure.
    monkeypatch.setattr(
        "agent_runtime.UserKnowledgeStore",
        lambda *a, **k: pytest.fail("dry-run must not touch the store"),
    )

    result = CliRunner().invoke(
        cli, ["fact", "ingest-docs", str(tmp_path), "--domain", "comfyui_mechanics", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "Parsed 1 candidate" in result.output
    assert "dry run" in result.output.lower()


def test_fact_ingest_docs_rejects_unknown_domain(tmp_path) -> None:
    result = CliRunner().invoke(
        cli, ["fact", "ingest-docs", str(tmp_path), "--domain", "suno_mechanics", "--dry-run"],
    )
    assert result.exit_code != 0  # not a visual-generation mechanics domain


def test_fact_ingest_docs_requires_domain(tmp_path) -> None:
    result = CliRunner().invoke(cli, ["fact", "ingest-docs", str(tmp_path), "--dry-run"])
    assert result.exit_code != 0  # --domain is required


# ── explain / research ──────────────────────────────────────────────────────────


def test_explain(monkeypatch) -> None:
    res = ExplainResult(concept="cfg", level="concise", gloss="Guidance is the knob.",
                        own_lessons=["CFG>7 washed skin"], cost_usd=0.01)
    captured = {}

    def _fake(concept, **kwargs):
        captured["concept"] = concept
        captured["level"] = kwargs.get("level")
        return res

    monkeypatch.setattr("visual_generation.cli.explain_sync", _fake)
    result = CliRunner().invoke(cli, ["explain", "cfg", "--level", "concise"])
    assert result.exit_code == 0, result.output
    assert captured["level"] == "concise"
    assert "CFG>7 washed skin" in result.output       # own lessons always shown
    assert "Guidance is the knob." in result.output


def test_explain_rejects_bad_level() -> None:
    result = CliRunner().invoke(cli, ["explain", "cfg", "--level", "loud"])
    assert result.exit_code != 0


def test_research(monkeypatch) -> None:
    outcome = ResearchOutcome(topic="runpod headless", delegation_status="completed",
                              items_processed=2, tutorial_hits=[(0.8, "pod billing")])
    monkeypatch.setattr("visual_generation.cli.research_sync", lambda t, **k: outcome)
    result = CliRunner().invoke(cli, ["research", "runpod headless"])
    assert result.exit_code == 0, result.output
    assert "completed" in result.output
    assert "pod billing" in result.output


# ── canon --lora parsing (character-LoRA continuity) ─────────────────────────────


def test_parse_lora_defaults_strength_to_one() -> None:
    from visual_generation.cli import _parse_lora

    lr = _parse_lora("celeste-narrator.safetensors")
    assert lr.name == "celeste-narrator.safetensors"
    assert lr.strength == 1.0


def test_parse_lora_reads_explicit_strength() -> None:
    from visual_generation.cli import _parse_lora

    lr = _parse_lora("celeste-narrator.safetensors:0.8")
    assert lr.strength == 0.8


def test_parse_lora_rejects_empty_name_and_bad_strength() -> None:
    import click

    from visual_generation.cli import _parse_lora

    with pytest.raises(click.BadParameter):
        _parse_lora(":0.8")
    with pytest.raises(click.BadParameter):
        _parse_lora("char.safetensors:loud")
