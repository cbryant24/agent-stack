"""Ingest local ElevenLabs documentation into verified user_knowledge — no LLM.

Thin domain-injecting shim over the shared, domain-agnostic ingest mechanism in
agent-runtime (`agent_runtime.knowledge.docs_ingest`). The generic flow — parsing H2+
headings into candidates, the y/n/edit/defer confirmation, dedup, and the
`bulk_load_verified` call — lives in the runtime. This module fixes the domain to
`elevenlabs_mechanics` and preserves the CLI's import surface (`ingest_docs`,
`ingest_docs_sync`, `parse_docs`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent_runtime.knowledge.docs_ingest import (
    DocCandidate,
    ingest_docs as _ingest_docs,
    parse_docs,
)
from agent_runtime.knowledge.user_knowledge import UserKnowledgeStore

from voiceover_direction.constants import ELEVENLABS_MECHANICS_DOMAIN

__all__ = ["DocCandidate", "parse_docs", "ingest_docs", "ingest_docs_sync"]


async def ingest_docs(
    folder: str | Path,
    *,
    dry_run: bool = False,
    auto_confirm: bool = False,
    uks: UserKnowledgeStore | None = None,
) -> None:
    """Parse local ElevenLabs docs and load verified entries under `elevenlabs_mechanics`."""
    return await _ingest_docs(
        folder,
        domain=ELEVENLABS_MECHANICS_DOMAIN,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        uks=uks,
    )


def ingest_docs_sync(folder: str | Path, **kwargs: Any) -> None:
    """Synchronous wrapper for ingest_docs()."""
    asyncio.run(ingest_docs(folder, **kwargs))
