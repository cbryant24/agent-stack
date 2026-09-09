"""CLI signature guards.

`explain` is fully implemented in Phase 2 (see test_explain.py). `generate` and
`report` are tested end-to-end in test_generate_*.py and test_report_render.py.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from video_clipping.cli import cli


def test_generate_requires_existing_plan(tmp_path: Path) -> None:
    """click.Path(exists=True) turns a missing file into a usage error (exit 2)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(tmp_path / "does-not-exist.json")])
    assert result.exit_code == 2
