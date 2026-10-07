"""Turn the model's reading of the director's feedback into an evaluation proposal.

`build_interpretation` is pure: everything it needs (resolved labels, the generations involved,
the chain's earlier evaluations, session facts) is gathered first into an `EvalContext`. It applies
the guardrails in code:

  * a prompt-layer lesson about identity, staging or set needs a falsification test;
  * "validated" needs evidence_n >= 5 and a held-out evaluation id that exists;
  * a redraft proposal after three same-class failures needs an architecture question;
  * numbers in a proposal come from the director's words or the attempt's own recipe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.resolve import resolve_ref, resolver_for
from visual_generation.chat.schemas import (
    EvaluationInput,
    FeedbackInterpretation,
    InterpretationInput,
    LessonInput,
    RevisedSpecProposal,
)
from visual_generation.chat.state import ChatState
from visual_generation.curation import lesson_rule_violations
from visual_generation.evaluation import (
    apply_execution_truth,
    evaluation_id,
    execution_truth_verified_since,
    strike_status,
    ungrounded_numbers,
)
from visual_generation.models import EvaluationEntry, KeepConstraint, VisualGeneration


class InterpretationError(ValueError):
    """The proposal breaks a rule; the message tells the model what to change."""

    def __init__(self, message: str, open_questions: list[str] | None = None) -> None:
        super().__init__(message)
        self.open_questions = open_questions or []


@dataclass
class EvalContext:
    resolver: LabelResolver
    resolved: dict[str, tuple[str | None, str]]            # label -> (generation id, reason if None)
    gens: dict[str, VisualGeneration]                        # generations the input refers to
    prior_evals: list[EvaluationEntry]                       # earlier evaluations in the chain
    known_eval_ids: set[str] = field(default_factory=set)    # held-out ids that exist in memory
    project: str | None = None
    session_id: str = ""
    engine_provider: str = ""
    engine_model: str = ""
    now: str = ""
    since: str | None = None


def recipe_text(gen: VisualGeneration) -> str:
    """Everything numeric the generation's own record contains (what the model may cite)."""
    parts = [gen.prompt, gen.negative_prompt or "", json.dumps(gen.settings), str(gen.seed),
             str(gen.width), str(gen.height)]
    parts += [f"{lr.name} {lr.strength}" for lr in gen.lora_stack]
    return " ".join(parts)


def _labels(inp: EvaluationInput) -> list[str]:
    out = [inp.generation, *[k.source for k in inp.keep]]
    base = getattr(inp, "revised_spec", None)
    if base is not None:
        out.append(base.base)
    return list(dict.fromkeys(out))


async def gather_context(state: ChatState, inp: EvaluationInput) -> EvalContext:
    """The reads the pure builder needs. Raises InterpretationError if the evaluated generation
    cannot be resolved (nothing can be recorded against an unknown attempt)."""
    store, _ = state.stores()
    resolver = await resolver_for(state)
    resolved: dict[str, tuple[str | None, str]] = {}
    for label in _labels(inp):
        resolved[label] = await resolve_ref(state, label)
    gen_id, why = resolved[inp.generation]
    if gen_id is None:
        raise InterpretationError(
            f"Could not resolve {inp.generation!r}: {why}",
            [f"Which generation is {inp.generation!r}? ({why})"],
        )
    gens: dict[str, VisualGeneration] = {}
    for gid, _why in resolved.values():
        if gid and gid not in gens:
            g = await store.get_generation(gid)
            if g is not None:
                gens[gid] = g
    if gen_id not in gens:
        raise InterpretationError(f"No generation with id {gen_id}.")
    chain_root = gens[gen_id].chain_root_id
    prior = await store.list_evaluations(chain_root_id=chain_root)
    known: set[str] = set()
    for lesson in getattr(inp, "lessons", []):
        if lesson.held_out_eval_id and await store.get_evaluation(lesson.held_out_eval_id) is not None:
            known.add(lesson.held_out_eval_id)
    return EvalContext(
        resolver=resolver, resolved=resolved, gens=gens, prior_evals=prior, known_eval_ids=known,
        project=state.project, session_id=state.session_id, engine_provider=state.engine_provider,
        engine_model=state.engine_model, now=datetime.now(UTC).isoformat(),
        since=execution_truth_verified_since(),
    )


