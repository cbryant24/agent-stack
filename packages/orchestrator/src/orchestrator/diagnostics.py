"""Vector-DB diagnostics for the orchestrator — diagnose-only.

The orchestrator can audit the shared Qdrant layer but never writes to it: it is a
reader, not an owner. Diagnosis combines three things it already has — read-only
Qdrant inspection (via ``MemoryStore``'s inspection surface), live code access (the
existing ``read_file`` / ``grep`` tools, driven by the model), and a **behavioral
probe** that embeds a query which *should* hit and checks whether the expected point
returns above threshold. The probe is the only way to catch a cross-model
embedding-space mismatch: ``voyage-3-large`` and ``voyage-multimodal-3`` vectors are
both 1024-dim and structurally valid but semantically incompatible, so the data is
present yet never retrieves.

On finding an issue the orchestrator does two things and stops: it writes a
**diagnostic report** to ``<agent_reports_vault>/diagnostics/`` (status moves
``open → delegated → fixed``), and — by design — it *delegates* the fix to the owning
agent, which performs the actual write under its own ownership. That delegation
**seam** is defined here (a ``RemediationHandler`` protocol + registry +
``delegate_remediation``), but **no agent registers a handler in this slice**: with an
empty registry every report stays ``open`` and serves as a human/Claude-Code work
order. Per-agent remediation entry points are deferred (see
``docs/v2-refinements-orchestrator.md``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, Field

from agent_runtime import MemoryStore, get_memory_store
from agent_runtime.config import get_config

logger = logging.getLogger(__name__)

# Probe embedding spaces — mirrors agent_runtime.memory.embeddings (single source of
# truth there; restated here only for report evidence labelling).
TEXT_MODEL = "voyage-3-large"
MULTIMODAL_MODEL = "voyage-multimodal-3"

# Below this score a probe hit is treated as "did not retrieve" for the expected point.
DEFAULT_PROBE_THRESHOLD = 0.5

Status = Literal["open", "delegated", "fixed"]


# ── Diagnostic report ───────────────────────────────────────────────────────────


class DiagnosticReport(BaseModel):
    """A diagnose-only finding about one collection. Written to the reports vault as
    markdown with YAML frontmatter; `status` moves open → delegated → fixed."""

    collection: str
    owning_agent: str
    symptom: str
    diagnosis: str
    # filter/threshold/model read from code + actual payloads/scores from Qdrant.
    evidence: dict[str, Any] = Field(default_factory=dict)
    proposed_fix: str
    status: Status = "open"
    created_at: str = ""
    run_id: str = ""

    def stamp(self) -> DiagnosticReport:
        """Fill created_at if unset (kept separate so callers can inject a fixed
        timestamp in tests). Returns self for chaining."""
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        return self


def render_report_markdown(report: DiagnosticReport) -> str:
    """YAML frontmatter + a readable body, matching the repo's report convention."""
    front = {
        "type": "vector-db-diagnostic",
        "collection": report.collection,
        "owning_agent": report.owning_agent,
        "status": report.status,
        "created_at": report.created_at,
        "run_id": report.run_id,
    }
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False).strip()
    evidence = yaml.safe_dump(report.evidence, sort_keys=False, default_flow_style=False).strip()
    return (
        f"---\n{fm}\n---\n\n"
        f"# Diagnostic: `{report.collection}`\n\n"
        f"**Owning agent:** {report.owning_agent}  \n"
        f"**Status:** {report.status}\n\n"
        f"## Symptom\n\n{report.symptom}\n\n"
        f"## Root-cause diagnosis\n\n{report.diagnosis}\n\n"
        f"## Supporting evidence\n\n```yaml\n{evidence}\n```\n\n"
        f"## Proposed fix\n\n{report.proposed_fix}\n"
    )


def _report_filename(report: DiagnosticReport) -> str:
    date = (report.created_at or datetime.now(UTC).isoformat())[:10]
    return f"{date} {report.collection}.md"


def diagnostics_dir(vault: Path | None = None) -> Path:
    """The diagnostics subdir of the reports vault (config doesn't pre-create it)."""
    base = vault if vault is not None else get_config().agent_reports_vault
    return Path(base) / "diagnostics"


def write_diagnostic_report(report: DiagnosticReport, *, vault: Path | None = None) -> Path:
    """Write (or overwrite) the report markdown under <vault>/diagnostics/.

    Filename is stable per (date, collection) so a status transition rewrites the
    same file rather than spawning a duplicate."""
    report.stamp()
    out_dir = diagnostics_dir(vault)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _report_filename(report)
    out_path.write_text(render_report_markdown(report), encoding="utf-8")
    return out_path


