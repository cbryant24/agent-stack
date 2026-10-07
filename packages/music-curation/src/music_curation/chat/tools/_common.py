from __future__ import annotations

from typing import Any

from agent_shell.tools.registry import ToolResult

from music_curation.chat.state import ChatState

CLIP = 3500
MIN_PREFIX = 8


def clip(text: str, limit: int = CLIP) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 60].rstrip() + "\n…(truncated; ask for a narrower view)"


def ok(text: str, *, data: dict[str, Any] | None = None, artifacts: list[str] | None = None) -> ToolResult:
    return ToolResult(text=clip(text), data=data or {}, artifacts=artifacts or [])


def fail(text: str, *, data: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(text=clip(text), data=data or {}, is_error=True)


def title_of(state: ChatState, gen_id: str) -> str:
    title = state.seen.get(gen_id)
    return f"{title} ({gen_id[:8]})" if title else gen_id[:8]


async def resolve_ref(state: ChatState, ref: str) -> tuple[str | None, str]:
    """(generation id, why-not). Accepts a full id, a unique 8+ character prefix among the pending
    generations and those already shown this session, or `latest` (the newest pending one).
    Never guesses."""
    raw = (ref or "").strip()
    if not raw:
        return None, "empty generation reference"
    store, _, _ = state.stores()
    await store.ensure_collection()
    pending = await store.list_pending()
    state.remember(pending)
    if raw.lower() in ("latest", "last"):
        if not pending:
            return None, "there are no pending generations, so 'latest' means nothing"
        return max(pending, key=lambda g: g.created_at).entry_id, ""
    gen = await store.get_generation(raw)
    if gen is not None:
        state.remember([gen])
        return gen.entry_id, ""
    if len(raw) >= MIN_PREFIX:
        hits = [gid for gid in state.seen if gid.lower().startswith(raw.lower())]
        if len(hits) == 1:
            return hits[0], ""
        if len(hits) > 1:
            return None, f"{raw!r} matches {len(hits)} generations; use more characters"
    return None, f"{raw!r} is not a generation id, a known id prefix (8+ characters), or 'latest'"
