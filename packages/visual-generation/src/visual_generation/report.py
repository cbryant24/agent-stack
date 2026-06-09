"""report — record the director's reaction to a pending generation.

Thin wrapper over the store's `update_generation_reaction`: captures a
closed-vocabulary reaction (no re-embed; flips status pending → complete) plus an
optional rating/notes/context onto the payload. The aesthetic/technical split is
the load-bearing one: `disliked` (rendered faithfully, not to taste — weighs
against the settings) vs. `render_failed` (the intent didn't render — the
direction stays open).
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_runtime import MemoryStore, get_memory_store

from visual_generation.models import VisualGeneration
from visual_generation.store import VisualGenerationStore


async def report(
    gen_id: str,
    reaction: str,
    *,
    rating: int | None = None,
    notes: str | None = None,
    context: str | None = None,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> VisualGeneration | None:
    """Record a reaction. Returns the (pre-update) generation, or None if not found."""
    store = store or VisualGenerationStore(memory_store or get_memory_store())
    await store.ensure_collection()
    gen = await store.get_generation(gen_id)
    if gen is None:
        return None
    await store.update_generation_reaction(
        gen_id, reaction, rating=rating, notes=notes, context=context
    )
    return gen


def report_sync(gen_id: str, reaction: str, **kwargs: Any) -> VisualGeneration | None:
    return asyncio.run(report(gen_id, reaction, **kwargs))
