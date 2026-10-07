from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_shell.guard.gate import ConfirmRequest, Confirmer
from agent_shell.tools.registry import EffectClass

_NS = uuid.UUID("5f0c7a2e-6d1b-4e7e-9a55-3b8d2c1f0a11")


class Proposal(BaseModel):
    """A write the session suggests but has not made."""

    kind: str                       # e.g. "lesson", "interpretation"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    # The registry tool that carries this write out when the proposal is accepted (payload =
    # its arguments). None means the caller applies it.
    tool: str | None = None

    @property
    def id(self) -> str:
        return draft_id(self.kind, self.payload or {"summary": self.summary})


class ProposalReport(BaseModel):
    accepted: list[Proposal] = Field(default_factory=list)
    deferred: list[Proposal] = Field(default_factory=list)
    skipped: list[Proposal] = Field(default_factory=list)


def draft_id(kind: str, payload: dict[str, Any]) -> str:
    """Stable id, so deferring the same thing twice writes one file."""
    return str(uuid.uuid5(_NS, kind + json.dumps(payload, sort_keys=True, default=str)))


def write_draft(drafts_dir: Path, kind: str, payload: dict[str, Any], **extra: Any) -> Path:
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{draft_id(kind, payload)}.json"
    path.write_text(
        json.dumps({"kind": kind, "payload": payload, **extra}, indent=2, default=str),
        encoding="utf-8",
    )
    return path


async def walk_proposals(
    proposals: list[Proposal], confirmer: Confirmer, drafts_dir: Path
) -> ProposalReport:
    """y/n/edit/defer through each proposal. The caller writes the accepted ones."""
    report = ProposalReport()
    for p in proposals:
        decision = await confirmer.ask(ConfirmRequest(
            tool=f"proposal:{p.kind}", effect=EffectClass.MEMORY_WRITE,
            args=p.payload, preview=p.summary,
            allowed=("accept", "reject", "edit", "defer"),
        ))
        if decision.kind == "accept":
            report.accepted.append(p)
        elif decision.kind == "edit":
            report.accepted.append(p.model_copy(update={"payload": decision.payload or p.payload}))
        elif decision.kind == "defer":
            write_draft(drafts_dir, p.kind, p.payload, summary=p.summary, tool=p.tool)
            report.deferred.append(p)
        else:
            report.skipped.append(p)
    return report
