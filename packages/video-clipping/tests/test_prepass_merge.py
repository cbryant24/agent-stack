from __future__ import annotations

from video_clipping.prepass.merge import build_candidate_segments


def test_merge_flags_near_miss_short() -> None:
    # Duration 20s; target window [15, 60]; a 13s segment lands in the tolerance band.
    segments, union = build_candidate_segments(
        duration_sec=20.0,
        silences=[],
        pyscenedetect_scenes=[(0.0, 13.0), (13.0, 20.0)],
        scdet_scenes=[(0.0, 13.0), (13.0, 20.0)],
        target_clip_length_sec=(15.0, 60.0),
        tolerance_sec=3.0,
    )
    # 13s segment sits at [0, 13) → near_miss_short (within 3s of the 15s floor).
    near_miss = [s for s in segments if s.length_status == "near_miss_short"]
    assert near_miss, f"expected a near_miss_short segment, got: {[s.model_dump() for s in segments]}"
    assert union  # union computed


def test_merge_drops_hard_out_of_range() -> None:
    segments, _ = build_candidate_segments(
        duration_sec=100.0,
        silences=[],
        pyscenedetect_scenes=[(0.0, 100.0)],
        scdet_scenes=[(0.0, 100.0)],
        target_clip_length_sec=(15.0, 60.0),
        tolerance_sec=3.0,
    )
    # Single 100s segment is far outside [15, 60] and beyond the 3s tolerance.
    assert segments == []


def test_merge_dedupes_detector_provenance() -> None:
    # Both detectors call a cut at t=10; the resulting boundary should carry both labels.
    segments, _ = build_candidate_segments(
        duration_sec=50.0,
        silences=[],
        pyscenedetect_scenes=[(0.0, 10.0), (10.0, 50.0)],
        scdet_scenes=[(0.0, 10.05), (10.05, 50.0)],  # near-duplicate cut
        target_clip_length_sec=(15.0, 60.0),
        tolerance_sec=3.0,
    )
    # The 40s window [10, 50) should exist and have both detectors on its start boundary.
    matching = [s for s in segments if 9.5 < s.start < 10.5 and 39.5 < s.duration < 40.5]
    assert matching, f"expected a segment starting near 10s; got: {[s.model_dump() for s in segments]}"
    seg = matching[0]
    assert "pyscenedetect" in seg.detector_provenance
    assert "scdet" in seg.detector_provenance


def test_merge_labels_silence_edges() -> None:
    segments, _ = build_candidate_segments(
        duration_sec=60.0,
        silences=[(20.0, 25.0)],
        pyscenedetect_scenes=[(0.0, 60.0)],
        scdet_scenes=[(0.0, 60.0)],
        target_clip_length_sec=(15.0, 60.0),
        tolerance_sec=3.0,
    )
    # Silence at [20, 25) carves the video into two windows: [0, 20) and [25, 60);
    # both should carry the "silence" provenance label.
    for seg in segments:
        assert "silence" in seg.detector_provenance, seg.model_dump()
