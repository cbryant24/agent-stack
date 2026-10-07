"""Interpretation models. Phase 4 extends these (evaluation records)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The three score layers are kept separate (project-instructions.md "Evaluation model").
Layer = Literal["platform", "agent_correctness", "production_quality"]
Category = Literal["identity", "staging", "set", "prompt", "settings", "model", "other"]
Attribution = Literal["conditioning", "settings", "prompt", "model", "unknown"]
Status = Literal["observed", "inferred", "unresolved"]

# Failures in these categories are conditioning/asset problems until shown otherwise.
CONDITIONING_FIRST = frozenset({"identity", "staging", "set"})


class ObservationInput(BaseModel):
    """One claim the director's feedback supports, as read by the model."""

    label: str | None = Field(default=None, description="The attempt this is about, e.g. 'attempt-07'.")
    layer: Layer
    category: Category
    attribution: Attribution
    claim: str
    status: Status = "inferred"
    evidence: str = Field(default="", description="What shows it; required to attribute an identity, "
                          "staging or set failure to anything but conditioning.")


class SuggestedRedraftInput(BaseModel):
    label: str
    change: str


class InterpretationInput(BaseModel):
    feedback: str
    observations: list[ObservationInput]
    suggested_redraft: SuggestedRedraftInput | None = None
    open_questions: list[str] = Field(default_factory=list)


class Observation(ObservationInput):
    resolved_gen_id: str | None = None


class SuggestedRedraft(BaseModel):
    label: str
    resolved_gen_id: str | None
    change: str


class FeedbackInterpretation(BaseModel):
    feedback: str
    observations: list[Observation]
    suggested_redraft: SuggestedRedraft | None = None
    open_questions: list[str] = Field(default_factory=list)
