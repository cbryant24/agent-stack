"""Interpretation and write-tool schemas.

The persisted `EvaluationEntry` lives in the library (visual_generation.models); these are what
the model passes in (labels, not ids; no system fields) and what a proposal looks like once the
labels are resolved. System fields (ids, chain root, project, session, engine, timestamps, the
automatic agent_status) are filled by code, never by the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from visual_generation.evaluation import StrikeStatus
from visual_generation.models import ArchitectureQuestion, EvaluationEntry, Finding, Layer

Reaction = Literal["loved", "liked", "liked_with_changes", "disliked", "render_failed"]
# Evaluation-charter status vocabulary, plus the explicit "unresolved".
Status = Literal[
    "draft", "candidate", "approved", "rejected", "infrastructure-pass", "agent-pass",
    "visual-pass", "production-ready", "unresolved",
]
Topic = Literal["identity", "staging", "set", "other"]
Mode = Literal["redraft", "refine_img2img", "inpaint", "new_draft"]
Scope = Literal["prompt", "settings", "workflow", "model"]


class KeepInput(BaseModel):
    attribute: str = Field(description="What to keep, e.g. 'jaw'.")
    source: str = Field(description="The attempt it should be kept from: a label like 'attempt-07' or an id.")


class EvaluationInput(BaseModel):
    """Everything an evaluation needs from the model: the director's words and the structure read
    out of them. Used by `propose_interpretation` (via InterpretationInput) and `record_evaluation`."""

    generation: str = Field(description="The attempt being evaluated: a label like 'attempt-07', 'latest', or an id.")
    raw_feedback: str = Field(description="The director's feedback, VERBATIM.")
    reaction: Reaction = Field(description="The director's reaction. If they did not give one, ask first.")
    rating: int | None = Field(default=None, ge=1, le=5, description="Only if the director gave one.")
    question: str | None = Field(default=None, description="The single question this attempt was meant to answer.")
    keep: list[KeepInput] = Field(default_factory=list)
    change: list[str] = Field(default_factory=list, description="Words only. Numbers must come from the director "
                              "or the attempt's own recipe; anything new goes in open_parameters.")
    findings: list[Finding] = Field(default_factory=list)
    required_outcomes: list[str] = Field(default_factory=list)
    infrastructure_status: Status | None = None
    agent_status: Status | None = None
    visual_status: Status | None = None
    director_signoff: bool = False
    strike_class: str | None = Field(default=None, description="The fix class this attempt belongs to, for "
                                     "three-strikes counting, e.g. 'bleed-via-prompt'.")
    architecture_question: ArchitectureQuestion | None = Field(
        default=None, description="Required after three failed same-class attempts: name the layer blamed "
                                  "and a different layer that could be at fault.")


class RevisedSpecInput(BaseModel):
    base: str = Field(description="The attempt to revise from: a label or id.")
    mode: Mode
    locked: list[str] = Field(default_factory=list, description="Attributes held fixed.")
    changes: list[str] = Field(default_factory=list, description="Words only; no new numbers.")
    open_parameters: list[str] = Field(default_factory=list, description="Values the DIRECTOR must decide.")


class LessonInput(BaseModel):
    statement: str
    scope: Scope
    valence: Literal["positive", "negative"]
    layer: Layer
    topic: Topic = Field(default="other", description="identity, staging or set if the lesson is about them.")
    evidence_n: int = Field(default=1, ge=1)
    falsification_test: str | None = Field(default=None, description="A counter-case that would disprove it. "
                                           "Required for a prompt-layer lesson about identity, staging or set.")
    claim_level: Literal["tuned", "validated"] = "tuned"
    held_out_eval_id: str | None = Field(default=None, description="Needed for 'validated' (with evidence_n >= 5).")
    source_eval_ids: list[str] = Field(default_factory=list)


class InterpretationInput(EvaluationInput):
    revised_spec: RevisedSpecInput | None = None
    lessons: list[LessonInput] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class RevisedSpecProposal(BaseModel):
    base_label: str
    base_gen_id: str | None
    mode: Mode
    locked: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    open_parameters: list[str] = Field(default_factory=list)


class FeedbackInterpretation(BaseModel):
    evaluation: EvaluationEntry
    revised_spec: RevisedSpecProposal | None = None
    lessons: list[LessonInput] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    strike: StrikeStatus = Field(default_factory=StrikeStatus)
