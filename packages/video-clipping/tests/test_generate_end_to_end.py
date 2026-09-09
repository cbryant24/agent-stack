from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import requires_ffmpeg
from tests.fakes import (
    FakeCompletion,
    FakeEmbedder,
    FakeProvider,
    FakeWhisperModel,
    FakeWhisperSegment,
)
from tests.fixtures.generate_synthetic_video import generate as generate_video
from video_clipping.cli import cli
from video_clipping.plan import load_run


def _make_spec_yaml(path: Path, video: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                f"video: {video}",
                "location: Synthetic hillside",
                "event_type: hike",
                "target_clip_length_sec: [1, 8]",
                "max_total_output_min: 1.0",
                "content_wanted:",
                "  - dynamic scenes",
                "  - test patterns",
                "exclude_when: [low_video_quality, theme_mismatch]",
                "tone_notes: observational",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    monkeypatch.setattr("video_clipping.generate.get_provider", lambda: provider)


def _patch_embedder(monkeypatch: pytest.MonkeyPatch, embedder: FakeEmbedder) -> None:
    monkeypatch.setattr(
        "video_clipping.similarity.embed.get_embedding_client",
        lambda: embedder,
    )


def _patch_whisper(monkeypatch: pytest.MonkeyPatch, model: FakeWhisperModel) -> None:
    monkeypatch.setattr(
        "video_clipping.audio.transcribe._load_model",
        lambda name: model,
    )
    monkeypatch.setattr("video_clipping.audio.transcribe.WHISPER_BACKOFF_SEC", 0.0)


def _decide_json(action: str, start: float, end: float, summary: str,
                 exclude_reason: str | None = None) -> str:
    return json.dumps({
        "action": action,
        "refined_start": start,
        "refined_end": end,
        "exclude_reason": exclude_reason,
        "theme_match": 0.7 if action != "exclude" else 0.2,
        "confidence": 0.8,
        "one_line_summary": summary,
    })


def _vision_reply(text: str = "wide test pattern with sine tone") -> FakeCompletion:
    return FakeCompletion(text=text, input_tokens=200, output_tokens=30)


@requires_ffmpeg
def test_generate_end_to_end_writes_clips_and_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = generate_video(tmp_path / "sample.mp4")
    spec_path = _make_spec_yaml(tmp_path / "spec.yaml", video)

    runner = CliRunner()
    draft_res = runner.invoke(
        cli, ["draft", str(video), "--spec", str(spec_path)], catch_exceptions=False
    )
    assert draft_res.exit_code == 0, draft_res.stderr

    from agent_runtime import get_config

    outputs_root = get_config().agent_data_dir / "video-clipping" / "outputs"
    run_dirs = list(outputs_root.iterdir())
    assert len(run_dirs) == 1
    plan_path = run_dirs[0] / "plan.json"
    assert plan_path.exists()

    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)
    n = len(plan.segments)
    assert n >= 1

    _patch_whisper(monkeypatch, FakeWhisperModel(
        segments=[FakeWhisperSegment(start=0.0, end=9.0, text="synthetic narration")],
        duration=9.0,
    ))

    # Alternate include / exclude so we exercise both paths without any trim math
    # (which is brittle against tiny near-miss prepass segments).
    responses: list[FakeCompletion] = []
    for i, seg in enumerate(plan.segments):
        responses.append(_vision_reply(f"scene {i}"))
        if i % 2 == 0:
            responses.append(FakeCompletion(text=_decide_json(
                "include", seg.start, seg.end, f"scene {i} kept"
            )))
        else:
            responses.append(FakeCompletion(text=_decide_json(
                "exclude", seg.start, seg.end, f"scene {i} skipped",
                exclude_reason="theme_mismatch",
            )))
    _patch_provider(monkeypatch, FakeProvider(responses=responses))
    _patch_embedder(monkeypatch, FakeEmbedder())

    gen_res = runner.invoke(
        cli, ["generate", str(plan_path), "--max-usd", "5.0", "--yes"],
        catch_exceptions=False,
    )
    assert gen_res.exit_code == 0, gen_res.stderr

    run_json = plan_path.parent / "run.json"
    assert run_json.exists()
    run = load_run(run_json)
    assert run.status == "completed"
    accepted = [d for d in run.decisions if d.action in ("include", "trim")]
    assert len(accepted) >= 1
    assert len(run.clip_paths) == len(accepted)
    for p in run.clip_paths:
        assert Path(p).exists() and Path(p).stat().st_size > 0


@requires_ffmpeg
def test_generate_dry_run_skips_paid_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run: no LLM/Voyage/Whisper is called, but clips are still produced."""
    video = generate_video(tmp_path / "sample.mp4")
    spec_path = _make_spec_yaml(tmp_path / "spec.yaml", video)

    runner = CliRunner()
    draft_res = runner.invoke(
        cli, ["draft", str(video), "--spec", str(spec_path)], catch_exceptions=False
    )
    assert draft_res.exit_code == 0

    from agent_runtime import get_config

    outputs_root = get_config().agent_data_dir / "video-clipping" / "outputs"
    plan_path = next(outputs_root.iterdir()) / "plan.json"

    def boom(*_a, **_kw):
        raise AssertionError("dry-run must not touch paid boundaries")

    monkeypatch.setattr("video_clipping.audio.transcribe._load_model", boom)
    monkeypatch.setattr("video_clipping.generate.get_provider", boom)
    monkeypatch.setattr(
        "video_clipping.similarity.embed.get_embedding_client", boom
    )

    gen_res = runner.invoke(
        cli, ["generate", str(plan_path), "--dry-run", "--yes"],
        catch_exceptions=False,
    )
    assert gen_res.exit_code == 0, gen_res.stderr

    run = load_run(plan_path.parent / "run.json")
    assert run.status == "completed"
    assert run.actual_cost_usd == 0.0
    assert len(run.clip_paths) == len(run.segments)
