"""The experiment record a paid run must carry (project-instructions.md, "experiment discipline").

A plan is given before the spend, shown in the confirm panel, written to the audit log, and saved
with the ids of the generations it produced, so an evaluation of any of them can name the question
the run was meant to answer.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from visual_generation.chat.state import ChatState
from visual_generation.models import EvaluationEntry

REFUSAL = (
    "{tool} refused: no AttemptPlan. Before a paid run, give: question, baseline_attempt (or none), "
    "hypothesis, changed_variable, controlled_variables, acceptance_gate, stop_rule, session_cost_cap_usd."
)


class AttemptPlan(BaseModel):
    question: str = Field(description="The single question this run answers.")
    baseline_attempt: str | None = Field(default=None, description="The attempt it is compared against, if any.")
    hypothesis: str
    changed_variable: str = Field(description="One, unless the test studies a bundle.")
    controlled_variables: list[str] = Field(default_factory=list)
    acceptance_gate: str
    stop_rule: str
    session_cost_cap_usd: float = Field(gt=0, description="Hard ceiling for this run, in USD.")


def attempt_id(project: str | None, plan: AttemptPlan) -> str:
    digest = hashlib.sha1(json.dumps(plan.model_dump(), sort_keys=True).encode()).hexdigest()[:4]
    return f"{project or 'adhoc'}-{datetime.now(UTC):%Y-%m-%d}-{digest}"


def render_attempt(plan: AttemptPlan, aid: str) -> list[str]:
    return [
        f"Attempt plan  ({aid})",
        f"  Question:     {plan.question}",
        f"  Baseline:     {plan.baseline_attempt or 'none'}",
        f"  Hypothesis:   {plan.hypothesis}",
        f"  Changed:      {plan.changed_variable}",
        f"  Controlled:   {'; '.join(plan.controlled_variables) or 'none listed'}",
        f"  Accept when:  {plan.acceptance_gate}",
        f"  Stop rule:    {plan.stop_rule}",
        f"  Cost cap:     ${plan.session_cost_cap_usd:.2f}, hard. The run stops before the render that would pass it.",
    ]


def save_attempt(state: ChatState, aid: str, plan: AttemptPlan, *, tool: str, generation_ids: list[str],
                 outputs: list[str] | None = None, status: str = "") -> str:
    """Write (or extend) `attempts/<id>.json` and the audit record. Returns the file path."""
    path = state.data_dir / "attempts" / f"{aid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"attempt_id": aid, "plan": plan.model_dump(), "runs": []}
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
    record["runs"].append({
        "at": datetime.now(UTC).isoformat(), "tool": tool, "session_id": state.session_id,
        "generation_ids": generation_ids, "outputs": outputs or [], "status": status,
    })
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    state.audit(kind="attempt_plan", attempt_id=aid, tool=tool, plan=plan.model_dump(),
                generation_ids=generation_ids, outputs=outputs or [], status=status)
    return str(path)


def attempt_for(state: ChatState, gen_id: str) -> dict[str, Any] | None:
    """The saved attempt whose run produced `gen_id`, if any."""
    folder = state.data_dir / "attempts"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if any(gen_id in run.get("generation_ids", []) for run in record.get("runs", [])):
            return record
    return None


def link_attempt(state: ChatState, entry: EvaluationEntry) -> EvaluationEntry:
    """Tie an evaluation to the attempt its generation was rendered under: set `attempt_id`, and
    use the plan's question when the evaluation gives none."""
    record = attempt_for(state, entry.gen_id)
    if record is None:
        return entry
    update: dict[str, Any] = {"attempt_id": record["attempt_id"]}
    if not entry.question:
        update["question"] = (record.get("plan") or {}).get("question")
    return entry.model_copy(update=update)
