"""Retrieval composition — the knowledge F&I grounds its diagnosis/steps in.

`editing_toolset` is ALWAYS loaded so every recommended action is checked against
DaVinci Resolve free (upgrade flags carried verbatim). Technique findings +
tutorial material supply technique guidance; user_knowledge supplies the
director's stated preferences, boosted 1.25× per the established convention. The
query is FEEDBACK/diagnosis-driven (the perceptual reaction drives retrieval, not
the section text). Read-only v1 — a gap becomes a named notation, never a
delegation. Mirrors edit_brief/retrieval.py.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from agent_runtime import MemoryStore, UserKnowledgeStore

from feedback_iteration.constants import (
    EDITING_TOOLSET_DOMAIN,
    FINDINGS_LIMIT,
    TECHNIQUE_OUTPUTS_COLLECTION,
    TOOLSET_LIMIT,
    TUTORIAL_LIMIT,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_LIMIT,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from feedback_iteration.models import FeedbackItem, ParsedBrief

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    technique: str
    description: str
    application_notes: str = ""
    toolset_fit: str = ""
    upgrade_flag: str | None = None


@dataclass
class RetrievedContext:
    toolset: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    tutorial: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


def build_retrieval_query(items: list[FeedbackItem], parsed: ParsedBrief) -> str:
    """Compose a compact query from the feedback (the perceptual reactions drive
    retrieval) plus the brief's section headings for territory."""
    parts = [i.text for i in items]
    parts += [s.heading_text for s in parsed.sections]
    return " · ".join(p for p in parts if p) or "video edit feedback"


async def _read_toolset(query: str, uks: UserKnowledgeStore) -> list[str]:
    try:
        hits = await uks.search(query, domain=EDITING_TOOLSET_DOMAIN, limit=TOOLSET_LIMIT)
    except Exception:
        logger.debug("editing_toolset read skipped (collection may not exist yet)")
        return []
    return [h.statement for h in hits]


async def _read_findings(store: MemoryStore, query: str) -> list[Finding]:
    try:
        results = await store.search(TECHNIQUE_OUTPUTS_COLLECTION, query, limit=FINDINGS_LIMIT)
    except Exception:
        return []
    findings: list[Finding] = []
    for r in results:
        m = r.point.metadata or {}
        technique = m.get("technique")
        if not technique:
            continue
        findings.append(
            Finding(
                technique=technique,
                description=m.get("description", ""),
                application_notes=m.get("application_notes", ""),
                toolset_fit=m.get("toolset_fit", "") or "",
                upgrade_flag=m.get("upgrade_flag") or None,
            )
        )
    return findings


async def _read_tutorial(store: MemoryStore, query: str) -> list[str]:
    try:
        results = await store.search(TUTORIAL_RESEARCH_COLLECTION, query, limit=TUTORIAL_LIMIT)
    except Exception:
        return []
    out: list[str] = []
    for r in results:
        title = r.point.source_title or r.point.source_id or "tutorial"
        out.append(f"{title}: {r.point.text[:300]}")
    return out


async def _read_preferences(uks: UserKnowledgeStore, query: str) -> list[str]:
    """Stated editing preferences ground the diagnosis — boosted per the 1.25×
    first-party convention. Toolset facts are surfaced separately."""
    try:
        hits = await uks.search(query, limit=USER_KNOWLEDGE_LIMIT)
    except Exception:
        return []
    boosted = sorted(hits, key=lambda h: h.score * USER_KNOWLEDGE_SCORE_MULTIPLIER, reverse=True)
    return [h.statement for h in boosted if h.domain != EDITING_TOOLSET_DOMAIN]


async def retrieve_context(query: str, store: MemoryStore, uks: UserKnowledgeStore) -> RetrievedContext:
    """Compose the four knowledge legs in parallel; each degrades to empty."""
    toolset, findings, tutorial, preferences = await asyncio.gather(
        _read_toolset(query, uks),
        _read_findings(store, query),
        _read_tutorial(store, query),
        _read_preferences(uks, query),
    )
    return RetrievedContext(toolset=toolset, findings=findings, tutorial=tutorial, preferences=preferences)
