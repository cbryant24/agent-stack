"""Fail-fast -o validation: a bad output path errors at parse time (before any
identification, gate, or paid delegation), and a directory target is accepted."""
from __future__ import annotations

import click
import pytest

from technique_research import agent
from technique_research.cli import _validate_output
from technique_research.models import TechniqueReport


def test_validate_output_accepts_existing_directory(tmp_path) -> None:
    assert _validate_output(None, None, tmp_path) == tmp_path


def test_validate_output_creates_missing_parent(tmp_path) -> None:
    target = tmp_path / "nested" / "deeper" / "report.md"
    out = _validate_output(None, None, target)
    assert out == target
    assert target.parent.is_dir()  # parent made usable up front


def test_validate_output_rejects_path_under_a_file(tmp_path) -> None:
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("x", encoding="utf-8")
    # Parent of the target is a regular file → cannot be a directory → fail fast.
    with pytest.raises(click.BadParameter):
        _validate_output(None, None, a_file / "report.md")


def test_validate_output_passthrough_none() -> None:
    assert _validate_output(None, None, None) is None


def test_write_report_into_directory_uses_default_filename(tmp_path) -> None:
    report = TechniqueReport(goal="A Punchy AMV")
    out = agent._write_report(report, tmp_path, config=None)
    # Written INTO the directory under the slugged default name — never an
    # IsADirectoryError at the final write.
    assert out.parent == tmp_path
    assert out.name == report.default_filename()
    assert out.read_text(encoding="utf-8").startswith("---")


def test_write_report_explicit_file_path(tmp_path) -> None:
    report = TechniqueReport(goal="g")
    target = tmp_path / "sub" / "mine.md"
    out = agent._write_report(report, target, config=None)
    assert out == target and out.is_file()
