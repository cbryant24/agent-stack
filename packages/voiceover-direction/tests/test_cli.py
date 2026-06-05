from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from voiceover_direction.cli import cli
from voiceover_direction.directed_script import write_directed_script
from voiceover_direction.generation import GenerationPlan, SectionPlan
from voiceover_direction.models import (
    CharacterUsage,
    DirectedScript,
    DirectedSection,
    DirectionLesson,
    DirectionResult,
    GenerationResult,
    Take,
    VoiceoverResult,
    VoiceProfile,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _result(**overrides) -> DirectionResult:
    defaults = dict(
        directed_script=DirectedScript(
            project_id="ep",
            sections=[DirectedSection(section_id="intro", heading="Intro", text="[warm] Hi.")],
        ),
        output_path=Path("/tmp/ep.directed.md"),
        overall_reasoning="soft to assured",
        run_id="run-1",
        status="completed",
        cost_usd=0.01,
        wall_time_sec=2.0,
        items_processed=1,
    )
    defaults.update(overrides)
    return DirectionResult(**defaults)


def test_direct_smoke(runner: CliRunner, tmp_path: Path) -> None:
    script = tmp_path / "ep.md"
    script.write_text("# Intro\nHi.\n", encoding="utf-8")

    with patch("voiceover_direction.cli.direct_sync", return_value=_result()) as mock_direct:
        result = runner.invoke(cli, ["direct", str(script)])

    assert result.exit_code == 0, result.output
    assert "completed" in result.output
    assert "Sections:  1" in result.output
    assert mock_direct.call_args.args[0] == str(script)


def test_direct_dry_run_flag_forwarded(runner: CliRunner, tmp_path: Path) -> None:
    script = tmp_path / "ep.md"
    script.write_text("# Intro\nHi.\n", encoding="utf-8")

    with patch("voiceover_direction.cli.direct_sync",
               return_value=_result(output_path=None)) as mock_direct:
        result = runner.invoke(cli, ["direct", str(script), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert mock_direct.call_args.kwargs["dry_run"] is True


def test_direct_output_option_forwarded(runner: CliRunner, tmp_path: Path) -> None:
    script = tmp_path / "ep.md"
    script.write_text("# Intro\nHi.\n", encoding="utf-8")

    with patch("voiceover_direction.cli.direct_sync", return_value=_result()) as mock_direct:
        result = runner.invoke(cli, ["direct", str(script), "-o", str(tmp_path / "out.md")])

    assert result.exit_code == 0, result.output
    assert mock_direct.call_args.kwargs["output_path"] == str(tmp_path / "out.md")


def test_missing_script_errors(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["direct", "/nonexistent/script.md"])
    assert result.exit_code != 0


# ── generate: the soft-inform cost gate (plan → gate → spend) ────────────────


def _directed_file(tmp_path: Path) -> Path:
    script = DirectedScript(
        project_id="ep",
        sections=[
            DirectedSection(section_id="intro", heading="Intro", text="[warm] Hi there.",
                            voice_id="voice-1", model="eleven_v3"),
            DirectedSection(section_id="outro", heading="Outro", text="Bye.",
                            voice_id="voice-2", model="eleven_v3"),
        ],
    )
    path = tmp_path / "ep.directed.md"
    write_directed_script(script, path)
    return path


def _usage() -> CharacterUsage:
    return CharacterUsage(character_count=2000, character_limit=10000, characters_remaining=8000)


def _section_plan(section_id="intro", text="[warm] Hi there.", voice_id="voice-1",
                  was_redirected=False, note=None) -> SectionPlan:
    return SectionPlan(
        section_id=section_id, heading=section_id.title(), text=text, voice_id=voice_id,
        model="eleven_v3", settings={}, char_count=len(text),
        was_redirected=was_redirected, note=note,
    )


def _plan(plans=None, skipped=None, cost_usd=0.0) -> GenerationPlan:
    return GenerationPlan(
        run_id="plan-1", project_id="ep", domain=None,
        plans=plans if plans is not None else [_section_plan()],
        skipped=skipped or [], cost_usd=cost_usd,
    )


def _gen_result() -> GenerationResult:
    return GenerationResult(
        results=[VoiceoverResult(take_id="t-1", audio_path="/abs/intro.mp3",
                                 character_cost=16, remaining_characters=7984)],
        run_id="spend-1", status="completed", items_processed=1,
    )


_UNSET = object()


def _patch_gate(plan=None, usage=_UNSET, plan_side_effect=None):
    """Patch plan_generation_sync, _query_usage, spend_generation_sync for a gate test.

    `usage=None` means the vendor query failed (remaining unknown); omit it for a normal read.
    """
    plan_mock = (
        patch("voiceover_direction.cli.plan_generation_sync", side_effect=plan_side_effect)
        if plan_side_effect is not None
        else patch("voiceover_direction.cli.plan_generation_sync", return_value=plan or _plan())
    )
    usage_val = _usage() if usage is _UNSET else usage
    return (
        plan_mock,
        patch("voiceover_direction.cli._query_usage", AsyncMock(return_value=usage_val)),
        patch("voiceover_direction.cli.spend_generation_sync", return_value=_gen_result()),
    )


def test_gate_shows_cost_and_remaining_then_proceeds(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate()
    with p_plan, p_usage, p_spend as spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "intro: 16 chars" in result.output
    assert "Vendor remaining: 8000" in result.output
    assert "Total to spend: 16 characters" in result.output
    spend.assert_called_once()


def test_gate_abort_does_not_spend(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate()
    with p_plan, p_usage, p_spend as spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro"], input="n\n")

    assert result.exit_code != 0  # aborted before the spend
    spend.assert_not_called()


def test_yes_skips_the_gate(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate()
    with p_plan, p_usage, p_spend as spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Spend 16 characters?" not in result.output  # no prompt
    spend.assert_called_once()


def test_all_shows_aggregate_cost(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    plan = _plan(plans=[
        _section_plan("intro", "[warm] Hi there.", "voice-1"),
        _section_plan("outro", "Bye.", "voice-2"),
    ])
    p_plan, p_usage, p_spend = _patch_gate(plan=plan)
    with p_plan, p_usage, p_spend:
        result = runner.invoke(cli, ["generate", str(directed), "--all"], input="y\n")

    assert result.exit_code == 0, result.output
    total = len("[warm] Hi there.") + len("Bye.")
    assert f"Total to spend: {total} characters" in result.output


def test_remaining_unknown_when_usage_fails(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate(usage=None)
    with p_plan, p_usage, p_spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Vendor remaining: unknown" in result.output


def test_unknown_section_errors(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate(plan_side_effect=ValueError("Unknown section_id 'nope'"))
    with p_plan, p_usage, p_spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "nope"])
    assert result.exit_code != 0


def test_gate_shows_revised_markup_for_redirected_section(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    plan = _plan(
        plans=[_section_plan(text="[slow] Hi there.", was_redirected=True, note="slow it down")],
        cost_usd=0.0123,
    )
    p_plan, p_usage, p_spend = _patch_gate(plan=plan)
    with p_plan, p_usage, p_spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro", "--yes"])

    assert result.exit_code == 0, result.output
    assert "re-directed" in result.output
    assert 'folded in note: "slow it down"' in result.output
    assert "revised: [slow] Hi there." in result.output
    assert "Re-direction cost: $0.0123" in result.output


def test_raw_forwarded_to_plan(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate()
    with p_plan as plan_mock, p_usage, p_spend:
        result = runner.invoke(cli, ["generate", str(directed), "--section", "intro", "--raw", "--yes"])
    assert result.exit_code == 0, result.output
    assert plan_mock.call_args.kwargs["raw"] is True


def test_max_cost_overrides_budget(runner: CliRunner, tmp_path: Path) -> None:
    directed = _directed_file(tmp_path)
    p_plan, p_usage, p_spend = _patch_gate()
    with p_plan as plan_mock, p_usage, p_spend:
        result = runner.invoke(
            cli, ["generate", str(directed), "--section", "intro", "--max-cost", "0.5", "--yes"]
        )
    assert result.exit_code == 0, result.output
    assert plan_mock.call_args.kwargs["budget"].max_cost_usd == 0.5


# ── report / review-pending / recall (Step 4) ────────────────────────────────


def _take(**overrides) -> Take:
    base = dict(text="[warm] Hi there.", voice_id="voice-1", model="eleven_v3",
                section_id="intro", project_id="ep")
    base.update(overrides)
    return Take(**base)


def _mock_stores(get_take=None, pending=None, takes=None, lessons=None):
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.get_take = AsyncMock(return_value=get_take)
    store.update_take_reaction = AsyncMock()
    store.list_pending = AsyncMock(return_value=pending or [])
    store.search_takes = AsyncMock(return_value=takes or [])
    store.search_lessons = AsyncMock(return_value=lessons or [])
    return patch("voiceover_direction.cli._get_stores", return_value=(store, MagicMock(), MagicMock())), store


def test_report_records_reaction_and_flips(runner: CliRunner) -> None:
    take = _take()
    p, store = _mock_stores(get_take=take)
    with p:
        result = runner.invoke(cli, ["report", take.entry_id, "--reaction", "loved", "--rating", "5"])
    assert result.exit_code == 0, result.output
    store.update_take_reaction.assert_awaited_once()
    kwargs = store.update_take_reaction.call_args.kwargs
    assert store.update_take_reaction.call_args.args == (take.entry_id, "loved")
    assert kwargs["rating"] == 5
    assert "Recorded: intro" in result.output


def test_report_notes_and_context_land_on_distinct_fields(runner: CliRunner) -> None:
    take = _take()
    p, store = _mock_stores(get_take=take)
    with p:
        result = runner.invoke(cli, [
            "report", take.entry_id, "--reaction", "liked_with_changes",
            "--notes", "slow the open", "--context", "felt rushed",
        ])
    assert result.exit_code == 0, result.output
    kwargs = store.update_take_reaction.call_args.kwargs
    assert kwargs["notes"] == "slow the open"
    assert kwargs["context"] == "felt rushed"


@pytest.mark.parametrize("reaction", ["loved", "liked", "liked_with_changes", "disliked", "render_failed"])
def test_report_accepts_each_reaction(runner: CliRunner, reaction: str) -> None:
    take = _take()
    p, store = _mock_stores(get_take=take)
    with p:
        result = runner.invoke(cli, ["report", take.entry_id, "--reaction", reaction])
    assert result.exit_code == 0, result.output
    assert store.update_take_reaction.call_args.args == (take.entry_id, reaction)


def test_report_rating_warns_on_negative_reaction_but_records(runner: CliRunner) -> None:
    take = _take()
    p, store = _mock_stores(get_take=take)
    with p:
        result = runner.invoke(cli, ["report", take.entry_id, "--reaction", "disliked", "--rating", "3"])
    assert result.exit_code == 0, result.output
    assert "Warning:" in result.output
    store.update_take_reaction.assert_awaited_once()  # still records


def test_report_rating_clean_on_positive(runner: CliRunner) -> None:
    take = _take()
    p, _ = _mock_stores(get_take=take)
    with p:
        result = runner.invoke(cli, ["report", take.entry_id, "--reaction", "loved", "--rating", "4"])
    assert result.exit_code == 0, result.output
    assert "Warning:" not in result.output


def test_report_unknown_reaction_rejected(runner: CliRunner) -> None:
    p, _ = _mock_stores(get_take=_take())
    with p:
        result = runner.invoke(cli, ["report", "t-1", "--reaction", "meh"])
    assert result.exit_code == 2  # click.Choice rejects


def test_report_rating_out_of_range_rejected(runner: CliRunner) -> None:
    p, _ = _mock_stores(get_take=_take())
    with p:
        result = runner.invoke(cli, ["report", "t-1", "--reaction", "loved", "--rating", "9"])
    assert result.exit_code == 2


def test_report_unknown_take_errors(runner: CliRunner) -> None:
    p, store = _mock_stores(get_take=None)  # take not found
    with p:
        result = runner.invoke(cli, ["report", "missing", "--reaction", "loved"])
    assert result.exit_code == 1
    assert "not found" in result.output
    store.update_take_reaction.assert_not_called()


def test_review_pending_lists(runner: CliRunner) -> None:
    take = _take()
    p, _ = _mock_stores(pending=[take])
    with p:
        result = runner.invoke(cli, ["review-pending"])
    assert result.exit_code == 0, result.output
    assert "1 pending take(s)" in result.output
    assert take.entry_id in result.output
    assert "Section: intro" in result.output


def test_review_pending_empty(runner: CliRunner) -> None:
    p, _ = _mock_stores(pending=[])
    with p:
        result = runner.invoke(cli, ["review-pending"])
    assert result.exit_code == 0, result.output
    assert "No pending takes." in result.output


def test_recall_formats_takes_and_lessons(runner: CliRunner) -> None:
    take = _take(reaction="loved", rating=5, context="warm worked")
    lesson = DirectionLesson(statement="Slow on emotional beats.", valence="positive", scope="pacing")
    p, store = _mock_stores(
        takes=[(take.entry_id, 0.91, take)],
        lessons=[(lesson.entry_id, 0.82, lesson)],
    )
    with p:
        result = runner.invoke(cli, ["recall", "calm intro"])
    assert result.exit_code == 0, result.output
    assert "Prior Takes (1)" in result.output
    assert "reaction=loved ★5" in result.output
    assert "context: warm worked" in result.output
    assert "Direction Lessons (1)" in result.output
    assert "[positive/pacing]" in result.output
    # recall excludes pending takes.
    assert store.search_takes.call_args.kwargs["exclude_pending"] is True


def test_recall_cold_start(runner: CliRunner) -> None:
    p, _ = _mock_stores(takes=[], lessons=[])
    with p:
        result = runner.invoke(cli, ["recall", "anything"])
    assert result.exit_code == 0, result.output
    assert "No results found." in result.output


# ── lesson add / fact add / voice sync (Step 5) ──────────────────────────────


def test_lesson_add_writes_confirmed_lesson(runner: CliRunner) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_lesson = AsyncMock()
    with patch("voiceover_direction.cli._get_stores", return_value=(store, MagicMock(), MagicMock())):
        result = runner.invoke(cli, ["lesson", "add", "Slow on emotional beats.",
                                     "--valence", "negative", "--scope", "pacing"])
    assert result.exit_code == 0, result.output
    lesson: DirectionLesson = store.upsert_lesson.call_args.args[0]
    assert lesson.statement == "Slow on emotional beats."
    assert lesson.valence == "negative"
    assert lesson.scope == "pacing"
    assert lesson.confirmed is True


def test_lesson_add_defaults(runner: CliRunner) -> None:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_lesson = AsyncMock()
    with patch("voiceover_direction.cli._get_stores", return_value=(store, MagicMock(), MagicMock())):
        result = runner.invoke(cli, ["lesson", "add", "Keep it warm."])
    assert result.exit_code == 0, result.output
    lesson: DirectionLesson = store.upsert_lesson.call_args.args[0]
    assert lesson.valence == "positive"   # default
    assert lesson.scope == "general"      # default


def test_fact_add_writes_verified_entry(runner: CliRunner) -> None:
    uks = MagicMock()
    uks.ensure_collection = AsyncMock()
    uks.bulk_load_verified = AsyncMock(return_value=["entry-1"])
    with (
        patch("agent_runtime.UserKnowledgeStore", return_value=uks),
        patch("agent_runtime.get_memory_store", return_value=MagicMock()),
    ):
        result = runner.invoke(cli, ["fact", "add", "eleven_v3 reads inline audio tags."])
    assert result.exit_code == 0, result.output
    entries, kwargs = uks.bulk_load_verified.call_args.args, uks.bulk_load_verified.call_args.kwargs
    entry = entries[0][0]
    assert entry["statement"] == "eleven_v3 reads inline audio tags."
    assert entry["domain"] == "elevenlabs_mechanics"   # default
    assert entry["source_type"] == "user_verified"
    assert entry["confidence"] == "high"
    assert kwargs["source_ref"] == "manual:cli"
    assert "entry-1" in result.output


def test_fact_add_domain_override(runner: CliRunner) -> None:
    uks = MagicMock()
    uks.ensure_collection = AsyncMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e"])
    with (
        patch("agent_runtime.UserKnowledgeStore", return_value=uks),
        patch("agent_runtime.get_memory_store", return_value=MagicMock()),
    ):
        result = runner.invoke(cli, ["fact", "add", "x", "--domain", "custom_domain"])
    assert result.exit_code == 0, result.output
    assert uks.bulk_load_verified.call_args.args[0][0]["domain"] == "custom_domain"


def test_voice_sync_replaces_registry_and_reports_count(runner: CliRunner) -> None:
    voices = [
        VoiceProfile(voice_id="v1", name="Rachel", category="stock"),
        VoiceProfile(voice_id="v2", name="Clone", category="cloned"),
    ]
    client = MagicMock()
    client.list_voices = AsyncMock(return_value=voices)
    store = MagicMock()
    store.sync_voices = MagicMock()
    with (
        patch("voiceover_direction.elevenlabs_client.ElevenLabsClient", return_value=client),
        patch("voiceover_direction.cli._get_stores", return_value=(store, MagicMock(), MagicMock())),
    ):
        result = runner.invoke(cli, ["voice", "sync"])
    assert result.exit_code == 0, result.output
    store.sync_voices.assert_called_once_with(voices)   # wholesale replace via the registry
    assert "Synced 2 voices" in result.output
    assert "1 stock, 1 cloned" in result.output
