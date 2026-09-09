from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from video_clipping.cli import cli
from video_clipping.models import Spec


def test_spec_init_writes_parseable_yaml(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "spec.yaml"
    result = runner.invoke(cli, ["spec", "init", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()

    spec = Spec.from_yaml(out)
    assert spec.target_clip_length_sec == (15.0, 60.0)
    assert "low_video_quality" in spec.exclude_when
    assert spec.location  # non-empty


def test_spec_init_refuses_overwrite(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "spec.yaml"
    out.write_text("existing: true\n")
    result = runner.invoke(cli, ["spec", "init", "-o", str(out)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_spec_init_force_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "spec.yaml"
    out.write_text("existing: true\n")
    result = runner.invoke(cli, ["spec", "init", "-o", str(out), "--force"])
    assert result.exit_code == 0, result.output
    assert "location:" in out.read_text()
