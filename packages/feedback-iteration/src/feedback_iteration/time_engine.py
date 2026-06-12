"""The time-shift engine — pure, deterministic, fully unit-tested, no I/O.

Every number in a revision is computed HERE, never by the LLM. The LLM names the
OPERATION and the AMOUNT THE DIRECTOR STATED; this engine does the arithmetic:
it resizes or shifts a section and cascades the consequence through every
downstream boundary, preserving each inter-section gap exactly.

Output is a `ChangeMap`: the new rows, a per-section old→new diff (labelled
resized / shifted / unchanged), and the deduped set of boundary-value
substitutions `(old, new)` that downstream prose references must be retimed to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


def _fmt(sec: float) -> str:
    """Seconds → `mm:ss.mmm` — identical to edit_brief/brief.py::_fmt."""
    m, s = divmod(round(sec, 3), 60)
    return f"{int(m):02d}:{s:06.3f}"


@dataclass
class EngineRow:
    section_id: str
    start: float
    end: float

    @property
    def length(self) -> float:
        return round(self.end - self.start, 3)


@dataclass
class SectionChange:
    section_id: str
    old_start: float
    old_end: float
    new_start: float
    new_end: float
    kind: Literal["resized", "shifted", "unchanged"]


@dataclass
class ChangeMap:
    rows: list[EngineRow]
    changes: list[SectionChange]
    boundary_subs: list[tuple[float, float]] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return any(c.kind != "unchanged" for c in self.changes)

    def change_for(self, section_id: str) -> SectionChange | None:
        for c in self.changes:
            if c.section_id == section_id:
                return c
        return None


def measure_gaps(rows: list[EngineRow]) -> list[float]:
    """The gap *before* each row: gaps[0] is the lead-in from 0.0; gaps[i] is the
    inter-section breathing gap rows[i].start - rows[i-1].end. Per-pair, so the
    real artifact's recurring 0.500s gaps are preserved individually (never
    assumed constant)."""
    gaps: list[float] = []
    for i, r in enumerate(rows):
        if i == 0:
            gaps.append(round(r.start, 3))
        else:
            gaps.append(round(r.start - rows[i - 1].end, 3))
    return gaps


def _index(rows: list[EngineRow], section_id: str) -> int:
    for i, r in enumerate(rows):
        if r.section_id == section_id:
            return i
    raise KeyError(f"section '{section_id}' is not on the timeline")


def _recompute(rows: list[EngineRow], lengths: list[float], gaps: list[float]) -> list[EngineRow]:
    out: list[EngineRow] = []
    cursor = 0.0
    for r, length, gap in zip(rows, lengths, gaps):
        cursor += gap
        start = round(cursor, 3)
        end = round(start + length, 3)
        cursor = end
        out.append(EngineRow(section_id=r.section_id, start=start, end=end))
    return out


def _diff(old: list[EngineRow], new: list[EngineRow]) -> ChangeMap:
    changes: list[SectionChange] = []
    subs: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for o, n in zip(old, new):
        length_changed = round(o.end - o.start, 3) != round(n.end - n.start, 3)
        moved = (o.start, o.end) != (n.start, n.end)
        kind: Literal["resized", "shifted", "unchanged"]
        if not moved:
            kind = "unchanged"
        elif length_changed:
            kind = "resized"
        else:
            kind = "shifted"
        changes.append(
            SectionChange(
                section_id=o.section_id,
                old_start=o.start,
                old_end=o.end,
                new_start=n.start,
                new_end=n.end,
                kind=kind,
            )
        )
        for old_v, new_v in ((o.start, n.start), (o.end, n.end)):
            if old_v != new_v and (old_v, new_v) not in seen:
                seen.add((old_v, new_v))
                subs.append((old_v, new_v))
    return ChangeMap(rows=new, changes=changes, boundary_subs=subs)


def diff(old: list[EngineRow], new: list[EngineRow]) -> ChangeMap:
    """Net change between two row sets — labels each section resized/shifted/
    unchanged and collects the changed boundary-value substitutions. Used to
    compose several sequential ops into one cascade before patching."""
    return _diff(old, new)


def adjust_section_duration(rows: list[EngineRow], section_id: str, *, delta: float) -> ChangeMap:
    """Change one section's length by `delta` (negative = tighten); every
    downstream section shifts by the same delta, gaps preserved."""
    idx = _index(rows, section_id)
    gaps = measure_gaps(rows)
    lengths = [r.length for r in rows]
    lengths[idx] = round(lengths[idx] + delta, 3)
    if lengths[idx] < 0:
        raise ValueError(
            f"adjusting '{section_id}' by {delta:+.3f}s would make its length negative"
        )
    return _diff(rows, _recompute(rows, lengths, gaps))


def set_section_duration(rows: list[EngineRow], section_id: str, *, new_length: float) -> ChangeMap:
    """Set one section's length absolutely; downstream shifts by the difference."""
    if new_length < 0:
        raise ValueError("new_length must be non-negative")
    idx = _index(rows, section_id)
    gaps = measure_gaps(rows)
    lengths = [r.length for r in rows]
    lengths[idx] = round(new_length, 3)
    return _diff(rows, _recompute(rows, lengths, gaps))


def shift_section(rows: list[EngineRow], section_id: str, *, delta: float) -> ChangeMap:
    """Move one section's start by `delta` without resizing it (re-cuts the gap
    before it); every downstream section shifts by the same delta."""
    idx = _index(rows, section_id)
    if idx == 0:
        raise ValueError("cannot shift the first section — it has no preceding gap to re-cut")
    gaps = measure_gaps(rows)
    gaps[idx] = round(gaps[idx] + delta, 3)
    lengths = [r.length for r in rows]
    return _diff(rows, _recompute(rows, lengths, gaps))
