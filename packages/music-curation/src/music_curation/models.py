from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from music_curation.constants import (
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_SOUND_REFERENCE,
    MEMORY_TYPE_TASTE,
    MEMORY_TYPE_TEMPLATE,
    REACTION_LOST_TRACK,
    REACTION_PENDING,
    STATUS_COMPLETE,
    STATUS_PENDING,
    STYLE_FIELD_MAX_CHARS,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Output models (generation chain results) ─────────────────────────────────

class SunoPrompt(BaseModel):
    """One Suno-ready prompt pair. style_field is the Style-of-Music field;
    lyrics_field is the optional Lyrics field."""
    style_field: str
    lyrics_field: str | None = None

    @field_validator("style_field")
    @classmethod
    def _truncate_style(cls, v: str) -> str:
        if len(v) > STYLE_FIELD_MAX_CHARS:
            v = v[:STYLE_FIELD_MAX_CHARS]
        return v


class GenerationRef(BaseModel):
    """Lightweight reference to a prior generation, embedded in MusicResult."""
    entry_id: str
    style_field_excerpt: str
    reaction: str
    suggested_track_title: str | None = None


class MusicResult(BaseModel):
    """Returned by curate() / curate_sync()."""
    prompts: list[SunoPrompt]
    suggested_titles: list[str] = Field(default_factory=list)
    theory_reasoning: str
    references: list[str] = Field(default_factory=list)
    cross_references: list[GenerationRef] = Field(default_factory=list)
    generation_ids: list[str] = Field(default_factory=list)
    run_id: str
    status: Literal["completed", "partial", "failed"]
    cost_usd: float
    items_processed: int
    wall_time_sec: float
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


# ── Memory entry models (Qdrant payload schema) ───────────────────────────────

class Generation(BaseModel):
    """A generation entry in music_curation_memory.

    The style_field text is the embedded vector source. All other fields are
    stored as payload. Pending generations (status="pending") are excluded from
    taste/quality retrieval by default; they're only surfaced by review-pending
    and when the agent notices a pending entry in the same territory.
    """
    memory_type: Literal["generation"] = MEMORY_TYPE_GENERATION
    entry_id: str = Field(default_factory=_new_id)
    session_id: str
    chain_root_id: str = ""          # set to own entry_id when no parent
    parent_id: str | None = None
    style_field: str
    lyrics_field: str | None = None
    goal: str | None = None
    references: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    suggested_track_title: str | None = None
    bpm: int | None = None
    language: str | None = None
    reaction: str = REACTION_PENDING
    status: Literal["pending", "complete"] = STATUS_PENDING
    change_summary: str | None = None
    notes: str | None = None       # action-oriented: what to change next time (was: user_note)
    context: str | None = None     # reasoning-oriented: why the user reacted as they did
    rating: int | None = Field(default=None, ge=1, le=5)  # intensity within a reaction tier
    created_at: str = Field(default_factory=_now_iso)
    reacted_at: str | None = None

    @field_validator("style_field")
    @classmethod
    def _validate_style(cls, v: str) -> str:
        if len(v) > STYLE_FIELD_MAX_CHARS:
            raise ValueError(
                f"style_field exceeds {STYLE_FIELD_MAX_CHARS} characters ({len(v)})"
            )
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.chain_root_id:
            self.chain_root_id = self.entry_id

    def to_payload(self) -> dict[str, Any]:
        d = self.model_dump()
        d["status"] = STATUS_PENDING if self.reaction == REACTION_PENDING else STATUS_COMPLETE
        return d

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Generation:
        # Back-compat for the user_note → notes rename: map a legacy key if present
        # and the new key is absent, so no stored note is silently dropped on read.
        if "user_note" in payload and "notes" not in payload:
            payload = {**payload, "notes": payload["user_note"]}
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class Template(BaseModel):
    """A reusable parameterized prompt scaffold.

    The descriptor is the embedded text — a short phrase summarising what the
    template serves (e.g. "sparse solo synthesizer space psychedelic meditation").
    The style_pattern holds the actual parameterized body with [SwapVar] slots.
    """
    memory_type: Literal["template"] = MEMORY_TYPE_TEMPLATE
    entry_id: str = Field(default_factory=_new_id)
    name: str
    descriptor: str
    style_pattern: str
    lyrics_pattern: str | None = None
    swap_variables: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    source_session_id: str | None = None
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Template:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class TasteLesson(BaseModel):
    """A generalised taste preference.

    Only confirmed lessons (confirmed=True) are used in retrieval for generation
    context. Unconfirmed lessons are stored but filtered out by default — they
    exist so they can be promoted later via `seed review-taste`.
    """
    memory_type: Literal["taste"] = MEMORY_TYPE_TASTE
    entry_id: str = Field(default_factory=_new_id)
    statement: str
    valence: Literal["positive", "negative"]
    scope: Literal["genre", "production", "instrumentation", "vocal", "arrangement", "general"]
    derived_from_session_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TasteLesson:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class SoundReference(BaseModel):
    """A reference to a specific sound, described verbally.

    The description is the embedded text — the user's verbal characterisation
    of the sound they want to reproduce or avoid.
    """
    memory_type: Literal["sound_reference"] = MEMORY_TYPE_SOUND_REFERENCE
    entry_id: str = Field(default_factory=_new_id)
    description: str
    source_track: str | None = None
    timestamp_range: str | None = None
    qualities: list[str] = Field(default_factory=list)
    linked_generation_ids: list[str] = Field(default_factory=list)
    linked_suno_tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SoundReference:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


# ── Seed-ingestion intermediate types ────────────────────────────────────────

class ParsedPrompt(BaseModel):
    """A prompt extracted from a seed file before Qdrant storage."""
    session_id: str
    name: str
    style_field: str
    lyrics_field: str | None = None
    reaction: str = REACTION_LOST_TRACK
    bpm: int | None = None
    language: str | None = None
    suggested_track_title: str | None = None
    change_summary: str | None = None
    parent_index: int | None = None  # index into the session's prompt list (0-based)
    is_explicit_template: bool = False  # True when the file explicitly frames it as a template

    @field_validator("style_field")
    @classmethod
    def _truncate(cls, v: str) -> str:
        return v[:STYLE_FIELD_MAX_CHARS] if len(v) > STYLE_FIELD_MAX_CHARS else v


class ParsedSunoFact(BaseModel):
    """A Suno-mechanics fact extracted from a seed file's learnings section."""
    statement: str
    topic_tags: list[str] = Field(default_factory=list)
    confidence: str = "high"
    examples: list[str] = Field(default_factory=list)


class ParsedTasteLesson(BaseModel):
    """A taste lesson candidate awaiting user confirmation."""
    statement: str
    valence: Literal["positive", "negative"]
    scope: Literal["genre", "production", "instrumentation", "vocal", "arrangement", "general"] = "general"
    session_id: str
    is_explicit: bool = False  # True for README-derived and explicit summary tables


class ParsedTemplate(BaseModel):
    """A template candidate extracted from a seed file."""
    name: str
    descriptor: str
    style_pattern: str
    lyrics_pattern: str | None = None
    swap_variables: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    source_session_id: str | None = None
    is_explicit: bool = False  # True for README and file 7 explicit reference templates


class ParsedSession(BaseModel):
    """All entries parsed from one seed file."""
    session_id: str
    source_path: str
    prompts: list[ParsedPrompt] = Field(default_factory=list)
    suno_facts: list[ParsedSunoFact] = Field(default_factory=list)
    taste_lessons: list[ParsedTasteLesson] = Field(default_factory=list)
    templates: list[ParsedTemplate] = Field(default_factory=list)


# ── Taste pending draft (deferred confirmation queue) ─────────────────────────

class TastePendingDraft(BaseModel):
    """A taste lesson deferred during seed ingestion, awaiting later review."""
    draft_id: str = Field(default_factory=_new_id)
    statement: str
    valence: Literal["positive", "negative"]
    scope: Literal["genre", "production", "instrumentation", "vocal", "arrangement", "general"] = "general"
    session_id: str
    source_path: str
    created_at: str = Field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TastePendingDraft:
        return cls(**data)
