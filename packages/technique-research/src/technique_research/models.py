"""Data models for technique-research.

The stored unit is the per-technique *finding* (a relevance decision), not the
report. The report is the per-project assembly of findings; findings are what
accumulate in `technique_research_outputs` and what `check` retrieves on the next
run. Findings are text-embedded (`voyage-3-large`) — images inform identification
but never the memory (the handoff's resolved embedding-space decision).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_runtime import MemoryPoint

from technique_research.constants import AGENT_NAME

Scope = Literal["editing", "generation", "both"]

# Human labels for non-delegated gap statuses in the report.
_GAP_LABELS = {
    "local": "answered from existing knowledge",
    "would delegate": "**gap** — would delegate (preview)",
    "declined": "gap, delegation declined — curated from existing knowledge",
}


def _slug(text: str, n: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:n].strip("-") or "untitled"


# ── Inputs ───────────────────────────────────────────────────────────────────


class IdentificationInput(BaseModel):
    """The identification chain's input shape: text + zero-or-more images +
    optional context. This is the one V1 provision for Mode B — later it becomes
    *more frames* into the same `images` list plus an extraction front-end, an
    extension rather than a redesign.
    """

    goal: str
    images: list[Path] = Field(default_factory=list)
    url: str | None = None
    ref_report: Path | None = None
    scope: Scope | None = None  # None → inferred from the goal
    domain: str | None = None   # video type (AMV, game review, …); inferable

    model_config = {"arbitrary_types_allowed": True}


# ── Identification outputs ────────────────────────────────────────────────────


class TechniqueDomain(BaseModel):
    """A prioritized technique domain emitted by identification. `search_query`
    is reused verbatim for both the check and any delegation to tutorial-research.
    """

    name: str
    why_it_matters: str
    priority: int = 1
    scope: Scope = "editing"
    search_query: str


class GroundedReference(BaseModel):
    summary: str = ""
    exemplars: list[str] = Field(default_factory=list)
    url_metadata: dict[str, Any] | None = None


class CheckOutcome(BaseModel):
    """Per-domain result of the three-collection check."""

    domain_name: str
    decision: Literal["local", "delegate"]
    technique_outputs_score: float = 0.0
    tutorial_score: float = 0.0
    user_knowledge_score: float = 0.0


# ── The stored unit ───────────────────────────────────────────────────────────


class TechniqueFinding(BaseModel):
    """A curated relevance decision about one technique — the unit that
    accumulates in `technique_research_outputs` and is retrieved by `check`."""

    technique: str
    description: str
    why_it_matters: str = ""
    application_notes: str = ""
    toolset_fit: str = ""
    # Surfaced only when a technique is materially faster or only possible in a
    # paid/Studio tool; None otherwise. Never a sales pitch.
    upgrade_flag: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    goal_context: str = ""
    domain_context: str = ""
    scope: Scope = "editing"

    def embed_text(self) -> str:
        return f"{self.technique}: {self.description}"

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TechniqueFinding:
        known = set(cls.model_fields)
        return cls(**{k: v for k, v in payload.items() if k in known})

    def to_memory_point(self, run_id: str) -> MemoryPoint:
        return MemoryPoint(
            text=self.embed_text(),
            source_id=f"technique:{_slug(self.technique)}",
            source_type="agent_summary",
            source_title=self.technique,
            processed_by_agent=AGENT_NAME,
            processed_in_run=run_id,
            domain_tags=[self.domain_context] if self.domain_context else [],
            topic_tags=[self.scope],
            metadata=self.to_payload(),
        )


# ── The report (per-project assembly) ─────────────────────────────────────────


class GapOutcome(BaseModel):
    domain_name: str
    delegated: bool
    status: str = ""  # tutorial-research run status, when delegated
    run_id: str = ""
    items_processed: int = 0


class TechniqueReport(BaseModel):
    goal: str
    scope: Scope = "editing"
    grounded_reference_summary: str = ""
    techniques: list[TechniqueFinding] = Field(default_factory=list)
    gaps: list[GapOutcome] = Field(default_factory=list)
    preview: bool = False  # True for --plan-only (no delegation / no writes)

    def to_markdown(self) -> str:
        now = datetime.now(UTC).strftime("%Y-%m-%d")
        lines: list[str] = [
            "---",
            "title: Technique Report",
            f"goal: {self.goal!r}",
            f"scope: {self.scope}",
            f"date: {now}",
            f"agent: {AGENT_NAME}",
            "---",
            "",
            f"# Technique Report — {self.goal}",
            "",
        ]
        if self.preview:
            lines += [
                "> **Preview (`--plan-only`)** — no delegation was run and nothing "
                "was written. This is what is already known plus the identified gaps.",
                "",
            ]
        if self.grounded_reference_summary:
            lines += ["## Reference", "", self.grounded_reference_summary, ""]

        lines += ["## Techniques", ""]
        if not self.techniques:
            lines += ["_No techniques curated._", ""]
        for i, t in enumerate(self.techniques, start=1):
            lines.append(f"### {i}. {t.technique}")
            lines.append("")
            if t.description:
                lines.append(t.description)
                lines.append("")
            if t.why_it_matters:
                lines.append(f"**Why it matters here:** {t.why_it_matters}")
                lines.append("")
            if t.application_notes:
                lines.append(f"**How to apply:** {t.application_notes}")
                lines.append("")
            if t.toolset_fit:
                lines.append(f"**With your toolset:** {t.toolset_fit}")
                lines.append("")
            if t.upgrade_flag:
                lines.append(f"**⬆ Paid/Studio:** {t.upgrade_flag}")
                lines.append("")
            if t.source_refs:
                refs = ", ".join(t.source_refs)
                lines.append(f"**Where to learn more:** {refs}")
                lines.append("")

        if self.gaps:
            lines += ["## Gaps & Delegations", ""]
            for g in self.gaps:
                if g.delegated:
                    lines.append(
                        f"- **{g.domain_name}** — delegated to tutorial-research "
                        f"({g.status}, {g.items_processed} item(s), run `{g.run_id}`)"
                    )
                else:
                    lines.append(f"- **{g.domain_name}** — {_GAP_LABELS.get(g.status, g.status or 'no delegation')}")
            lines.append("")

        consumer = (
            "## For the brief" if self.scope == "editing"
            else "## For generation" if self.scope == "generation"
            else "## For the brief / generation"
        )
        lines += [consumer, ""]
        for t in self.techniques:
            lines.append(f"- **{t.technique}** — {t.why_it_matters or t.description}")
        lines.append("")
        return "\n".join(lines)

    def default_filename(self) -> str:
        return f"{datetime.now(UTC).strftime('%Y-%m-%d')}-{_slug(self.goal)}.md"


# ── The library return type ───────────────────────────────────────────────────


class TechniqueResult(BaseModel):
    report: TechniqueReport
    report_path: Path | None = None       # the TechniqueReport markdown (-o)
    report_run_path: Path | None = None   # the standard run report in the vault
    finding_ids: list[str] = Field(default_factory=list)
    domains: list[TechniqueDomain] = Field(default_factory=list)
    check_outcomes: list[CheckOutcome] = Field(default_factory=list)
    run_id: str = ""
    status: str = "completed"
    cost_usd: float = 0.0
    items_processed: int = 0
    wall_time_sec: float = 0.0

    model_config = {"arbitrary_types_allowed": True}
