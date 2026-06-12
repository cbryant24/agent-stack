"""CLI tests for `orchestrator remediate` — the refusal gates (status / spec).

The happy path performs a Qdrant write and is covered by the diagnostics seam tests
(the real music-curation handler over a mocked store); here we cover the CLI's own
guard rails, which fire before any handler is registered or any write is attempted.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from orchestrator.cli import cli
from orchestrator.diagnostics import DiagnosticReport, RemediationSpec, write_diagnostic_report


def _write(report: DiagnosticReport, vault: Path) -> Path:
    return write_diagnostic_report(report, vault=vault)


def _base(**overrides) -> DiagnosticReport:
    base = dict(
        collection="music_curation_memory",
        owning_agent="music-curation",
        symptom="s",
        diagnosis="d",
        proposed_fix="re-tag",
        created_at="2026-06-11T00:00:00+00:00",
        remediation=RemediationSpec(
            kind="retag", match={"reaction": "approvd"}, set={"reaction": "approved"}
        ),
    )
    base.update(overrides)
    return DiagnosticReport(**base)


class TestRemediateRefusals:
    def test_refuses_non_open_status(self, tmp_path: Path) -> None:
        path = _write(_base(status="fixed"), tmp_path)
        result = CliRunner().invoke(cli, ["remediate", str(path)])
        assert result.exit_code != 0
        assert "not 'open'" in result.output

    def test_refuses_missing_spec(self, tmp_path: Path) -> None:
        path = _write(_base(remediation=None), tmp_path)
        result = CliRunner().invoke(cli, ["remediate", str(path)])
        assert result.exit_code != 0
        assert "no remediation spec" in result.output

    def test_missing_file_is_a_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["remediate", str(tmp_path / "nope.md")])
        assert result.exit_code != 0
