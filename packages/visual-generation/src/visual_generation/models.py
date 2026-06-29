"""Pydantic v2 models for the visual-generation agent.

Three models are stored in the `visual_generation_memory` Qdrant collection
(`VisualGeneration`, `TechniqueLesson`, `WorkflowTemplate`); each carries a
`memory_type` discriminator and `to_payload()`/`from_payload()` round-trip
helpers. `ModelAsset` is the registry record (local JSON, not embedded). The
binary asset of a generation is a disk file referenced by `asset_path` — never
stored in Qdrant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from visual_generation.constants import (
    ASSET_KIND_CHECKPOINT,
    MEMORY_TYPE_GENERATION,
    MEMORY_TYPE_TECHNIQUE_LESSON,
    MEMORY_TYPE_WORKFLOW_TEMPLATE,
    REACTION_PENDING,
    STATUS_COMPLETE,
    STATUS_PENDING,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Sub-models ────────────────────────────────────────────────────────────────


class LoraRef(BaseModel):
    """One entry in a generation's LoRA stack: a registry name plus its applied
    strength. The name keys into the model/LoRA registry (ModelAsset.name)."""

    name: str
    strength: float = 1.0


class VisualSource(BaseModel):
    """Where a refinement starts from (img2img / inpaint).

    Two mutually-exclusive forms: `from_generation` (a prior VisualGeneration
    entry_id, resolved to its `asset_path` at spend time — the iterate loop) OR
    `image_path` (an external image already on disk — a reference start). `mask`
    is inpaint-only: a user-supplied PNG path where white = the area to change.
    An absent source on a spec means current text-to-image behavior, unchanged.
    """

    from_generation: str | None = None
    image_path: str | None = None
    mask: str | None = None  # inpaint only; user-supplied PNG, white = area to change

    @model_validator(mode="after")
    def _exactly_one_origin(self) -> VisualSource:
        if bool(self.from_generation) == bool(self.image_path):
            raise ValueError(
                "source: set exactly one of from_generation / image_path"
            )
        return self


# ── Memory entry models (Qdrant payload schema) ───────────────────────────────


class VisualGeneration(BaseModel):
    """A generation entry in `visual_generation_memory` — the core record.

    The embedded vector comes from the image/keyframe at `asset_path` plus the
    `caption` (multimodal, voyage-multimodal-3); everything else is payload. The
    binary asset is a disk file, never stored in Qdrant. A generation is born
    `pending` (rendered, not yet reacted to); `report` (Step 4) flips it to a
    settled reaction and `status="complete"`.

    Generation params are held as a flexible, model-agnostic `settings` dict
    (sampler/steps/CFG/shift/…) rather than fixed floats — Flux, SDXL, and WAN
    parameterize differently, so keeping `settings` open avoids reshaping the
    foundation when Step 3 fills it per model.

    Lineage spans output types (an I2V clip's parent can be a prior still), which
    is what unifies stills and video onto one path: `parent_id`/`chain_root_id`.
    """

    memory_type: Literal["generation"] = MEMORY_TYPE_GENERATION
    entry_id: str = Field(default_factory=_new_id)
    # Embedded multimodal source: the image at asset_path + this caption.
    caption: str
    asset_path: str | None = None
    # The spec that produced it.
    prompt: str = ""
    negative_prompt: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)  # sampler/steps/CFG/shift/...
    model: str | None = None  # checkpoint name (registry key)
    lora_stack: list[LoraRef] = Field(default_factory=list)
    workflow_ref: str | None = None  # WorkflowTemplate name/id
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    # Cost / opsec.
    cost_usd: float = 0.0  # per-run GPU cost (orthogonal to the Claude BudgetEnvelope)
    identity_bearing: bool = False
    # Reaction / lifecycle.
    reaction: str = REACTION_PENDING
    rating: int | None = Field(default=None, ge=1, le=5)  # intensity within a reaction tier
    status: Literal["pending", "complete"] = STATUS_PENDING
    notes: str | None = None  # action-oriented: what to change next time
    context: str | None = None  # reasoning-oriented: why the user reacted as they did
    # Scope / placement.
    project: str | None = None
    # Lineage (spans output types).
    parent_id: str | None = None
    chain_root_id: str = ""  # set to own entry_id when this is a chain root
    # Refinement provenance (img2img / inpaint): the resolved LOCAL paths used as
    # init image / mask. parent_id carries the from_generation lineage; these
    # capture the external-image case (no parent) and aid reproduction.
    source_image_path: str | None = None
    source_mask_path: str | None = None
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
    def from_payload(cls, payload: dict[str, Any]) -> VisualGeneration:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class TechniqueLesson(BaseModel):
    """A generalised technique preference learned by doing ("CFG>7 washed skin on
    this checkpoint"). The `statement` is the embedded text. Only confirmed
    lessons are surfaced in retrieval by default; unconfirmed ones are stored so
    they can be promoted later.
    """

    memory_type: Literal["technique_lesson"] = MEMORY_TYPE_TECHNIQUE_LESSON
    entry_id: str = Field(default_factory=_new_id)
    statement: str
    valence: Literal["positive", "negative"]
    scope: Literal["prompt", "settings", "workflow", "model"] = "settings"
    confirmed: bool = False
    derived_from: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TechniqueLesson:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


class WorkflowTemplate(BaseModel):
    """A reusable parameterized ComfyUI graph.

    The `descriptor` is the embedded text — a short phrase summarising what the
    template serves. The `graph` is the API-format node graph (node id →
    `{class_type, inputs}`). The `slot_map` maps a semantic parameter name to the
    `{node_id, input_key}` it writes into — the swap-points. `required_models`
    lets a batch be checked against the registry before spin-up. The slot-map
    internals are stored/retrieved faithfully here; they get exercised in Step 3.
    """

    memory_type: Literal["workflow_template"] = MEMORY_TYPE_WORKFLOW_TEMPLATE
    entry_id: str = Field(default_factory=_new_id)
    name: str
    descriptor: str
    graph: dict[str, Any] = Field(default_factory=dict)
    slot_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    required_models: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkflowTemplate:
        return cls(**{k: v for k, v in payload.items() if k in cls.model_fields})


# ── Model/LoRA registry record (local JSON, not embedded) ─────────────────────


class ModelAsset(BaseModel):
    """A concrete named asset (checkpoint, LoRA, VAE, …) in the local registry.

    Not a memory type — enumerated and looked up by `name`, never semantically
    searched. `identity_bearing` flags character LoRAs (and other identity
    artifacts); the secured-path / write-guard enforcement attaches at the
    asset-writing layer in Step 4. This step just carries the flag.
    """

    name: str  # lookup key
    kind: Literal["checkpoint", "lora", "vae", "controlnet", "clip", "embedding"] = ASSET_KIND_CHECKPOINT
    identity_bearing: bool = False
    base_model: str | None = None
    source: Literal["registered", "synced"] = "registered"
    # Whether the most recent `model sync` saw this asset in the pod's /object_info.
    # A manually-registered asset absent from a given pod is kept + flagged False
    # (so its identity_bearing flag survives a pod that's down or lacks it); a
    # previously-synced asset that goes absent is dropped (see model_sync.reconcile).
    present_on_endpoint: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelAsset:
        return cls.model_validate(data)


# ── The turn: batch spec / file (Phase A) and run results (Phase B) ───────────


class VisualSpec(BaseModel):
    """One settled generation spec in an editable batch file.

    The `prompt` is the human-readable body of the batch-file section; everything
    else rides in the per-section HTML-comment JSON. `identity_bearing` here is a
    convenience pre-fill (draft derives it honestly from the registry) — it is
    NOT trusted for the security decision: `generate` RE-DERIVES it from the
    registry at spend time (the registry is source of truth; this field can only
    escalate to identity-bearing, never downgrade). See `identity.derive_identity_bearing`.
    """

    spec_id: str = Field(default_factory=_new_id)
    heading: str = ""  # human label for the batch-file section (not security-relevant)
    prompt: str = ""
    negative_prompt: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)  # steps/cfg/sampler/scheduler/flux_guidance/...
    model: str | None = None  # checkpoint/unet registry name
    seed: int | None = None
    seed_strategy: Literal["fixed", "random"] = "fixed"
    width: int | None = None
    height: int | None = None
    lora_stack: list[LoraRef] = Field(default_factory=list)
    workflow_ref: str | None = None  # WorkflowTemplate name
    # Refinement origin (img2img / inpaint). Absent = text-to-image (unchanged).
    # denoise is NOT duplicated here — it rides in `settings`.
    source: VisualSource | None = None
    project: str | None = None
    identity_bearing: bool = False  # pre-fill only — re-derived at generate
    rationale: str | None = None  # concise tutor rationale for the spec
    # Lineage for a `redraft` (prose-only text2img revise): the parent gen_id this
    # spec was revised from. Metadata ONLY — never read at generate time (a redraft
    # carries source=None, so it stays text2img). parent_id/chain_root_id are still
    # minted on the generation; this records the spec→generation descent.
    revised_from: str | None = None
    created_at: str = Field(default_factory=_now_iso)


class GenerationBatch(BaseModel):
    """A batch file: a header plus an ordered list of specs (one per generation).

    Parameter sweeps are multiple pre-queued specs, not live improvisation.
    """

    project: str | None = None
    created_at: str = Field(default_factory=_now_iso)
    source_path: str | None = None
    specs: list[VisualSpec] = Field(default_factory=list)


class VisualResult(BaseModel):
    """The on-screen result of generating one spec (Q11): where the asset landed,
    the resolved recipe, the tutor rationale, and the GPU cost."""

    generation_id: str
    spec_id: str
    asset_path: str | None = None
    identity_bearing: bool = False
    settings_recipe: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    gpu_cost_usd: float = 0.0
    session_cost_running_usd: float = 0.0


class ProvenanceLeg(BaseModel):
    """One retrieval leg's contribution, for deterministic 'what was surfaced' proof.

    `tier` is the authority label (locked > strong > reference); `count`/`top_score`
    summarize the hits; `snippets` are short previews of the top items."""

    label: str
    collection: str
    tier: Literal["locked", "strong", "reference"]
    count: int
    top_score: float = 0.0
    snippets: list[str] = Field(default_factory=list)


class DraftResult(BaseModel):
    """Returned by draft() — the crafted spec plus the free-loop advisories."""

    spec: VisualSpec
    batch_path: Path | None = None
    template_name: str | None = None
    compiled_from: list[str] = Field(default_factory=list)  # project docs compiled into the input
    provenance: list[ProvenanceLeg] = Field(default_factory=list)  # what retrieval surfaced (deterministic)
    tutor_notes: list[str] = Field(default_factory=list)  # the user's own surfaced lessons
    missing_models: list[str] = Field(default_factory=list)  # required models absent from registry
    inert_inheritance: list[str] = Field(default_factory=list)  # inherited attrs the template can't apply
    revise_warnings: list[str] = Field(default_factory=list)  # redraft advisories (e.g. parent was img2img)
    canon_applied: list[str] = Field(default_factory=list)  # deterministic canon edits made to the prompt
    canon_absent: list[str] = Field(default_factory=list)  # scene-named canon subjects missing from the prompt
    research_offer: str | None = None  # a gap topic to OFFER (never auto-run)
    overall_reasoning: str = ""
    run_id: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    cost_usd: float = 0.0
    wall_time_sec: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


class GenerationResult(BaseModel):
    """Returned by generate()/spend_generation(): per-spec results plus the GPU
    session total. `cost_usd` is the Claude axis (≈0 — generation makes no LLM
    call); GPU spend lives in `session_cost_usd`, never in the BudgetEnvelope."""

    results: list[VisualResult] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # spec ids skipped
    skip_reasons: list[str] = Field(default_factory=list)  # plain-language, one per skip
    run_id: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    items_processed: int = 0
    session_cost_usd: float = 0.0
    gpu_rate_usd_per_hr: float = 0.0
    drained: bool = True  # whether the batch fully drained (drives the stop-prompt)
    cost_usd: float = 0.0  # Claude axis (≈0)
    wall_time_sec: float = 0.0
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}
