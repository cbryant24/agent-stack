from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from visual_generation.cli import cli
from visual_generation.models import (
    DraftResult,
    GenerationResult,
    VisualResult,
    VisualSpec,
)


# ── draft ────────────────────────────────────────────────────────────────────


def test_cli_draft_shows_spec_lessons_missing_models_and_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = VisualSpec(spec_id="spec-1", prompt="a wolf in neon rain",
                      settings={"steps": 20}, model="flux1-dev.safetensors", identity_bearing=True)
    result = DraftResult(
        spec=spec, batch_path=Path("/tmp/p.batch.md"), template_name="flux-txt2img",
        tutor_notes=["CFG>7 washes skin on flux1-dev."],
        missing_models=["ae.safetensors"], research_offer="WAN VACE trick",
        overall_reasoning="guidance 3.5 keeps it crisp",
    )
    monkeypatch.setattr("visual_generation.cli.draft_sync", lambda *a, **k: result)

    out = CliRunner().invoke(cli, ["draft", "a wolf in neon rain"])
    assert out.exit_code == 0, out.output
    assert "a wolf in neon rain" in out.output
    assert "identity-bearing" in out.output
    assert "washes skin" in out.output           # tutor note
    assert "ae.safetensors" in out.output         # missing-model advisory
    assert "research" in out.output.lower()        # gap → research offer (not run)


def test_cli_draft_from_sets_source_and_shows_refining(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_draft_sync(intent, **kwargs):
        captured.update(kwargs)
        spec = VisualSpec(
            spec_id="spec-2", prompt="warmer key light",
            source=kwargs["source"], settings={"denoise": kwargs.get("denoise") or 0.5},
        )
        return DraftResult(spec=spec, batch_path=Path("/tmp/p.batch.md"), template_name="z-img2img")

    monkeypatch.setattr("visual_generation.cli.draft_sync", fake_draft_sync)

    out = CliRunner().invoke(
        cli, ["draft", "warmer key light", "--from", "gen-parent", "--denoise", "0.6"]
    )
    assert out.exit_code == 0, out.output
    assert captured["source"].from_generation == "gen-parent"
    assert captured["denoise"] == 0.6
    assert "Refining" in out.output and "gen-parent" in out.output


def test_cli_draft_from_and_image_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.draft_sync", lambda *a, **k: None)
    out = CliRunner().invoke(
        cli, ["draft", "x", "--from", "gen-1", "--image", "/tmp/ref.png"]
    )
    assert out.exit_code != 0
    assert "only one of --from / --image" in out.output


def test_cli_draft_mask_without_source_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.draft_sync", lambda *a, **k: None)
    out = CliRunner().invoke(cli, ["draft", "x", "--mask", "/tmp/m.png"])
    assert out.exit_code != 0
    assert "--mask requires a source" in out.output


# ── generate ─────────────────────────────────────────────────────────────────


def _fake_plan() -> SimpleNamespace:
    return SimpleNamespace(
        plans=[SimpleNamespace(warnings=[])],
        skipped=[],
        per_run_estimate_usd=0.05,
        estimate_source="default",
        estimated_session_cost_usd=0.05,
        gpu_rate_usd_per_hr=3.0,
    )


def _fake_result(drained: bool = True) -> GenerationResult:
    return GenerationResult(
        results=[VisualResult(generation_id="gen-123456789012", spec_id="spec-1",
                              asset_path="/x/assets/proj/gen.png", gpu_cost_usd=0.05,
                              session_cost_running_usd=0.05, rationale="crisp flux still")],
        run_id="r1", status="completed", items_processed=1, session_cost_usd=0.05, drained=drained,
    )


def test_cli_generate_gate_and_stop_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    batch = tmp_path / "p.batch.md"
    batch.write_text("<!-- vg-batch: {} -->\n\n## s\n\nbody\n", encoding="utf-8")

    monkeypatch.setattr("visual_generation.cli.plan_generation_sync", lambda *a, **k: _fake_plan())
    monkeypatch.setattr("visual_generation.cli.spend_generation_sync", lambda *a, **k: _fake_result())

    out = CliRunner().invoke(
        cli, ["generate", str(batch), "--all", "--endpoint", "http://pod:8188", "--yes"]
    )
    assert out.exit_code == 0, out.output
    # Soft-inform gate.
    assert "GPU cost gate" in out.output
    assert "Est. session cost" in out.output
    assert "(default)" in out.output
    # The FULL gen id (not a 12-char prefix) + a ready, agent-prefixed report command — so the
    # echoed value can be pasted straight into `report` (it does an exact point-id lookup).
    assert "gen-123456789012" in out.output
    assert "agent visual-generation report gen-123456789012 --reaction" in out.output
    assert "<loved|liked|" in out.output  # reaction vocabulary is filled in
    # Drain → stop-prompt + idle warning (advisory; no RunPod stop).
    assert "Batch drained" in out.output
    assert "Stop your pod" in out.output
    assert "Idle warning" in out.output


def test_cli_generate_prints_skip_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    batch = tmp_path / "p.batch.md"
    batch.write_text("<!-- vg-batch: {} -->\n\n## s\n\nbody\n", encoding="utf-8")

    result = _fake_result()
    result.skipped = ["spec-9"]
    result.skip_reasons = [
        "Skipped spec-9: this workflow can't do img2img/inpaint (no init_image slot) "
        "— use an img2img/inpaint template"
    ]
    monkeypatch.setattr("visual_generation.cli.plan_generation_sync", lambda *a, **k: _fake_plan())
    monkeypatch.setattr("visual_generation.cli.spend_generation_sync", lambda *a, **k: result)

    out = CliRunner().invoke(
        cli, ["generate", str(batch), "--all", "--endpoint", "http://pod:8188", "--yes"]
    )
    assert out.exit_code == 0, out.output
    assert "no init_image slot" in out.output  # the plain-language reason, not a bare id


def test_cli_generate_gate_can_be_declined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    batch = tmp_path / "p.batch.md"
    batch.write_text("<!-- vg-batch: {} -->\n\n## s\n\nbody\n", encoding="utf-8")
    spent = {"called": False}

    def _spend(*a, **k):
        spent["called"] = True
        return _fake_result()

    monkeypatch.setattr("visual_generation.cli.plan_generation_sync", lambda *a, **k: _fake_plan())
    monkeypatch.setattr("visual_generation.cli.spend_generation_sync", _spend)

    # No --yes; answer "n" at the gate → abort before spending.
    out = CliRunner().invoke(
        cli, ["generate", str(batch), "--all", "--endpoint", "http://pod:8188"], input="n\n"
    )
    assert out.exit_code != 0
    assert spent["called"] is False


# ── report ───────────────────────────────────────────────────────────────────


def test_cli_report_records(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = VisualSpec(prompt="x")  # only needs to be non-None for the CLI's found-check
    monkeypatch.setattr("visual_generation.cli.report_sync", lambda *a, **k: gen)
    out = CliRunner().invoke(cli, ["report", "gen-123456789012", "--reaction", "loved", "--rating", "5"])
    assert out.exit_code == 0, out.output
    assert "Recorded" in out.output
    assert "loved" in out.output


def test_cli_report_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("visual_generation.cli.report_sync", lambda *a, **k: None)
    out = CliRunner().invoke(cli, ["report", "missing", "--reaction", "liked"])
    assert out.exit_code != 0
    assert "not found" in out.output