# ── Behavioral probe ────────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    """Outcome of a behavioral probe against one collection."""

    collection: str
    model: str
    threshold: float
    hits: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)
    expected_point_id: str | None = None
    expected_returned_above_threshold: bool | None = None
    expected_present_in_collection: bool | None = None
    cross_model_suspected: bool = False

    @property
    def top_score(self) -> float:
        return self.hits[0][1] if self.hits else 0.0


async def behavioral_probe(
    collection: str,
    query: str,
    *,
    expected_point_id: str | None = None,
    multimodal: bool = False,
    threshold: float = DEFAULT_PROBE_THRESHOLD,
    limit: int = 10,
    store: MemoryStore | None = None,
) -> ProbeResult:
    """Embed a query that SHOULD hit and check whether the expected point returns
    above threshold. A cross-model mismatch is the prime target: when the expected
    point exists in the collection (confirmed via retrieve) but the probe — embedded
    with `model` — fails to surface it above threshold, the stored vectors were almost
    certainly written in a different embedding space (`cross_model_suspected`)."""
    from agent_runtime.memory.embeddings import MultimodalInput

    ms = store or get_memory_store()
    model = MULTIMODAL_MODEL if multimodal else TEXT_MODEL
    embedder = ms.embedding_client
    if multimodal:
        [vector] = await embedder.embed_multimodal(
            [MultimodalInput(text=query)], input_type="query"
        )
    else:
        [vector] = await embedder.embed([query], input_type="query")

    hits = await ms.query_by_vector(collection, vector, limit=limit)
    result = ProbeResult(
        collection=collection, model=model, threshold=threshold, hits=hits,
        expected_point_id=expected_point_id,
    )

    if expected_point_id is not None:
        above = any(
            pid == expected_point_id and score >= threshold for pid, score, _ in hits
        )
        result.expected_returned_above_threshold = above
        # Is the expected point actually in the collection at all?
        present = False
        try:
            records = await ms.retrieve_points(collection, [expected_point_id])
            present = len(records) > 0
        except Exception:
            logger.debug("retrieve_points failed during probe; treating as unknown")
            present = False
        result.expected_present_in_collection = present
        # Present but not retrievable above threshold → likely embedding-space mismatch.
        result.cross_model_suspected = present and not above

    return result


# ── Remediation delegation seam (empty registry in this slice) ────────────────────


@dataclass
class RemediationOutcome:
    """Returned by a RemediationHandler. `status` is the new report status the handler
    achieved (typically "fixed"); `detail` is a human-readable note for the report."""

    status: Status
    detail: str


@runtime_checkable
class RemediationHandler(Protocol):
    """An owning agent's remediation entry point. The agent performs the actual write
    (re-embed / re-tag payload / move points) under its own ownership — the
    orchestrator never writes to Qdrant. No agent implements this in the current
    slice; per-agent handlers are deferred to docs/v2-refinements-orchestrator.md."""

    async def remediate(self, report: DiagnosticReport) -> RemediationOutcome: ...


_REMEDIATION_HANDLERS: dict[str, RemediationHandler] = {}


def register_remediation_handler(owning_agent: str, handler: RemediationHandler) -> None:
    """Register an owning agent's remediation handler (used by the delegation seam)."""
    _REMEDIATION_HANDLERS[owning_agent] = handler


def get_remediation_handler(owning_agent: str) -> RemediationHandler | None:
    return _REMEDIATION_HANDLERS.get(owning_agent)


async def delegate_remediation(
    report: DiagnosticReport, *, vault: Path | None = None
) -> DiagnosticReport:
    """Hand a diagnosed report to the owning agent's remediation handler, if one is
    registered. Transitions open → delegated, invokes the handler (which performs the
    write and reports back its achieved status, typically "fixed"), and rewrites the
    report file at each transition. With no handler registered — the current reality —
    the report is left untouched as a manual work order."""
    handler = get_remediation_handler(report.owning_agent)
    if handler is None:
        logger.info(
            "No remediation handler for %s; report stays a manual work order",
            report.owning_agent,
        )
        return report

    report.status = "delegated"
    write_diagnostic_report(report, vault=vault)
    outcome = await handler.remediate(report)
    report.status = outcome.status
    report.evidence = {**report.evidence, "remediation": outcome.detail}
    write_diagnostic_report(report, vault=vault)
    return report
