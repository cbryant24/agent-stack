"""Pre-pass pipeline orchestrator.

Runs ffprobe, silencedetect, both scene detectors (in parallel), the loudness
pass per candidate window, and the length filter — returns the pieces the draft
step assembles into a `Run`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from video_clipping.models import PrepassMetrics, Segment, Spec
from video_clipping.prepass.loudness import mean_loudness_lufs
from video_clipping.prepass.merge import build_candidate_segments
from video_clipping.prepass.probe import probe
from video_clipping.prepass.scenes_pyscenedetect import detect_scenes_pyscenedetect
from video_clipping.prepass.scenes_scdet import detect_scenes_scdet
from video_clipping.prepass.silence import detect_silences


class PrepassResult:
    """Bundle of everything the pre-pass produces."""

    def __init__(
        self,
        prepass_metrics: PrepassMetrics,
        segments: list[Segment],
        scene_detection: dict[str, list[tuple[float, float]]],
    ) -> None:
        self.prepass_metrics = prepass_metrics
        self.segments = segments
        self.scene_detection = scene_detection


def run_prepass(video: Path, spec: Spec) -> PrepassResult:
    metrics = probe(video)

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_silence = pool.submit(detect_silences, video)
        fut_pyscene = pool.submit(detect_scenes_pyscenedetect, video)
        fut_scdet = pool.submit(detect_scenes_scdet, video, metrics.duration_sec)
        silences = fut_silence.result()
        pyscene_scenes = fut_pyscene.result()
        scdet_scenes = fut_scdet.result()

    segments, union_ranges = build_candidate_segments(
        duration_sec=metrics.duration_sec,
        silences=silences,
        pyscenedetect_scenes=pyscene_scenes,
        scdet_scenes=scdet_scenes,
        target_clip_length_sec=spec.target_clip_length_sec,
    )

    for seg in segments:
        seg.mean_loudness_lufs = mean_loudness_lufs(video, seg.start, seg.duration)

    scene_detection = {
        "pyscenedetect": pyscene_scenes,
        "scdet": scdet_scenes,
        "union": union_ranges,
    }
    return PrepassResult(
        prepass_metrics=metrics,
        segments=segments,
        scene_detection=scene_detection,
    )
