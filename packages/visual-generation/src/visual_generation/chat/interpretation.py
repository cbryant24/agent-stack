"""propose_interpretation: validate and resolve the model's reading of the director's feedback.

Pure: no store, no file, no network. Generations are preloaded into the LabelResolver by the
caller. The model does the reading; this checks it against the repo's rules and resolves
labels. Nothing is stored (Phase 4 adds the confirmed write).
"""

from __future__ import annotations

from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.schemas import (
    CONDITIONING_FIRST,
    FeedbackInterpretation,
    InterpretationInput,
    Observation,
    SuggestedRedraft,
)


class InterpretationError(ValueError):
    """The interpretation breaks a rule; the message tells the model how to fix it."""


def interpret(inp: InterpretationInput, resolver: LabelResolver) -> FeedbackInterpretation:
    questions = list(dict.fromkeys(q.strip() for q in inp.open_questions if q.strip()))
    observations: list[Observation] = []

    for i, obs in enumerate(inp.observations, 1):
        if (
            obs.category in CONDITIONING_FIRST
            and obs.attribution != "conditioning"
            and not obs.evidence.strip()
        ):
            raise InterpretationError(
                f"observation {i}: {obs.category} failures are conditioning or asset problems "
                f"until shown otherwise. Attribute it to 'conditioning', or give `evidence` "
                f"for attributing it to {obs.attribution!r}."
            )
        resolved: str | None = None
        if obs.label:
            res = resolver.resolve(obs.label)
            resolved = res.gen_id
            if resolved is None:
                questions.append(f"Which generation is {obs.label!r}? ({res.reason})")
        observations.append(Observation(**obs.model_dump(), resolved_gen_id=resolved))

    redraft: SuggestedRedraft | None = None
    if inp.suggested_redraft is not None:
        res = resolver.resolve(inp.suggested_redraft.label)
        if res.gen_id is None:
            questions.append(
                f"Which generation should the redraft start from, {inp.suggested_redraft.label!r}? "
                f"({res.reason})"
            )
        redraft = SuggestedRedraft(
            label=inp.suggested_redraft.label,
            resolved_gen_id=res.gen_id,
            change=inp.suggested_redraft.change,
        )

    return FeedbackInterpretation(
        feedback=inp.feedback,
        observations=observations,
        suggested_redraft=redraft,
        open_questions=list(dict.fromkeys(questions)),
    )


def render_interpretation(fi: FeedbackInterpretation, resolver: LabelResolver) -> str:
    lines = [f"Interpretation of: {fi.feedback.strip()[:200]}", ""]
    for o in fi.observations:
        target = f" [{resolver.display(o.resolved_gen_id)}]" if o.resolved_gen_id else (
            f" [{o.label}: unresolved]" if o.label else ""
        )
        lines.append(
            f"- ({o.status}) {o.layer} / {o.category} -> {o.attribution}{target}: {o.claim}"
        )
        if o.evidence:
            lines.append(f"    evidence: {o.evidence}")
    if fi.suggested_redraft is not None:
        r = fi.suggested_redraft
        where = resolver.display(r.resolved_gen_id) if r.resolved_gen_id else f"{r.label} (unresolved)"
        lines.append(f"\nSuggested redraft of {where}: {r.change}")
    if fi.open_questions:
        lines.append("\nOpen questions:")
        lines.extend(f"- {q}" for q in fi.open_questions)
    lines.append("\nProposal only: nothing was stored.")
    return "\n".join(lines)
