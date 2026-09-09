"""Merge silence + union(scene) boundaries → candidate segments with length flags."""

from __future__ import annotations

from video_clipping.constants import LENGTH_TOLERANCE_SEC
from video_clipping.models import DetectorLabel, LengthStatus, Segment


def _union_cut_times(
    pyscenedetect: list[tuple[float, float]],
    scdet: list[tuple[float, float]],
) -> list[tuple[float, DetectorLabel]]:
    """Extract cut *times* (scene starts, excluding 0) from both detectors with provenance."""
    tagged: list[tuple[float, DetectorLabel]] = []
    for start, _end in pyscenedetect:
        if start > 0:
            tagged.append((start, "pyscenedetect"))
    for start, _end in scdet:
        if start > 0:
            tagged.append((start, "scdet"))
    return tagged


def _bucket_cuts(
    tagged: list[tuple[float, DetectorLabel]],
    tolerance_sec: float = 0.25,
) -> list[tuple[float, list[DetectorLabel]]]:
    """Collapse near-duplicate cuts (within tolerance) into one, keeping all provenance labels."""
    if not tagged:
        return []
    tagged_sorted = sorted(tagged, key=lambda p: p[0])
    buckets: list[tuple[float, list[DetectorLabel]]] = []
    for t, label in tagged_sorted:
        if buckets and (t - buckets[-1][0]) <= tolerance_sec:
            if label not in buckets[-1][1]:
                buckets[-1][1].append(label)
        else:
            buckets.append((t, [label]))
    return buckets


def _classify_length(
    duration: float,
    target: tuple[float, float],
    tolerance: float,
) -> tuple[LengthStatus, bool]:
    """Return (length_status, keep?)."""
    lo, hi = target
    if lo <= duration <= hi:
        return "ok", True
    if (lo - tolerance) <= duration < lo:
        return "near_miss_short", True
    if hi < duration <= (hi + tolerance):
        return "near_miss_long", True
    return "ok", False  # length_status irrelevant when dropped


def build_candidate_segments(
    duration_sec: float,
    silences: list[tuple[float, float]],
    pyscenedetect_scenes: list[tuple[float, float]],
    scdet_scenes: list[tuple[float, float]],
    target_clip_length_sec: tuple[float, float],
    tolerance_sec: float = LENGTH_TOLERANCE_SEC,
) -> tuple[list[Segment], list[tuple[float, float]]]:
    """Assemble candidate segments from silence + union(visual) boundaries.

    Returns (segments, union_scene_ranges). Boundaries are: every union'd visual
    cut, plus every silence start/end, plus 0 and duration. Each resulting window
    becomes one candidate; its detector_provenance lists which detectors put the
    boundaries on either side, plus "silence" if the window sits between silence
    edges.
    """
    tagged_cuts = _bucket_cuts(_union_cut_times(pyscenedetect_scenes, scdet_scenes))
    visual_cut_times = [t for t, _ in tagged_cuts]
    cut_labels: dict[float, list[DetectorLabel]] = {t: labels for t, labels in tagged_cuts}

    silence_edges: list[float] = []
    for s, e in silences:
        silence_edges.extend([s, e])

    boundaries = sorted({0.0, duration_sec, *visual_cut_times, *silence_edges})
    boundaries = [b for b in boundaries if 0.0 <= b <= duration_sec]

    silence_ranges = silences

    def _in_silence(mid: float) -> bool:
        return any(s <= mid <= e for s, e in silence_ranges)

    segments: list[Segment] = []
    for start, end in zip(boundaries, boundaries[1:]):
        dur = end - start
        if dur <= 0:
            continue
        # Drop windows that are entirely inside a silent region — they're by
        # definition uninteresting for a highlight reel.
        mid = (start + end) / 2
        if _in_silence(mid):
            continue

        status, keep = _classify_length(dur, target_clip_length_sec, tolerance_sec)
        if not keep:
            continue

        provenance: list[DetectorLabel] = []
        for edge in (start, end):
            for label in cut_labels.get(edge, []):
                if label not in provenance:
                    provenance.append(label)
        # If the window abuts a silence edge, tag silence.
        if any(edge in silence_edges for edge in (start, end)):
            if "silence" not in provenance:
                provenance.append("silence")

        segments.append(
            Segment(
                start=start,
                end=end,
                duration=dur,
                detector_provenance=provenance,
                length_status=status,
            )
        )

    # Union scene ranges: rebuild from union cut times (for the plan JSON's
    # scene_detection.union field).
    union_ranges: list[tuple[float, float]] = []
    prev = 0.0
    for t in visual_cut_times:
        if t > prev:
            union_ranges.append((prev, t))
        prev = t
    if duration_sec > prev:
        union_ranges.append((prev, duration_sec))

    return segments, union_ranges
