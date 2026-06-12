from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from edit_brief import cli as cli_mod
from edit_brief.models import (
    BriefResult,
    DiscoveredInputs,
    DiscoveredMusic,
    EditBrief,
    TimelineRow,
)

SCRIPT = "# Intro\nhello world\n"


def _result(dry_run: bool) -> BriefResult:
    inputs = DiscoveredInputs(
        project_id="s",
        music=DiscoveredMusic(file=None, bpm=None, bpm_source="none"),
    )
    brief = EditBrief(
        project_id="s",
        provenance=inputs,
        timeline=[TimelineRow(section_id="intro", heading="Intro", start_sec=0, end_sec=4,
                              timing_source="estimate")],
        notations=["No BPM available — beat grid omitted."],
    )
    return BriefResult(
        brief=brief, dry_run=dry_run,
        brief_path=None if dry_run else Path("/tmp/s.edit-brief.md"),
        run_id="" if dry_run else "run-1", status="completed",
    )


def test_dry_run_prints_discovery_and_writes_nothing(tmp_path, monkeypatch):
    script = tmp_path / "s.md"
    script.write_text(SCRIPT)

    seen = {}

    def fake_draft_sync(path, **kwargs):
        seen.update(kwargs)
        return _result(dry_run=True)

    monkeypatch.setattr(cli_mod, "draft_sync", fake_draft_sync)

    res = CliRunner().invoke(cli_mod.cli, ["draft", str(script), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "Discovery: s" in res.output
    assert "No BPM available" in res.output
    assert "dry run — no brief written" in res.output
    assert seen["dry_run"] is True


def test_full_run_reports_brief_path(tmp_path, monkeypatch):
    script = tmp_path / "s.md"
    script.write_text(SCRIPT)
    monkeypatch.setattr(cli_mod, "draft_sync", lambda path, **kw: _result(dry_run=False))

    res = CliRunner().invoke(cli_mod.cli, ["draft", str(script)])
    assert res.exit_code == 0, res.output
    assert "Brief:     /tmp/s.edit-brief.md" in res.output
    assert "Run ID:    run-1" in res.output


def test_missing_script_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "draft_sync", lambda path, **kw: _result(dry_run=True))
    res = CliRunner().invoke(cli_mod.cli, ["draft", str(tmp_path / "nope.md")])
    assert res.exit_code != 0  # click validates exists=True