def build_evaluation(inp: EvaluationInput, ctx: EvalContext) -> tuple[EvaluationEntry, list[str]]:
    """The evaluation that would be written, plus open questions raised on the way."""
    questions: list[str] = []
    gen_id = ctx.resolved[inp.generation][0]
    assert gen_id is not None
    gen = ctx.gens[gen_id]

    keep: list[KeepConstraint] = []
    for k in inp.keep:
        sid, why = ctx.resolved.get(k.source, (None, "not resolved"))
        if sid is None:
            questions.append(f"Which generation is {k.source!r}, to keep the {k.attribute!r} from? ({why})")
        else:
            keep.append(KeepConstraint(attribute=k.attribute, source_gen_id=sid))

    bad = ungrounded_numbers(inp.change, inp.raw_feedback + " " + recipe_text(gen))
    if bad:
        raise InterpretationError(
            f"`change` contains numbers that are not in the director's words or the attempt's own "
            f"recipe ({', '.join(bad)}). Numbers come from the record or the director: describe the "
            "change in words and list the value as an open_parameter for the director to decide."
        )

    entry = EvaluationEntry(
        entry_id=evaluation_id(gen_id, inp.reaction, inp.raw_feedback),
        gen_id=gen_id, chain_root_id=gen.chain_root_id, project=ctx.project or gen.project,
        question=inp.question, reaction=inp.reaction, rating=inp.rating, raw_feedback=inp.raw_feedback,
        keep=keep, change=inp.change, findings=inp.findings, required_outcomes=inp.required_outcomes,
        infrastructure_status=inp.infrastructure_status, agent_status=inp.agent_status,
        visual_status=inp.visual_status, director_signoff=inp.director_signoff,
        strike_class=inp.strike_class, architecture_question=inp.architecture_question,
        session_id=ctx.session_id, engine_provider=ctx.engine_provider, engine_model=ctx.engine_model,
        created_at=ctx.now or datetime.now(UTC).isoformat(),
    )
    return apply_execution_truth(entry, gen, ctx.since), questions


def build_interpretation(inp: InterpretationInput, ctx: EvalContext) -> FeedbackInterpretation:
    entry, questions = build_evaluation(inp, ctx)
    questions = list(dict.fromkeys([*[q.strip() for q in inp.open_questions if q.strip()], *questions]))

    # Three strikes: counting this evaluation, a redraft would be a fourth same-class attempt.
    strike = strike_status([*ctx.prior_evals, entry], inp.strike_class)
    revised: RevisedSpecProposal | None = None
    if inp.revised_spec is not None:
        rs = inp.revised_spec
        if rs.mode == "redraft" and strike.blocked:
            raise InterpretationError(
                f"{strike.count} attempts at fix class {strike.strike_class!r} have failed in this chain. "
                "Before a fourth redraft, record a written architecture question: set "
                "`architecture_question` (the layer being blamed and a DIFFERENT layer that could be at "
                "fault), or propose a change at another layer (new_draft, refine_img2img or inpaint)."
            )
        bad = ungrounded_numbers(rs.changes, inp.raw_feedback + " " + recipe_text(ctx.gens[entry.gen_id]))
        if bad:
            raise InterpretationError(
                f"`revised_spec.changes` contains numbers that are not in the director's words or the "
                f"attempt's own recipe ({', '.join(bad)}). Put new values in `open_parameters` for the "
                "director to decide; do not invent them."
            )
        base_id, why = ctx.resolved.get(rs.base, (None, "not resolved"))
        if base_id is None:
            questions.append(f"Which generation should the revision start from, {rs.base!r}? ({why})")
        revised = RevisedSpecProposal(
            base_label=rs.base, base_gen_id=base_id, mode=rs.mode, locked=rs.locked,
            changes=rs.changes, open_parameters=rs.open_parameters,
        )

    problems: list[str] = []
    lessons: list[LessonInput] = []
    for i, le in enumerate(inp.lessons, 1):
        found = lesson_rule_violations(
            statement=le.statement, layer=le.layer.value, topic=le.topic, claim_level=le.claim_level,
            evidence_n=le.evidence_n, falsification_test=le.falsification_test,
            held_out_eval_exists=bool(le.held_out_eval_id and le.held_out_eval_id in ctx.known_eval_ids),
        )
        problems += [f"lesson {i}: {p}" for p in found]
        lessons.append(le.model_copy(update={"source_eval_ids": le.source_eval_ids or [entry.entry_id]}))
    if problems:
        raise InterpretationError("; ".join(problems))

    return FeedbackInterpretation(
        evaluation=entry, revised_spec=revised, lessons=lessons, open_questions=questions, strike=strike,
    )


