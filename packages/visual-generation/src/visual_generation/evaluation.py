"""Evaluation records: recording, the trusted-execution marking, strike counting, and the
number-grounding rule.

The owner of `visual_generation_memory` is this package, so every write goes through functions
here and on the store; the chat tools call them and add the confirmation gate.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date

from pydantic import BaseModel

from visual_generation.constants import POSITIVE_REACTIONS, REACTION_PENDING, REACTIONS
from visual_generation.models import (
    EvaluationEntry,
    Evidence,
    Finding,
    Layer,
    VisualGeneration,
)
from visual_generation.report import report
from visual_generation.store import VisualGenerationStore

STRIKE_LIMIT = 3
EXECUTION_TRUTH_ENV = "EXECUTION_TRUTH_VERIFIED_SINCE"
_NS = uuid.UUID("a6c1d1c4-3f0e-4c58-8b7e-5d2f9e6b7a10")

PRE_FIX_STATEMENT = (
    "The recorded seed may not match the submitted graph: this generation predates the date "
    f"execution was verified ({EXECUTION_TRUTH_ENV} is unset or later than its creation), so its "
    "agent-correctness status stays unresolved."
)


class EvaluationPartialWrite(RuntimeError):
    """The evaluation point was written but setting the generation's reaction failed."""

    def __init__(self, entry: EvaluationEntry, cause: Exception) -> None:
        super().__init__(
            f"evaluation {entry.entry_id} was written, but recording the reaction on generation "
            f"{entry.gen_id} failed ({type(cause).__name__}: {cause}). Re-running is safe: the "
            "evaluation id is stable."
        )
        self.entry, self.cause = entry, cause


def evaluation_id(gen_id: str, reaction: str, raw_feedback: str) -> str:
    """Stable id: confirming or retrying the same evaluation never creates a duplicate."""
    return str(uuid.uuid5(_NS, f"{gen_id}\x1f{reaction}\x1f{raw_feedback}"))


def is_negative(reaction: str) -> bool:
    return reaction != REACTION_PENDING and reaction not in POSITIVE_REACTIONS


# ── trusted-execution marking ───────────────────────────────────────────────


def execution_truth_verified_since() -> str | None:
    """The ISO date from which recorded execution is trusted, or None (nothing is trusted yet)."""
    raw = os.environ.get(EXECUTION_TRUTH_ENV, "").strip()
    if not raw:
        return None
    try:
        date.fromisoformat(raw[:10])
    except ValueError as e:
        raise ValueError(f"{EXECUTION_TRUTH_ENV}={raw!r} is not an ISO date (YYYY-MM-DD)") from e
    return raw


def is_pre_fix(gen: VisualGeneration, since: str | None = None) -> bool:
    since = since if since is not None else execution_truth_verified_since()
    return since is None or gen.created_at < since


def apply_execution_truth(
    entry: EvaluationEntry, gen: VisualGeneration, since: str | None = None
) -> EvaluationEntry:
    """For a generation made before execution was verified: `agent_status` becomes
    "unresolved" and a finding says why (added once)."""
    if not is_pre_fix(gen, since):
        return entry
    findings = list(entry.findings)
    if not any(f.statement == PRE_FIX_STATEMENT for f in findings):
        findings.append(Finding(
            layer=Layer.AGENT_CORRECTNESS, evidence=Evidence.UNRESOLVED, statement=PRE_FIX_STATEMENT,
            basis=f"generation created_at={gen.created_at}; seed field={gen.seed}",
            suggested_action="Re-run the seed check (Gate 0) before trusting this record's execution.",
        ))
    return entry.model_copy(update={"agent_status": "unresolved", "findings": findings})


# ── three strikes ───────────────────────────────────────────────────────────


class StrikeStatus(BaseModel):
    strike_class: str | None = None
    count: int = 0
    blocked: bool = False


