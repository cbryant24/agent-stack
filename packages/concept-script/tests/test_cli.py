from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from concept_script.cli import cli
from concept_script.models import BriefSection, ConceptResult, VideoBrief


def _result(**kw) -> ConceptResult:
    defaults = dict(
        brief=VideoBrief(
            logline="A film about focus.",
            sections=[BriefSection(heading="Open", prose="[calm] Breathe.")],
        ),
        script_path=Path("script.md"),
        run_id="run-1",
        status="completed",
        cost_usd=0.01,
        wall_time_sec=2.0,
    )
    defaults.update(kw)
    return ConceptResult(**defaults)


def test_draft_help() -> None:
    result = CliRunner().invoke(cli, ["draft", "--help"])
    assert result.exit_code == 0
    assert "seeds" in result.output.lower()


def test_shape_help() -> None:
    result = CliRunner().invoke(cli, ["shape", "--help"])
    assert result.exit_code == 0
    assert "transcript" in result.output.lower()


def test_draft_inline_seeds() -> None:
    with patch("concept_script.cli.draft_sync", return_value=_result()) as mock:
        result = CliRunner().invoke(cli, ["draft", "focus, calm, 2min"])
    assert result.exit_code == 0
    assert mock.call_args.args[0] == "focus, calm, 2min"
    assert "Open" in result.output


def test_draft_seeds_file(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.md"
    seeds.write_text("# Seeds\nfocus, calm")
    with patch("concept_script.cli.draft_sync", return_value=_result()) as mock:
        result = CliRunner().invoke(cli, ["draft", "--seeds", str(seeds)])
    assert result.exit_code == 0
    assert "focus, calm" in mock.call_args.args[0]


def test_draft_ref_file(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.md"
    seeds.write_text("focus")
    ref = tmp_path / "prior.md"
    ref.write_text("# Prior\nold prose")
    with patch("concept_script.cli.draft_sync", return_value=_result()) as mock:
        result = CliRunner().invoke(cli, ["draft", "--seeds", str(seeds), "--ref", str(ref)])
    assert result.exit_code == 0
    assert "old prose" in mock.call_args.kwargs["prior_script"]


def test_draft_requires_seeds() -> None:
    with patch("concept_script.cli.draft_sync", return_value=_result()):
        result = CliRunner().invoke(cli, ["draft"])
    assert result.exit_code != 0
    assert "seeds" in result.output.lower()


def test_draft_dry_run_flag() -> None:
    with patch("concept_script.cli.draft_sync", return_value=_result()) as mock:
        result = CliRunner().invoke(cli, ["draft", "x", "--dry-run"])
    assert result.exit_code == 0
    assert mock.call_args.kwargs["dry_run"] is True


def test_shape_reads_transcript(tmp_path: Path) -> None:
    t = tmp_path / "t.txt"
    t.write_text("um so like, shipping is hard")
    trailer_result = _result(
        brief=VideoBrief(
            logline="Raw take.",
            sections=[BriefSection(heading="Rant", prose="[wry] Shipping is hard.")],
            cut_trailer=["Deleted the tangent"],
        )
    )
    with patch("concept_script.cli.shape_sync", return_value=trailer_result) as mock:
        result = CliRunner().invoke(cli, ["shape", str(t)])
    assert result.exit_code == 0
    assert "shipping is hard" in mock.call_args.args[0]
    assert "Deleted the tangent" in result.output


def test_shape_missing_file() -> None:
    result = CliRunner().invoke(cli, ["shape", "/nonexistent/file.txt"])
    assert result.exit_code != 0
