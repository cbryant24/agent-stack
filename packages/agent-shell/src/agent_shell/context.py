from __future__ import annotations

from typing import Any

TRUNCATED = "…[truncated]"


def _cap(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[: max(cap - len(TRUNCATED), 0)] + TRUNCATED


def trim_history(
    history: list[dict[str, Any]], *, last_n_turns: int = 20, tool_text_cap: int = 1500
) -> list[dict[str, Any]]:
    """The window of neutral history an engine sends to a model.

    A turn runs from one user message up to (not including) the next, so a window always
    starts on a user message and never separates a tool call from its result. Older turns are
    dropped (not summarised). Tool results are already just ``ToolResult.text``; each is capped
    at ``tool_text_cap`` characters. The system prompt is the engine's concern, not stored here.
    """
    starts = [i for i, m in enumerate(history) if m["role"] == "user"]
    if last_n_turns > 0 and len(starts) > last_n_turns:
        history = history[starts[-last_n_turns]:]
    out: list[dict[str, Any]] = []
    for m in history:
        if m["role"] == "tool":
            m = {**m, "content": _cap(str(m.get("content", "")), tool_text_cap)}
        out.append(m)
    return balance_tool_calls(out)


def balance_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make every tool call have exactly one result, and drop results with no call.

    The recorder already guarantees this for stored history; this is the belt-and-braces check
    before a provider (which rejects unbalanced history) sees it.
    """
    out: list[dict[str, Any]] = []
    for i, m in enumerate(messages):
        if m["role"] == "tool":
            called = {c["id"] for p in messages[:i] for c in p.get("tool_calls", [])}
            if m.get("tool_call_id") not in called:
                continue
        out.append(m)
        for call in m.get("tool_calls", []) if m["role"] == "assistant" else []:
            answered = any(
                x["role"] == "tool" and x.get("tool_call_id") == call["id"] for x in messages[i + 1:]
            )
            if not answered:
                out.append({
                    "role": "tool", "content": "Interrupted before completion.",
                    "tool_call_id": call["id"], "name": call["name"], "is_error": True,
                })
    return out
