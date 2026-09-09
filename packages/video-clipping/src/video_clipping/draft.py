"""`clip draft` — orchestrates the free pre-pass and writes plan.json.

No paid calls. The projected LLM cost is derived from the candidate frame budget
and the Sonnet 4.6 input price read directly from `agent_runtime.budget._PRICING`
(single source of truth — no local mirror).
"""

from __future__ import annotations

import hashlib
import json
from math import ceil
from pathlib import Path

from agent_runtime.budget import _PRICING
from agent_runtime.config import get_config
from ulid import ULID

from video_clipping.constants import (
    AGENT_SUBDIR,
    COST_PROJECTION_MODEL_ID,
    FRAME_SAMPLE_INTERVAL_SEC,
    IMAGE_TOKENS_PER_FRAME_ESTIMATE,
    MAX_FRAMES_PER_SEGMENT,
    TEXT_TOKENS_PER_SEGMENT_ESTIMATE,
)
from video_clipping.models import CostEstimate, Run, Segment, Spec
from video_clipping.prepass import run_prepass


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while data := fh.read(chunk):
            h.update(data)
    return h.hexdigest()


def _project_cost(segments: list[Segment]) -> CostEstimate:
    frames = 0
    for seg in segments:
        per_seg = min(
            max(1, ceil(seg.duration / FRAME_SAMPLE_INTERVAL_SEC)),
            MAX_FRAMES_PER_SEGMENT,
        )
        frames += per_seg
    projected_input_tokens = (
        frames * IMAGE_TOKENS_PER_FRAME_ESTIMATE
        + len(segments) * TEXT_TOKENS_PER_SEGMENT_ESTIMATE
    )
    input_price = _PRICING[COST_PROJECTION_MODEL_ID]["input"]  # USD per 1M tokens
    projected_usd = projected_input_tokens / 1_000_000 * input_price
    return CostEstimate(
        frames_to_send=frames,
        projected_input_tokens=projected_input_tokens,
        projected_usd=projected_usd,
        pricing_model_id=COST_PROJECTION_MODEL_ID,
        pricing_input_usd_per_mtok=input_price,
    )


class DraftResult:
    def __init__(self, run: Run, plan_path: Path) -> None:
        self.run = run
        self.plan_path = plan_path


def draft_sync(
    video: Path,
    spec_path: Path,
    outputs_root: Path | None = None,
) -> DraftResult:
    """Run the pre-pass, project cost, write plan.json under agent_data_dir."""
    video = Path(video).expanduser().resolve()
    spec = Spec.from_yaml(Path(spec_path))

    prepass = run_prepass(video, spec)
    cost = _project_cost(prepass.segments)

    run_id = str(ULID())
    run = Run(
        run_id=run_id,
        spec=spec,
        video_sha256=_sha256_file(video),
        prepass_metrics=prepass.prepass_metrics,
        segments=prepass.segments,
        scene_detection=prepass.scene_detection,
        cost_estimate=cost,
    )

    if outputs_root is None:
        outputs_root = get_config().agent_data_dir / AGENT_SUBDIR / "outputs"
    run_dir = Path(outputs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "plan.json"
    plan_path.write_text(
        json.dumps(run.to_payload(), indent=2, default=str),
        encoding="utf-8",
    )
    return DraftResult(run=run, plan_path=plan_path)
