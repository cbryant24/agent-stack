from __future__ import annotations

import re
from typing import Any

from agent_shell.tools.registry import ToolResult

from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.state import ChatState

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CLIP = 3500


def ok(text: str, *, data: dict[str, Any] | None = None, artifacts: list[str] | None = None) -> ToolResult:
    return ToolResult(text=clip(text), data=data or {}, artifacts=artifacts or [])


def fail(text: str, *, data: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(text=clip(text), data=data or {}, is_error=True)


def clip(text: str, limit: int = CLIP) -> str:
    """Keep tool results small; the full record is one inspect_generation / chain_show away."""
    if len(text) <= limit:
        return text
    return text[: limit - 60].rstrip() + "\n…(truncated; ask for a narrower view or a single record)"


def project_note(state: ChatState) -> str:
    """Active project, baked into tool descriptions: byte-stable for the whole session."""
    if state.project:
        return f"Defaults to the active project '{state.project}'."
    return "There is no active project: pass `project`."


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


def label_footer(resolver: LabelResolver, ids: list[str]) -> str:
    named = [resolver.display(i) for i in ids if resolver.name_of(i)]
    return ("\nIn this project: " + ", ".join(named)) if named else ""
