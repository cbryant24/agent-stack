"""Label resolution against the active project (shared by the tools and the interpretation builder)."""

from __future__ import annotations

import re

from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.state import ChatState

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


async def resolver_for(state: ChatState, project: str | None = None) -> LabelResolver:
    slug = project or state.project
    if not slug:
        return LabelResolver([])
    store, _ = state.stores()
    await store.ensure_collection()
    return LabelResolver(await store.list_generations(project=slug))


async def resolve_ref(state: ChatState, ref: str) -> tuple[str | None, str]:
    """(generation id, reason-if-not). Labels and prefixes resolve inside the active project;
    a full id from any project is accepted if it exists. Never guesses."""
    resolver = await resolver_for(state)
    res = resolver.resolve(ref)
    if res.gen_id:
        return res.gen_id, ""
    if _UUID.match(ref.strip()):
        store, _ = state.stores()
        gen = await store.get_generation(ref.strip())
        if gen is not None:
            return gen.entry_id, ""
        return None, f"no generation with id {ref.strip()!r}"
    return None, res.reason