def strike_status(
    evaluations: list[EvaluationEntry], strike_class: str | None = None
) -> StrikeStatus:
    """How many consecutive negative evaluations of one fix class stand since the last recorded
    architecture question. `strike_class` defaults to the latest evaluation's class. Blocked at
    STRIKE_LIMIT: the next same-class attempt needs a written architecture question first."""
    ordered = sorted(evaluations, key=lambda e: e.created_at)
    if strike_class is None:
        strike_class = next((e.strike_class for e in reversed(ordered) if e.strike_class), None)
    if strike_class is None:
        return StrikeStatus()
    count = 0
    for e in reversed([e for e in ordered if e.strike_class == strike_class]):
        if e.architecture_question is not None or not is_negative(e.reaction):
            break
        count += 1
    return StrikeStatus(strike_class=strike_class, count=count, blocked=count >= STRIKE_LIMIT)


# ── numbers come from the record or the director, never from the model ──────

_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_LABEL = re.compile(r"(?:attempt[-_ ]?|#)\d+", re.I)


def ungrounded_numbers(texts: list[str], allowed_text: str) -> list[str]:
    """Numbers appearing in `texts` that are not in `allowed_text` (the director's words plus the
    base generation's recipe). Attempt labels like 'attempt-07' are not numeric values."""
    allowed = set(_NUMBER.findall(_LABEL.sub(" ", allowed_text)))
    found: list[str] = []
    for t in texts:
        for n in _NUMBER.findall(_LABEL.sub(" ", t)):
            if n not in allowed and n not in found:
                found.append(n)
    return found


# ── recording ───────────────────────────────────────────────────────────────


async def record_evaluation(
    entry: EvaluationEntry, *, store: VisualGenerationStore
) -> EvaluationEntry:
    """Write the evaluation point, then set the generation's reaction through `report` so
    `review-pending`, `digest` and retrieval keep working.

    Raises LookupError for an unknown generation, ValueError for an unusable reaction or rating,
    and EvaluationPartialWrite if only the second step failed (the id is stable, so a retry is
    safe). Marks pre-verification generations (see `apply_execution_truth`)."""
    if entry.reaction not in REACTIONS:
        raise ValueError(f"reaction must be one of {', '.join(REACTIONS)}, not {entry.reaction!r}")
    await store.ensure_collection()
    gen = await store.get_generation(entry.gen_id)
    if gen is None:
        raise LookupError(f"no generation with id {entry.gen_id}")
    entry = apply_execution_truth(entry, gen)
    await store.upsert_evaluation(entry)
    try:
        await report(
            entry.gen_id, entry.reaction, rating=entry.rating,
            notes="; ".join(entry.change) or None, context=entry.raw_feedback, store=store,
        )
    except Exception as e:  # noqa: BLE001
        raise EvaluationPartialWrite(entry, e) from e
    return entry


async def list_evaluations(
    store: VisualGenerationStore,
    *,
    gen_id: str | None = None,
    chain_root_id: str | None = None,
    project: str | None = None,
) -> list[EvaluationEntry]:
    await store.ensure_collection()
    return await store.list_evaluations(gen_id=gen_id, chain_root_id=chain_root_id, project=project)


def render_evaluations(entries: list[EvaluationEntry]) -> str:
    if not entries:
        return "No evaluations."
    lines = [f"{len(entries)} evaluation(s):"]
    for e in entries:
        rating = f" ★{e.rating}" if e.rating is not None else ""
        status = f"  agent_status={e.agent_status}" if e.agent_status else ""
        lines.append(f"  {e.entry_id[:8]}  gen {e.gen_id[:8]}  [{e.reaction.upper().replace('_', ' ')}{rating}]{status}")
        lines.append(f"    “{e.raw_feedback[:100]}”")
        for f in e.findings[:3]:
            lines.append(f"    - ({f.evidence.value}) {f.layer.value}: {f.statement[:90]}")
        if e.strike_class:
            lines.append(f"    strike class: {e.strike_class}")
    return "\n".join(lines)
