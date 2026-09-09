"""Pydantic data models for the video-clipping agent.

Shape follows visual-generation conventions: Pydantic v2, plain UUID4 string ids,
ISO-string timestamps, `memory_type` discriminator + to_payload/from_payload
round-trip helpers on every memory-typed model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from video_clipping.constants import (
    LENGTH_TOLERANCE_SEC,
    MEMORY_TYPE_LESSON,
    MEMORY_TYPE_RUN,
    MEMORY_TYPE_SEGMENT,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


ExcludeReason = Literal[
    "low_video_quality",
    "short_or_long",
    "low_audio_quality",
    "theme_mismatch",
    "duplicate_of_previous",       # intra-run duplicate (Phase 1)
    "duplicate_of_previous_run",   # cross-run duplicate (Phase 2)
    "unidentifiable",
    "error",  # Phase-1 sentinel: per-segment LLM/parse/cut failure
]

RunStatus = Literal["completed", "partial", "failed"]

DetectorLabel = Literal["pyscenedetect", "scdet", "silence"]
LengthStatus = Literal["ok", "near_miss_short", "near_miss_long"]
MemoryType = Literal["run", "segment", "lesson"]


class Spec(BaseModel):
    """Director's input file. Mirrors the masterplan `spec.yaml` schema."""

    video: Path
    location: str
    event_type: str
    target_clip_length_sec: tuple[float, float]
    max_total_output_min: float
    content_wanted: list[str] = Field(default_factory=list)
    exclude_when: list[ExcludeReason] = Field(default_factory=list)
    tone_notes: str | None = None

    @model_validator(mode="after")
    def _check_length_window(self) -> Spec:
        lo, hi = self.target_clip_length_sec
        if lo <= 0 or hi <= 0 or lo > hi:
            raise ValueError(
                f"target_clip_length_sec must be [lo, hi] with 0 < lo <= hi, got ({lo}, {hi})"
            )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Spec:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"spec at {path} is not a YAML mapping")
        # YAML `[15, 60]` parses as a list; coerce to tuple for the field.
        if isinstance(raw.get("target_clip_length_sec"), list):
            raw["target_clip_length_sec"] = tuple(raw["target_clip_length_sec"])
        # Expand ~ in the video path.
        if "video" in raw and isinstance(raw["video"], str):
            raw["video"] = Path(raw["video"]).expanduser()
        return cls(**raw)


class PrepassMetrics(BaseModel):
    """Video-file-level metrics (from ffprobe). Attached at the Run level."""

    resolution: tuple[int, int]
    fps: float
    bitrate_kbps: int | None
    duration_sec: float


class Segment(BaseModel):
    """One candidate segment after the pre-pass. Per-window ebur128 loudness lives here."""

    segment_id: str = Field(default_factory=_new_id)
    start: float
    end: float
    duration: float
    mean_loudness_lufs: float | None = None
    detector_provenance: list[DetectorLabel] = Field(default_factory=list)
    length_status: LengthStatus = "ok"

    # Phase-1+ fields: transcript + vision summary. Kept optional so the schema is
    # stable across phases.
    transcript: str | None = None
    visual_summary: str | None = None

    memory_type: Literal["segment"] = MEMORY_TYPE_SEGMENT

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Segment:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class ClipDecision(BaseModel):
    """LLM decision on one segment."""

    segment_id: str
    action: Literal["include", "exclude", "trim"]
    refined_start: float
    refined_end: float
    exclude_reason: ExcludeReason | None = None
    theme_match: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    one_line_summary: str

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ClipDecision:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class CostEstimate(BaseModel):
    """Projected LLM cost for a Phase-1 run of this plan (Phase 0 records only)."""

    frames_to_send: int
    projected_input_tokens: int
    projected_usd: float
    pricing_model_id: str
    pricing_input_usd_per_mtok: float


LessonPatternType = Literal["exclude_cluster", "cross_run_repeat"]


class Lesson(BaseModel):
    """Reusable clipping-craft lesson. Persisted from Phase 2+.

    Auto-accrued from generate runs: `pattern_type` + `pattern_payload` +
    `human_summary` + `source_run_id` are populated by `lesson.accrue_lessons`.
    The older `statement`/`valence` fields are kept optional so a future
    human-authored lesson (CLI-added, opt-in) shares the schema.
    """

    lesson_id: str = Field(default_factory=_new_id)
    created_at: str = Field(default_factory=_now_iso)

    # Auto-accrued fields (Phase 2).
    source_run_id: str | None = None
    pattern_type: LessonPatternType | None = None
    pattern_payload: dict[str, Any] = Field(default_factory=dict)
    human_summary: str | None = None
    event_type: str | None = None  # denormalized for surfacing filter

    # Legacy / human-authored fields.
    statement: str | None = None
    valence: Literal["positive", "negative"] | None = None

    memory_type: Literal["lesson"] = MEMORY_TYPE_LESSON

    def embedding_text(self) -> str:
        """The string used to embed this lesson into Qdrant."""
        return self.human_summary or self.statement or ""

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Lesson:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class Run(BaseModel):
    """One `clip draft` invocation. Serialized as `plan.json`.

    Phase 1: after `clip generate`, the same Run schema (with the six optional
    fields at the bottom populated) is re-serialized alongside plan.json as
    `run.json`. plan.json itself stays immutable — it's the pre-generate artifact.
    """

    run_id: str = Field(default_factory=_new_id)
    created_at: str = Field(default_factory=_now_iso)
    spec: Spec
    video_sha256: str
    prepass_metrics: PrepassMetrics
    segments: list[Segment]
    scene_detection: dict[str, list[tuple[float, float]]]
    cost_estimate: CostEstimate

    # Post-`generate` fields (Phase 1). All optional so an existing plan.json
    # continues to load via from_payload.
    decisions: list[ClipDecision] = Field(default_factory=list)
    accepted_segment_ids: list[str] = Field(default_factory=list)
    clip_paths: list[Path] = Field(default_factory=list)
    actual_cost_usd: float | None = None
    status: RunStatus | None = None
    halted_reason: str | None = None

    # Phase-2 fields (Qdrant memory writes).
    cross_run_hits: list[dict[str, Any]] = Field(default_factory=list)
    lessons_recorded: list[str] = Field(default_factory=list)
    qdrant_deviation: bool = False

    memory_type: Literal["run"] = MEMORY_TYPE_RUN

    model_config = {"arbitrary_types_allowed": True}

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Run:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


# Exported so callers can compare against the tolerance without re-importing constants.
LENGTH_TOLERANCE = LENGTH_TOLERANCE_SEC
