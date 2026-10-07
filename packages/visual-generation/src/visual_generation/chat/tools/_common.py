from __future__ import annotations

from typing import Any

from agent_shell.tools.registry import ToolResult

from visual_generation.chat.labels import LabelResolver
from visual_generation.chat.resolve import resolve_ref, resolver_for  # noqa: F401  (re-exported)
from visual_generation.chat.state import ChatState

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


def label_footer(resolver: LabelResolver, ids: list[str]) -> str:
    named = [resolver.display(i) for i in ids if resolver.name_of(i)]
    return ("\nIn this project: " + ", ".join(named)) if named else ""
