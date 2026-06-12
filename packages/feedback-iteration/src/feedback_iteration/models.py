"""Data models for feedback-iteration.

Three families: (1) the PARSED-BRIEF read model — the foreign edit-brief artifact
decomposed into char-offset spans for every patchable surface, so revision is a
surgical string-splice that preserves the director's hand-edits byte-for-byte;
(2) the feedback / mapping shapes the one LLM call produces; (3) the library
return type.

All timing fields are produced by the pure time engine, never by the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

# ── Parsed-brief read model (spans index into ParsedBrief.text) ───────────────


class Span(NamedTuple):
    """A half-open [start, end) char range into the original brief text."""

    start: int
    end: int


@dataclass
class FrontmatterField:
    key: str
    value: str
    value_span: Span  # span of just the value (for the version bump)


@dataclass
class ParsedFrontmatter:
    block_span: Span
    fields: dict[str, FrontmatterField]
    version: int | None
    raw: str


@dataclass
class StepLine:
    number: int | None  # the "N." ordinal, None if unnumbered
    checked: bool
    text: str  # body after the "- [ ] N. " prefix
    line_span: Span  # the whole step line (no trailing newline)
    text_span: Span  # just the body text (for in-place rewrite)
    checkbox_span: Span  # just the 3 chars "[ ]"/"[x]" (to flip state)


@dataclass
class NotationLine:
    text: str  # body after the "> " prefix
    line_span: Span
    text_span: Span  # just the body (for in-place retiming)


@dataclass
class SectionBlock:
    section_id: str  # from the <a id="…"> anchor (authoritative)
    heading_text: str  # the title after "### ", without the time span
    anchor_span: Span  # the <a id="…"></a> line
    heading_span: Span  # the whole "### Title — start → end" line
    heading_timespan: Span | None  # just " — start → end" suffix, if present
    start_sec: float | None  # parsed from the heading time span
    end_sec: float | None
    steps: list[StepLine]
    notations: list[NotationLine]
    block_span: Span  # anchor line start → just before the next anchor/##/EOF
    steps_region_end: int  # char offset after the last step line (insert point)


@dataclass
class TimelineRowSpan:
    section_id: str  # from the (#anchor) link target
    heading: str
    start_text: str  # "00:00.000"
    end_text: str
    start_sec: float
    end_sec: float
    row_span: Span  # the whole "| … |" row line
    start_span: Span  # just the Start cell text
    end_span: Span  # just the End cell text


@dataclass
class ParsedBrief:
    text: str  # the original file, verbatim
    path: Path
    project_id: str | None
    frontmatter: ParsedFrontmatter
    timeline_rows: list[TimelineRowSpan]
    sections: list[SectionBlock]
    version_log_span: Span | None  # the "## Version log" block, or None
    insert_point_for_version_log: int  # char offset to append a fresh log section

    def section_by_id(self, section_id: str) -> SectionBlock | None:
        for s in self.sections:
            if s.section_id == section_id:
                return s
        return None

    def row_by_id(self, section_id: str) -> TimelineRowSpan | None:
        for r in self.timeline_rows:
            if r.section_id == section_id:
                return r
        return None


# ── Feedback / mapping shapes (the one LLM call's structured output) ──────────


@dataclass
class FeedbackItem:
    index: int
    text: str


ChangeType = Literal["step_rewrite", "time_shift", "lesson_only", "unresolved"]
TimeOp = Literal["adjust_duration", "set_duration", "shift"]


@dataclass
class TimeShiftSpec:
    op: TimeOp
    magnitude_sec: float
    magnitude_source_quote: str  # the verbatim words the amount was taken from
    direction: Literal["shorter", "longer", "earlier", "later"]


@dataclass
class StepRewriteSpec:
    target_step_number: int | None  # None = append a new step
    new_text: str


@dataclass
class LessonCandidate:
    statement: str
    confidence: str = "medium"


@dataclass
class MappedItem:
    feedback_index: int
    change_type: ChangeType
    resolved_anchor: str | None
    diagnosis: str
    step_rewrite: StepRewriteSpec | None = None
    time_shift: TimeShiftSpec | None = None
    lesson_candidate: LessonCandidate | None = None


@dataclass
class MappingResult:
    items: list[MappedItem] = field(default_factory=list)
    overall_notations: list[str] = field(default_factory=list)


# ── Library return type (mirror BriefResult) ─────────────────────────────────


class RevisionResult(BaseModel):
    brief_path: Path | None = None
    snapshot_path: Path | None = None
    project_id: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    feedback_items: list[str] = Field(default_factory=list)  # echo, verbatim
    version_from: int | None = None
    version_to: int | None = None  # None on dry-run / no applicable change
    applied: list[str] = Field(default_factory=list)  # resolution descriptions
    unresolved: list[str] = Field(default_factory=list)  # verbatim + reason
    invalidated_checks: list[str] = Field(default_factory=list)
    lesson_draft_ids: list[str] = Field(default_factory=list)
    validation_findings: list[str] = Field(default_factory=list)
    report_run_path: Path | None = None
    run_id: str = ""
    status: str = "completed"
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0
    dry_run: bool = False

    model_config = {"arbitrary_types_allowed": True}


def now_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
