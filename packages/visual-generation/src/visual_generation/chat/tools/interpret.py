from __future__ import annotations

from agent_shell.proposals import Proposal
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec

from visual_generation.chat.interpretation import (
    InterpretationError,
    build_interpretation,
    gather_context,
    render_interpretation,
    render_lesson,
)
from visual_generation.chat.schemas import EvaluationInput, InterpretationInput
from visual_generation.chat.state import ChatState, evaluation_key, lesson_key
from visual_generation.chat.tools._common import fail, ok, project_note

# Only the model-facing evaluation fields are the arguments of `record_evaluation`.
EVALUATION_FIELDS = set(EvaluationInput.model_fields)


def make_interpret_tools(state: ChatState) -> list[ToolSpec]:
    async def propose(a: InterpretationInput) -> ToolResult:
        try:
            ctx = await gather_context(state, a)
            fi = build_interpretation(a, ctx)
        except InterpretationError as e:
            return fail(str(e), data={"open_questions": e.open_questions} if e.open_questions else None)

        # Remember what is proposed, so anything not written by /exit is offered again.
        eval_args = a.model_dump(mode="json", include=EVALUATION_FIELDS)
        state.propose(evaluation_key(fi.evaluation.entry_id), Proposal(
            kind="evaluation", tool="record_evaluation", payload=eval_args,
            summary=f"Record the evaluation of {ctx.resolver.display(fi.evaluation.gen_id)}: "
                    f"{fi.evaluation.reaction}, “{fi.evaluation.raw_feedback[:80]}”",
        ))
        for le in fi.lessons:
            state.propose(lesson_key(le.statement), Proposal(
                kind="lesson", tool="add_lesson", payload=le.model_dump(mode="json"),
                summary="Add lesson: " + render_lesson(le).replace("\n", " "),
            ))
        return ok(render_interpretation(fi, ctx.resolver), data={
            "evaluation_id": fi.evaluation.entry_id, "gen_id": fi.evaluation.gen_id,
            "raw_feedback": fi.evaluation.raw_feedback, "reaction": fi.evaluation.reaction,
            "agent_status": fi.evaluation.agent_status, "strike": fi.strike.model_dump(),
            "open_questions": fi.open_questions, "lessons": len(fi.lessons),
        })

    return [ToolSpec(
        name="propose_interpretation", effect=EffectClass.NONE, input_model=InterpretationInput, handler=propose,
        description=(
            "Structure the director's feedback as a PROPOSAL (nothing is stored). YOU read the feedback "
            "and pass: the attempt, the verbatim words, their reaction, what to keep and change, findings "
            "(layer, observed/inferred/unresolved, basis), and any lesson candidates and revised spec. "
            "Labels are resolved; unresolved ones become open questions. Rules are enforced here: identity, "
            "staging and set failures are conditioning problems unless you give evidence; a prompt-layer "
            "lesson about them needs a falsification test; 'validated' needs 5+ held-out results; a fourth "
            "same-class redraft needs an architecture question; you may not invent numbers. To write it, "
            "call record_evaluation (and add_lesson), which the director confirms. " + project_note(state)
        ),
    )]
