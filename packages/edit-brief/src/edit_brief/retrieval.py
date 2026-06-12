"""Retrieval composition — the only knowledge edit-brief grounds steps in.

`editing_toolset` is ALWAYS loaded so every Resolve instruction is groundable in
the documented free-version constraints (the upgrade-flag convention carries
through verbatim). Technique findings + tutorial material supply the technique
recommendations. Nothing is gathered: an empty findings leg becomes a named gap
notation ("no findings on X — run technique-research"), never invented guidance.

Read-only v1 — no delegation. Mirrors technique-research/retrieval.py and the
voiceover-direction user-knowledge score boost.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from agent_runtime import MemoryStore, UserKnowledgeStore

from edit_brief.constants import (
    EDITING_TOOLSET_DOMAIN,
    FINDINGS_LIMIT,
    TECHNIQUE_OUTPUTS_COLLECTION,
    TOOLSET_LIMIT,
    TUTORIAL_LIMIT,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_LIMIT,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    technique: str
    description: str
    why_it_matters: str = ""
    application_notes: str = ""
    toolset_fit: str = ""
    upgrade_flag: str | None = None


@dataclass
class RetrievedContext:
    """Typed buckets composed for the synthesis prompt."""

    toolset: list[str] = field(default_factory=list)         # editing_toolset facts
    findings: list[Finding] = field(default_factory=list)    # technique_research_outputs
    tutorial: list[str] = field(default_factory=list)        # tutorial_research excerpts
    preferences: list[str] = field(default_factory=list)     # user_knowledge timing/editing prefs

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


async def read_editing_toolset(query: str, uks: UserKnowledgeStore) -> list[str]:
    """The director's Resolve-free toolset facts. The ONLY source of toolset
    claims — never hardcoded. Degrades to [] if the domain is empty/unavailable."""
    try:
        hits = await uks.search(query, domain=EDITING_TOOLSET_DOMAIN, limit=TOOLSET_LIMIT)
    except Exception:
        logger.debug("editing_toolset read skipped (collection may not exist yet)")
        return []
    return [h.statement for h in hits]


async def _read_findings(store: MemoryStore, query: str) -> list[Finding]:
    try:
        results = await store.search(
            TECHNIQUE_OUTPUTS_COLLECTION, query, limit=FINDINGS_LIMIT
        )
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
                why_it_matters=m.get("why_it_matters", ""),
                application_notes=m.get("application_notes", ""),
                toolset_fit=m.get("toolset_fit", "") or "",
                upgrade_flag=m.get("upgrade_flag") or None,
            )
        )
    return findings


async def _read_tutorial(store: MemoryStore, query: str) -> list[str]:
    try:
        results = await store.search(
            TUTORIAL_RESEARCH_COLLECTION, query, limit=TUTORIAL_LIMIT
        )
    except Exception:
        return []
    out: list[str] = []
    for r in results:
        title = r.point.source_title or r.point.source_id or "tutorial"
        out.append(f"{title}: {r.point.text[:300]}")
    return out


async def _read_preferences(uks: UserKnowledgeStore, query: str) -> list[str]:
    """Stated timing/editing preferences ground every brief — boosted per the
    1.25× first-party convention (used here only for the [PREFERENCE] ordering)."""
    try:
        hits = await uks.search(query, limit=USER_KNOWLEDGE_LIMIT)
    except Exception:
        return []
    boosted = sorted(
        hits, key=lambda h: h.score * USER_KNOWLEDGE_SCORE_MULTIPLIER, reverse=True
    )
    # editing_toolset is surfaced separately; keep prefs to other domains.
    return [h.statement for h in boosted if h.domain != EDITING_TOOLSET_DOMAIN]


async def retrieve_context(
    query: str, store: MemoryStore, uks: UserKnowledgeStore
) -> RetrievedContext:
    """Compose the four knowledge legs in parallel; each degrades to empty."""
    toolset, findings, tutorial, preferences = await asyncio.gather(
        read_editing_toolset(query, uks),
        _read_findings(store, query),
        _read_tutorial(store, query),
        _read_preferences(uks, query),
    )
    return RetrievedContext(
        toolset=toolset, findings=findings, tutorial=tutorial, preferences=preferences
    )
