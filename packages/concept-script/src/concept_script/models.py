"""Data models for concept-script.

The central artifact is `VideoBrief` — the in-memory form of the editable
`script.md` that both modes emit and that `voiceover-direction direct` consumes.
Emotion direction is authored *inline* inside each section's prose as literal
ElevenLabs-style tags (e.g. `[whispers] Welcome back. [excited] ...`); it is
deliberately not a separate field, because that is exactly the format the
voiceover parser passes through untouched.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class BriefSection(BaseModel):
    """One section of the script: a heading and its prose.

    `prose` carries inline emotion tags. The section's downstream identity is the
    slugified heading (derived by the voiceover parser), so we do not author IDs.
    """

    heading: str
    prose: str


class VideoBrief(BaseModel):
    """The structured form of an editable, Voiceover-Direction-ready script.

    Serializes to `script.md` via `concept_script.serialize.to_script_md`.
    """

    logline: str
    sections: list[BriefSection] = Field(default_factory=list)
    # Optional style hints for Music Curation. Lives in the pre-heading preamble,
    # which the voiceover parser skips — so it never becomes a narrated section.
    music_hint: str | None = None
    # Curation mode only: a human-readable record of each `director note` cut that
    # was executed, surfaced as a trailer so the user can verify the deletions.
    cut_trailer: list[str] = Field(default_factory=list)


class ConceptResult(BaseModel):
    """Returned by draft() / shape(). Carries the run's outcome and the path to
    the written script.md plus the standard run telemetry."""

    brief: VideoBrief
    script_path: Path | None = None
    run_id: str
    status: str  # "completed" | "partial" | "failed"
    cost_usd: float
    wall_time_sec: float
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}
