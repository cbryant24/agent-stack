from __future__ import annotations

import json
from pathlib import Path


from tests.conftest import requires_ffmpeg
from tests.fixtures.generate_synthetic_video import generate as generate_synthetic_video
from video_clipping import Run, draft_sync


def _write_spec(video: Path, spec_path: Path) -> None:
    spec_path.write_text(
        "video: " + str(video) + "\n"
        "location: synthetic\n"
        "event_type: test\n"
        # Widen the window so a segment on the 9-second synthetic clip actually survives.
        "target_clip_length_sec: [1, 10]\n"
        "max_total_output_min: 1\n"
        "content_wanted:\n  - anything\n"
        "exclude_when:\n  - low_video_quality\n"
    )


@requires_ffmpeg
def test_draft_end_to_end_writes_valid_plan(tmp_path: Path) -> None:
    video = generate_synthetic_video(tmp_path / "sample.mp4")
    spec_path = tmp_path / "spec.yaml"
    _write_spec(video, spec_path)

    outputs = tmp_path / "outputs"
    result = draft_sync(video=video, spec_path=spec_path, outputs_root=outputs)

    assert result.plan_path.exists()
    raw = json.loads(result.plan_path.read_text())

    # Round-trips through the Pydantic schema.
    run = Run.from_payload(raw)
    assert run.spec.location == "synthetic"
    assert run.prepass_metrics.duration_sec > 0
    assert run.prepass_metrics.resolution == (320, 240)
    assert set(run.scene_detection) == {"pyscenedetect", "scdet", "union"}
    assert run.cost_estimate.pricing_model_id == "claude-sonnet-4-6"
    assert run.cost_estimate.pricing_input_usd_per_mtok > 0
    # projected_usd may be $0 if zero segments survived the length filter; that's OK.
    assert run.cost_estimate.projected_usd >= 0
    # But there should be at least one candidate segment on this synthetic clip.
    assert run.segments, "expected at least one candidate segment"