# ── rendering (what the director sees) ──────────────────────────────────────


def render_entry(entry: EvaluationEntry, resolver: LabelResolver) -> str:
    rating = f" ★{entry.rating}" if entry.rating is not None else ""
    lines = [
        f"Evaluation of {resolver.display(entry.gen_id)}  [{entry.reaction.upper().replace('_', ' ')}{rating}]",
        f"  Feedback (verbatim): {entry.raw_feedback}",
    ]
    if entry.question:
        lines.append(f"  Question this attempt answered: {entry.question}")
    if entry.attempt_id:
        lines.append(f"  Attempt plan: {entry.attempt_id}")
    for k in entry.keep:
        lines.append(f"  Keep: {k.attribute} (from {resolver.display(k.source_gen_id)})")
    for c in entry.change:
        lines.append(f"  Change: {c}")
    for o in entry.required_outcomes:
        lines.append(f"  Required outcome: {o}")
    for f in entry.findings:
        lines.append(f"  Finding ({f.evidence.value}) [{f.layer.value}]: {f.statement}")
        if f.basis:
            lines.append(f"      basis: {f.basis}")
        if f.suggested_action:
            lines.append(f"      suggested: {f.suggested_action}")
    statuses = {k: v for k, v in (("infrastructure", entry.infrastructure_status), ("agent", entry.agent_status),
                                  ("visual", entry.visual_status)) if v}
    if statuses:
        lines.append("  Status: " + ", ".join(f"{k}={v}" for k, v in statuses.items()))
    if entry.director_signoff:
        lines.append("  Director sign-off: yes")
    if entry.strike_class:
        lines.append(f"  Strike class: {entry.strike_class}")
    if entry.architecture_question:
        q = entry.architecture_question
        lines.append(f"  Architecture question: blaming {q.layer_blamed.value}, alternative "
                     f"{q.alternative_layer.value}: {q.question}")
    return "\n".join(lines)


def render_lesson(le: LessonInput) -> str:
    lines = [f"[{le.valence}/{le.scope}] layer={le.layer.value} claim={le.claim_level} n={le.evidence_n}",
             f"  {le.statement}"]
    if le.falsification_test:
        lines.append(f"  falsification test: {le.falsification_test}")
    return "\n".join(lines)


def render_interpretation(fi: FeedbackInterpretation, resolver: LabelResolver) -> str:
    lines = [render_entry(fi.evaluation, resolver)]
    if fi.strike.strike_class:
        lines.append(f"\nStrikes for {fi.strike.strike_class!r}: {fi.strike.count} of 3"
                     + (" (BLOCKED: a redraft needs an architecture question)" if fi.strike.blocked else ""))
    if fi.revised_spec is not None:
        r = fi.revised_spec
        where = resolver.display(r.base_gen_id) if r.base_gen_id else f"{r.base_label} (unresolved)"
        lines.append(f"\nProposed revision ({r.mode}) of {where}:")
        lines += [f"  lock: {x}" for x in r.locked] + [f"  change: {x}" for x in r.changes]
        lines += [f"  director to decide: {x}" for x in r.open_parameters]
    if fi.lessons:
        lines.append(f"\n{len(fi.lessons)} lesson candidate(s), offered one at a time, never auto-confirmed:")
        lines += [render_lesson(le) for le in fi.lessons]
    if fi.open_questions:
        lines.append("\nOpen questions:")
        lines += [f"- {q}" for q in fi.open_questions]
    lines.append("\nProposal only: nothing was stored. Writing it needs `record_evaluation` (you confirm).")
    return "\n".join(lines)
