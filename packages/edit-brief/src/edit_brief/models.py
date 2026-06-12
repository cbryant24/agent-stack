"""Data models for edit-brief.

Three families: (1) discovery/provenance — edit-brief's own thin shapes parsed
from the foreign collection payloads it reads, holding only the fields it
consumes (it imports no sibling package); (2) the three-layer brief — timeline
skeleton, beat grid, per-section ordered steps; (3) the library return type.

All timing fields are populated by the pure time engine, never by the LLM.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# ── Discovery / provenance ────────────────────────────────────────────────────


class DiscoveredVOTake(BaseModel):
    """The selected take for one section (positive-reacted wins, else latest)."""

    section_id: str
    audio_path: str | None = None
    duration_sec: float | None = None  # ffprobe-read; None when the file is missing
    reaction: str = "pending"
    created_at: str = ""
    # True when >1 equally-valid take exists for the section — surfaced, not hidden.
    ambiguous: bool = False


class DiscoveredMusic(BaseModel):
    """The music track + beat-grid inputs. The file/duration come from --music
    (the music collection logs neither — Suno is manual); BPM is a flag, a
    surfaced proposal matched from music_curation_memory, or absent."""

    file: str | None = None
    duration_sec: float | None = None
    bpm: int | None = None
    bpm_source: Literal["flag", "matched", "none"] = "none"
    matched_title: str | None = None  # the prior track a matched BPM came from


class DiscoveredAsset(BaseModel):
    """A candidate visual asset for a moment. Generated assets carry rich
    metadata (precise mapping); director footage is thin (surfaced, not mapped)."""

    kind: Literal["generated", "footage"]
    path: str
    description: str | None = None
    section_hint: str | None = None
    prompt: str | None = None  # generated only — the generation intent
    duration_sec: float | None = None
    created_at: str = ""


class DiscoveredInputs(BaseModel):
    """The full discovery picture — what was found and what is missing per input.
    Drives --dry-run, the brief's provenance frontmatter, and the notations."""

    project_id: str
    vo_takes: list[DiscoveredVOTake] = Field(default_factory=list)
    music: DiscoveredMusic = Field(default_factory=DiscoveredMusic)
    assets: list[DiscoveredAsset] = Field(default_factory=list)

    @property
    def has_vo(self) -> bool:
        return any(t.duration_sec is not None for t in self.vo_takes)

    @property
    def has_music(self) -> bool:
        return self.music.file is not None

    @property
    def has_bpm(self) -> bool:
        return self.music.bpm is not None

    @property
    def has_assets(self) -> bool:
        return bool(self.assets)


# ── The three-layer brief ─────────────────────────────────────────────────────


class TimelineRow(BaseModel):
    """One section's place on the timeline. Timestamps are computed in code."""

    section_id: str
    heading: str
    start_sec: float
    end_sec: float
    vo_file: str | None = None
    timing_source: Literal["vo", "estimate"] = "estimate"
    candidate_assets: list[str] = Field(default_factory=list)


class BeatProposal(BaseModel):
    """A nearest-beat alignment offered at a section boundary — a PROPOSAL the
    director chooses to honour or not, never an imposed cut."""

    section_id: str
    boundary_sec: float
    nearest_beat_sec: float
    nearest_bar_sec: float


class BeatGrid(BaseModel):
    bpm: int
    beat_sec: float
    bar_sec: float
    boundary_proposals: list[BeatProposal] = Field(default_factory=list)
    note: str | None = None


class SectionSteps(BaseModel):
    """Per-section ordered checkbox steps + any missing-input/gap notations."""

    section_id: str
    heading: str
    steps: list[str] = Field(default_factory=list)        # each a "- [ ] …" line body
    notations: list[str] = Field(default_factory=list)


class EditBrief(BaseModel):
    project_id: str
    version: int = 1
    provenance: DiscoveredInputs
    timeline: list[TimelineRow] = Field(default_factory=list)
    beat_grid: BeatGrid | None = None
    sections: list[SectionSteps] = Field(default_factory=list)
    notations: list[str] = Field(default_factory=list)  # brief-level missing-input notes
    source_path: str | None = None


# ── Library return type (mirror TechniqueResult) ──────────────────────────────


class BriefResult(BaseModel):
    brief: EditBrief
    brief_path: Path | None = None        # the edit-brief.md next to the script
    report_run_path: Path | None = None   # the standard run report in the vault
    run_id: str = ""
    status: str = "completed"
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0
    dry_run: bool = False

    model_config = {"arbitrary_types_allowed": True}


def now_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
