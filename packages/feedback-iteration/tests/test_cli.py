from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from feedback_iteration import cli as cli_mod
from feedback_iteration.cli import cli
from feedback_iteration.models import RevisionResult


def _brief(tmp_path: Path) -> Path:
    p = tmp_path / "script-draft.edit-brief.md"
    p.write_text("---\nproject_id: t\nversion: 1\n---\n", encoding="utf-8")
    return p


def test_missing_brief_errors_at_parse_time():
    result = CliRunner().invoke(cli, ["revise", "does-not-exist.md", "feedback"])
    assert result.exit_code != 0
    assert "does-not-exist.md" in result.output


def test_dry_run_prints_echo(tmp_path, monkeypatch):
    p = _brief(tmp_path)
    captured = {}

    def _fake(brief, feedback, **kwargs):
        captured.update(kwargs)
        return RevisionResult(
            brief_path=p,
            project_id="script-draft",
            section_ids=["a", "b"],
            feedback_items=["tighten the calm section"],
            version_from=1,
            version_to=2,
            snapshot_path=tmp_path / "versions" / "script-draft.edit-brief.v1.md",
            dry_run=True,
        )

    monkeypatch.setattr(cli_mod, "revise_sync", _fake)
    result = CliRunner().invoke(cli, ["revise", str(p), "tighten the calm section", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert captured["dry_run"] is True
    assert "[0] tighten the calm section" in result.output
    assert "1 → 2 (planned)" in result.output
    assert "nothing spent" in result.output


def test_full_run_prints_summary(tmp_path, monkeypatch):
    p = _brief(tmp_path)

    def _fake(brief, feedback, **kwargs):
        return RevisionResult(
            brief_path=p,
            snapshot_path=tmp_path / "versions" / "script-draft.edit-brief.v1.md",
            project_id="script-draft",
            section_ids=["a"],
            feedback_items=["tighten"],
            version_from=1,
            version_to=2,
            applied=['"tighten" → #the-calm-underneath adjust_duration'],
            unresolved=['"the drop" — no drop here'],
            lesson_draft_ids=["draft-1"],
            run_id="01ABC",
            status="completed",
            cost_usd=0.0123,
            wall_time_sec=3.2,
        )

    monkeypatch.setattr(cli_mod, "revise_sync", _fake)
    result = CliRunner().invoke(cli, ["revise", str(p), "tighten"])
    assert result.exit_code == 0, result.output
    assert "Version:   1 → 2" in result.output
    assert "draft-1" in result.output
    assert "no drop here" in result.output
    assert "$0.0123" in result.output
