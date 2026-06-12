"""Shared vector-DB diagnostic types.

These live in agent-runtime because they cross the orchestrator/owning-agent
boundary: the orchestrator (a reader) writes the diagnosis, and the owning agent
(the writer) consumes it to perform a remediation under its own ownership. Putting
``DiagnosticReport`` / ``RemediationSpec`` / ``RemediationOutcome`` here keeps the
import direction clean — an owning agent (e.g. music-curation) can implement a
remediation handler without importing the orchestrator package.

The orchestrator owns everything *around* these types — the report's markdown
render/load, the behavioral probe, the ``RemediationHandler`` protocol + registry,
and ``delegate_remediation`` — in ``orchestrator/diagnostics.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["open", "delegated", "fixed"]


class RemediationSpec(BaseModel):
    """A machine-readable instruction for an owning agent's remediation handler —
    *not* prose. A handler executes this against its own collection.

    Designed to grow: ``kind`` is the only fix shape implemented so far (``retag``
    — rewrite payload fields, no re-embedding), but a future ``reembed`` (the
    cross-model embedding-space fix) slots in here.

    For ``retag``: ``match`` is the target payload filter (field → value pairs,
    AND-combined) selecting the points to rewrite, and ``set`` is the payload
    changes to apply to each matched point.
    """

    kind: Literal["retag"]
    match: dict[str, Any] = Field(default_factory=dict)
    set: dict[str, Any] = Field(default_factory=dict)


class DiagnosticReport(BaseModel):
    """A diagnose-only finding about one collection. Written to the reports vault as
    markdown with YAML frontmatter; `status` moves open → delegated → fixed.

    When a `remediation` spec is attached, the report is machine-actionable: the
    owning agent's handler executes the spec under its own ownership and the report
    itself (status transitions + evidence) is the audit record for that write."""

    collection: str
    owning_agent: str
    symptom: str
    diagnosis: str
    # filter/threshold/model read from code + actual payloads/scores from Qdrant.
    evidence: dict[str, Any] = Field(default_factory=dict)
    proposed_fix: str
    remediation: RemediationSpec | None = None
    status: Status = "open"
    created_at: str = ""
    run_id: str = ""

    def stamp(self) -> DiagnosticReport:
        """Fill created_at if unset (kept separate so callers can inject a fixed
        timestamp in tests). Returns self for chaining."""
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        return self


@dataclass
class RemediationOutcome:
    """Returned by a remediation handler. `status` is the new report status the
    handler achieved (``fixed`` when the write succeeded; ``open`` when the handler
    refused — e.g. a malformed/unsupported spec — so the report stays a manual work
    order rather than stranding at ``delegated``). `detail` is a human-readable note
    recorded on the report."""

    status: Status
    detail: str
