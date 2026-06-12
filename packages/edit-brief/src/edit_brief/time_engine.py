"""The time engine — pure, deterministic, fully unit-tested, no I/O.

All timing in the brief is computed HERE, never by the LLM. Two functions:

  section_timestamps  — cumulative section start/end from VO durations (+ gap),
                        falling back to a word-count estimate per section.
  build_beat_grid     — beat = 60/BPM, bar = 4 beats, nearest-beat proposals at
                        each section boundary.

The LLM later places retrieved recommendations *against* these numbers; it never
produces or alters one.
"""
from __future__ import annotations

from edit_brief.models import BeatGrid, BeatProposal, TimelineRow


def section_timestamps(
    sections: list[tuple[str, str]],
    *,
    durations: list[float | None],
    word_counts: list[int],
    gap: float,
    words_per_sec: float,
) -> list[TimelineRow]:
    """Compute cumulative section start/end timestamps.

    `sections` is a list of (section_id, heading), parallel to `durations` and
    `word_counts`. A section's length is its ffprobe VO duration when present;
    otherwise `word_count / words_per_sec`, marked timing_source="estimate". A
    `gap` of breathing room is inserted *between* sections (not before the first,
    not after the last).
    """
    if not (len(sections) == len(durations) == len(word_counts)):
        raise ValueError("sections, durations, word_counts must be the same length")
    if words_per_sec <= 0:
        raise ValueError("words_per_sec must be positive")

    rows: list[TimelineRow] = []
    cursor = 0.0
    for i, ((section_id, heading), dur, words) in enumerate(
        zip(sections, durations, word_counts)
    ):
        if i > 0:
            cursor += gap
        if dur is not None:
            length = dur
            source = "vo"
        else:
            length = words / words_per_sec
            source = "estimate"
        start = cursor
        end = start + length
        cursor = end
        rows.append(
            TimelineRow(
                section_id=section_id,
                heading=heading,
                start_sec=round(start, 3),
                end_sec=round(end, 3),
                timing_source=source,  # type: ignore[arg-type]
            )
        )
    return rows


def _nearest(value: float, unit: float) -> float:
    return round(round(value / unit) * unit, 3)


def build_beat_grid(
    bpm: int | None,
    boundaries: list[tuple[str, float]],
    *,
    track_duration: float | None = None,
) -> BeatGrid | None:
    """Build the beat grid from BPM and the computed section boundaries.

    `boundaries` is (section_id, boundary_sec) — typically each section's
    start_sec. Each boundary gets its nearest beat and nearest bar as a PROPOSAL
    (the director chooses where boundaries land musically). Returns None when BPM
    is absent — the caller records the "no BPM → no beat grid" notation.
    """
    if not bpm or bpm <= 0:
        return None

    beat_sec = round(60.0 / bpm, 6)
    bar_sec = round(4 * beat_sec, 6)

    proposals: list[BeatProposal] = []
    for section_id, boundary in boundaries:
        # A boundary past the track end can't align to a beat that doesn't play.
        if track_duration is not None and boundary > track_duration:
            continue
        proposals.append(
            BeatProposal(
                section_id=section_id,
                boundary_sec=round(boundary, 3),
                nearest_beat_sec=_nearest(boundary, beat_sec),
                nearest_bar_sec=_nearest(boundary, bar_sec),
            )
        )

    note = None
    if track_duration is not None and any(
        b > track_duration for _, b in boundaries
    ):
        note = (
            "Some section boundaries fall after the music track ends "
            f"({track_duration:.1f}s) — those have no beat proposal. The track may "
            "need to loop or extend, or the content runs past the music."
        )

    return BeatGrid(
        bpm=bpm,
        beat_sec=beat_sec,
        bar_sec=bar_sec,
        boundary_proposals=proposals,
        note=note,
    )
