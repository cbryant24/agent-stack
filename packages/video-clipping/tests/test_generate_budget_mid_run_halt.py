"""Mid-run cap breach: BudgetTracker.check_budget raises → status="partial", partial results kept."""

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
        "\n".join([
            f"video: {video}",
            "location: Synthetic",
            "event_type: hike",
            "target_clip_length_sec: [1, 8]",
            "max_total_output_min: 1.0",
            "content_wanted: [dynamic scenes]",
            "exclude_when: [theme_mismatch]",
        ]),
        encoding="utf-8",
    )
    return path


def _decide_json(action: str, start: float, end: float, summary: str) -> str:
    return json.dumps({
        "action": action, "refined_start": start, "refined_end": end,
        "exclude_reason": None, "theme_match": 0.8, "confidence": 0.8,
        "one_line_summary": summary,
    })


@requires_ffmpeg
def test_mid_run_cap_yields_partial_status_and_partial_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    from video_clipping.plan import load_plan
    plan = load_plan(plan_path)
    n = len(plan.segments)
    if n < 2:
        pytest.skip(f"synthetic prepass produced only {n} segment(s); mid-run halt test needs ≥2")

    monkeypatch.setattr(
        "video_clipping.audio.transcribe._load_model",
        lambda name: FakeWhisperModel(
            segments=[FakeWhisperSegment(start=0.0, end=9.0, text="sample")],
            duration=9.0,
        ),
    )
    monkeypatch.setattr("video_clipping.audio.transcribe.WHISPER_BACKOFF_SEC", 0.0)

    # First segment: cheap vision + cheap decide → include (accepted, gets cut).
    # Second segment: massive vision (2M input tokens = $6 at Sonnet) → tracker.check_budget()
    # will refuse the NEXT iteration once cost exceeds cap.
    responses = [
        FakeCompletion(text="scene one", input_tokens=100, output_tokens=20),
        FakeCompletion(text=_decide_json("include", plan.segments[0].start,
                                         plan.segments[0].end, "scene one included")),
        FakeCompletion(text="scene two", input_tokens=2_000_000, output_tokens=20),
        FakeCompletion(text=_decide_json("include", plan.segments[1].start,
                                         plan.segments[1].end, "scene two included")),
    ]
    for i in range(2, n):
        responses.append(FakeCompletion(text="cheap"))
        responses.append(FakeCompletion(text=_decide_json(
            "include", plan.segments[i].start, plan.segments[i].end, f"unreached {i}"
        )))

    provider = FakeProvider(responses=responses)
    monkeypatch.setattr("video_clipping.generate.get_provider", lambda: provider)
    monkeypatch.setattr(
        "video_clipping.similarity.embed.get_embedding_client",
        lambda: FakeEmbedder(),
    )

    gen_res = runner.invoke(
        cli, ["generate", str(plan_path), "--max-usd", "5.00", "--yes"],
        catch_exceptions=False,
    )
    assert gen_res.exit_code == 0, gen_res.stderr

    run = load_run(plan_path.parent / "run.json")
    assert run.status == "partial"
    assert run.halted_reason
    include_count = sum(1 for d in run.decisions if d.action in ("include", "trim"))
    assert include_count == 2
    assert run.actual_cost_usd is not None
    assert run.actual_cost_usd >= 5.00
    assert len(run.clip_paths) == include_count
