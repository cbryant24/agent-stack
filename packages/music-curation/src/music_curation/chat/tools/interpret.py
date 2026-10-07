from __future__ import annotations

from agent_shell.proposals import Proposal
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec

from music_curation.chat.schemas import ReactionInput, ReportArgs, check_reaction
from music_curation.chat.state import ChatState, reaction_key, taste_key
from music_curation.chat.tools._common import fail, ok, resolve_ref, title_of

REPORT_FIELDS = set(ReportArgs.model_fields)


def render_proposal(target: str, a: ReactionInput, notes: list[str], questions: list[str]) -> str:
    rating = f" ★{a.rating}" if a.rating is not None else ""
    lines = [f"PROPOSED (nothing is stored): reaction to {target}  [{a.reaction.upper().replace('_', ' ')}{rating}]",
             f"  Feedback (verbatim): {a.raw_feedback}"]
    if a.notes:
        lines.append(f"  Notes (what to change): {a.notes}")
    if a.context:
        lines.append(f"  Context (why): {a.context}")
    lines += [f"  Taste lesson candidate [{t.valence}/{t.scope}]: {t.statement}" for t in a.taste_lessons]
    lines += [f"  note: {n}" for n in notes]
    lines += [f"  OPEN QUESTION: {q}" for q in questions]
    lines.append("To record it, call report (the director confirms). Offer each taste lesson with taste_add, one at a time."
                 if not questions else "Ask the director the open question(s) before calling report.")
    return "\n".join(lines)


def make_interpret_tools(state: ChatState) -> list[ToolSpec]:
    async def propose(a: ReactionInput) -> ToolResult:
        checked = check_reaction(a)
        if checked.refusals:
            return fail("; ".join(checked.refusals), data={"open_questions": checked.open_questions})
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        if not checked.open_questions:
            payload = a.model_dump(mode="json", include=REPORT_FIELDS)
            payload["generation"] = gen_id
            state.propose(reaction_key(gen_id), Proposal(
                kind="reaction", tool="report", payload=payload,
                summary=f"Record {a.reaction} on {title_of(state, gen_id)}: “{a.raw_feedback[:80]}”"))
            for t in a.taste_lessons:
                state.propose(taste_key(t.statement), Proposal(
                    kind="taste", tool="taste_add", payload=t.model_dump(mode="json"),
                    summary=f"Add taste lesson [{t.valence}/{t.scope}]: {t.statement[:100]}"))
        return ok(render_proposal(title_of(state, gen_id), a, checked.notes, checked.open_questions), data={
            "gen_id": gen_id, "reaction": a.reaction, "raw_feedback": a.raw_feedback,
            "open_questions": checked.open_questions, "taste_lessons": len(a.taste_lessons),
        })

    return [ToolSpec(
        name="propose_reaction", effect=EffectClass.NONE, input_model=ReactionInput, handler=propose,
        description=(
            "Structure the director's feedback on a Suno result as a PROPOSAL (nothing is stored). YOU read the "
            "feedback and pass: the generation, their verbatim words, the reaction, an optional rating, notes (what "
            "to change) and context (why), whether Suno rendered what the prompt asked for, and any taste-lesson "
            "candidates. Rules enforced here: 'disliked' is a taste verdict on a faithful render, 'prompt_failed' is "
            "Suno not rendering the prompt, and the two are never swapped; if you do not know which, it comes back as "
            "an open question; a track that was never heard takes no rating. To write it, call report, then "
            "taste_add for each lesson the director accepts."
        ),
    )]
