"""Pydantic v2 models for the voiceover-direction agent.

Two of these models are stored in the `voiceover_direction_memory` Qdrant
collection (`Take`, `DirectionLesson`); they carry a `memory_type` discriminator
and `to_payload()`/`from_payload()` round-trip helpers. `VoiceProfile` is the
registry record (local JSON, not embedded). The rest are output / in-memory
representations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from voiceover_direction.constants import (
    MEMORY_TYPE_DIRECTION_LESSON,
    MEMORY_TYPE_TAKE,
    REACTION_PENDING,
    STATUS_COMPLETE,
    STATUS_PENDING,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Memory entry models (Qdrant payload schema) ──────────────────────────────


class Take(BaseModel):
    """One generation attempt for a section — the audio plus its direction.

    The `text` (the exact string sent to ElevenLabs) is the embedded vector
    source; everything else is payload. Lineage is **section-scoped**: a take's
    `parent_take_id`/`chain_root_id` chain is reshaped per section and never
    crosses a `section_id`. A take is born `pending` (generated, not yet reacted
    to); `report` flips it to a settled reaction and `status="complete"`.

    Generation params are held as a flexible, model-agnostic `settings` dict
    rather than v2's continuous voice-settings floats — the handoff centers
    `eleven_v3`, whose expressive control is inline audio tags (in `emotion_tags`)
    plus a discrete stability mode. Keeping `settings` open avoids locking the
    foundation to v2 and lets Step 3 fill it per model without reshaping.
    """

    memory_type: Literal["take"] = MEMORY_TYPE_TAKE
    entry_id: str = Field(default_factory=_new_id)
    text: str  # the exact section text sent to ElevenLabs (embedded)
    voice_id: str
    model: str  # e.g. "eleven_v3"
    settings: dict[str, Any] = Field(default_factory=dict)  # model-agnostic generation params
    emotion_tags: list[str] = Field(default_factory=list)
    character_count: int = 0
    audio_path: str | None = None
    reaction: str = REACTION_PENDING
    rating: int | None = Field(default=None, ge=1, le=5)  # intensity within a reaction tier
    status: Literal["pending", "complete"] = STATUS_PENDING
    notes: str | None = None  # action-oriented: what to change next time
    context: str | None = None  # reasoning-oriented: why the user reacted as they did
    # Scope / placement
    section_id: str
    project_id: str
    domain: str | None = None
    # Section-scoped lineage
    parent_take_id: str | None = None
    chain_root_id: str = ""  # set to own entry_id when this take is a section root
    created_at: str = Field(default_factory=_now_iso)
    reacted_at: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.chain_root_id:
            self.chain_root_id = self.entry_id

    def to_payload(self) -> dict[str, Any]:
        d = self.model_dump()
        d["status"] = STATUS_PENDING if self.reaction == REACTION_PENDING else STATUS_COMPLETE
        return d

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Take:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class DirectionLesson(BaseModel):
    """A generalised direction preference ("how to direct"), e.g. a voice,
    pacing, or tone lesson. The `statement` is the embedded text. Only confirmed
    lessons are used in retrieval by default; unconfirmed ones are stored so they
    can be promoted later.
    """

    memory_type: Literal["direction_lesson"] = MEMORY_TYPE_DIRECTION_LESSON
    entry_id: str = Field(default_factory=_new_id)
    statement: str
    valence: Literal["positive", "negative"]
    scope: Literal["voice", "pacing", "tone", "general"] = "general"
    confirmed: bool = False
    derived_from: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DirectionLesson:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


# ── Voice registry record (local JSON, not embedded) ─────────────────────────


class VoiceProfile(BaseModel):
    """A voice available in ElevenLabs, synced into the local registry. Not a
    memory type — enumerated and looked up by `voice_id`, never semantically
    searched. `category` is normalised from the vendor's category field.
    """

    voice_id: str
    name: str
    category: Literal["stock", "cloned"]
    labels: dict[str, str] = Field(default_factory=dict)
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceProfile:
        return cls.model_validate(data)


# ── Vendor usage (queried, never cached / never in BudgetEnvelope) ───────────


class CharacterUsage(BaseModel):
    """A snapshot of the monthly ElevenLabs character quota. Source of truth is
    the vendor — this is a transient read, never persisted locally.
    """

    character_count: int
    character_limit: int
    characters_remaining: int
    next_reset_unix: int | None = None


# ── Output model (returned on-screen by `generate` in Step 3) ────────────────


class VoiceoverResult(BaseModel):
    """The on-screen result of a generate: the take produced, where the audio
    landed, what it cost, and the vendor-reported remaining budget.
    """

    take_id: str
    audio_path: str | None = None
    character_cost: int = 0
    remaining_characters: int | None = None


# ── Directed-script representation (the editable file `direct` writes; Step 2) ─
# The in-memory model is defined now; the markdown read/write serialization lands
# with the `direct` command.


class DirectedSection(BaseModel):
    """One section of a directed script: prose (emotion tags inline) plus the
    small per-section direction metadata a human can hand-tweak.
    """

    section_id: str
    heading: str
    text: str  # prose with emotion tags inline
    voice_id: str | None = None
    model: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class DirectedScript(BaseModel):
    """A whole directed script — headings preserved, one DirectedSection each."""

    project_id: str
    domain: str | None = None
    sections: list[DirectedSection] = Field(default_factory=list)
    source_path: str | None = None
    created_at: str = Field(default_factory=_now_iso)


# ── Parser output (input side; consumed by `direct` in Step 2) ───────────────


class ScriptSection(BaseModel):
    """A heading-delimited section parsed from an input script: identity comes
    from the heading, body is the raw prose beneath it.
    """

    section_id: str
    heading: str
    body: str


class ParsedScript(BaseModel):
    """The result of parsing an input markdown script into its sections."""

    source_path: str | None = None
    sections: list[ScriptSection] = Field(default_factory=list)


# ── direct() run result (Step 2) ─────────────────────────────────────────────


class DirectionResult(BaseModel):
    """Returned by direct() / direct_sync(): the directed script plus run stats."""

    directed_script: DirectedScript
    output_path: Path | None = None
    overall_reasoning: str = ""
    run_id: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    cost_usd: float = 0.0
    items_processed: int = 0
    wall_time_sec: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


# ── generate() run result (Step 3) ───────────────────────────────────────────


class GenerationResult(BaseModel):
    """Returned by generate() / generate_sync(): per-section results plus run stats.

    `cost_usd` is the Claude cost (always 0.0 — generation makes no LLM call), which
    is exactly the point: the character spend is orthogonal and never enters the budget.
    Sections lacking a voice_id are listed in `skipped`, not generated.
    """

    results: list[VoiceoverResult] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    run_id: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    items_processed: int = 0
    wall_time_sec: float = 0.0
    cost_usd: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}
