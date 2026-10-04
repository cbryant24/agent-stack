from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from visual_generation.cli import cli
from visual_generation.quick import QuickResult, QuickSeedUnmapped, QuickTemplateNotFound


def _result(**overrides) -> QuickResult:
    base = dict(
        asset_path=Path("/tmp/adhoc/x.png"),
        template_name="visual-workflow",
        seed=42,
        endpoint="http://pod:8188",
        elapsed_sec=1.5,
        estimated_cost_usd=0.001,
        video=False,
    )
    base.update(overrides)
    return QuickResult(**base)


def test_quick_still_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake(prompt: str, **kwargs):
        seen["prompt"] = prompt
        seen["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", fake)

    result = CliRunner().invoke(
        cli, ["quick", "a wolf in neon rain", "--endpoint", "http://pod:8188", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert seen["prompt"] == "a wolf in neon rain"
    assert seen["kwargs"]["video"] is False
    assert "Not recorded to visual_generation_memory" in result.output


def test_quick_video_happy_path_shows_video_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "visual_generation.cli.quick_generate_sync",
        lambda prompt, **k: _result(video=True, asset_path=Path("/tmp/adhoc/x.mp4")),
    )

    result = CliRunner().invoke(
        cli, ["quick", "a fox in snow", "--endpoint", "http://pod:8188", "--video", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert "more GPU time" in result.output


def test_quick_image_flag_without_video_is_a_usage_error(tmp_path: Path) -> None:
    seed = tmp_path / "seed.png"
    seed.write_bytes(b"x")
    result = CliRunner().invoke(
        cli, ["quick", "x", "--endpoint", "x", "--image", str(seed), "--yes"]
    )
    assert result.exit_code != 0
    assert "--image requires --video" in result.output


def test_quick_still_only_flags_rejected_with_video(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", lambda prompt, **k: _result())
    result = CliRunner().invoke(
        cli, ["quick", "x", "--endpoint", "x", "--video", "--steps", "20", "--yes"]
    )
    assert result.exit_code != 0
    assert "--video" in result.output


def test_quick_lora_rejected_with_video(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", lambda prompt, **k: _result())
    result = CliRunner().invoke(
        cli, ["quick", "x", "--endpoint", "x", "--video", "--lora", "char.safetensors:0.8", "--yes"]
    )
    assert result.exit_code != 0
    assert "--lora not supported with --video" in result.output


def test_quick_template_not_found_is_a_clean_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raiser(prompt, **k):
        raise QuickTemplateNotFound("No workflow template named 'ghost' is registered.")

    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", raiser)
    result = CliRunner().invoke(cli, ["quick", "x", "--endpoint", "x", "--yes"])
    assert result.exit_code != 0
    assert "ghost" in result.output


def test_quick_prompts_for_confirmation_without_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", lambda prompt, **k: _result())
    result = CliRunner().invoke(cli, ["quick", "x", "--endpoint", "x"], input="n\n")
    assert result.exit_code != 0  # aborted
    assert "Submit 1 image generation" in result.output


def test_quick_warns_when_a_requested_value_has_no_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "visual_generation.cli.quick_generate_sync", lambda prompt, **k: _result(unmapped=["negative"])
    )
    result = CliRunner().invoke(cli, ["quick", "x", "--endpoint", "x", "--yes"])
    assert result.exit_code == 0, result.output
    assert "visual-workflow" in result.output and "no slot for: negative" in result.output
    assert "will NOT affect the render" in result.output


def test_quick_prints_no_unmapped_warning_when_everything_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", lambda prompt, **k: _result())
    result = CliRunner().invoke(cli, ["quick", "x", "--endpoint", "x", "--yes"])
    assert result.exit_code == 0, result.output
    assert "no slot for" not in result.output


def test_quick_unmapped_seed_is_a_clean_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raiser(prompt, **k):
        raise QuickSeedUnmapped("template 'ghost' has no seed slot, so seed 5 can't be applied.")

    monkeypatch.setattr("visual_generation.cli.quick_generate_sync", raiser)
    result = CliRunner().invoke(cli, ["quick", "x", "--endpoint", "x", "--yes"])
    assert result.exit_code != 0
    assert "no seed slot" in result.output
