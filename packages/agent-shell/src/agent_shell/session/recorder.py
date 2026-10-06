from __future__ import annotations

from typing import Any

from agent_shell.engine.base import EngineEvent, TextDelta, ToolCallFinished, ToolCallStarted
from agent_shell.session.store import SessionStore

INTERRUPTED = "Interrupted before completion."


class TurnRecorder:
    """Folds one turn's engine events into the neutral transcript, in order.

    Shapes written: ``assistant`` (text, optional ``tool_calls``) and ``tool``
    (``tool_call_id``, ``name``, ``is_error``, content = ``ToolResult.text``). A tool call is
    stored the moment it starts, so an interrupt or crash leaves it visible; ``finish`` then
    closes any call without a result with a synthetic error result. That keeps every stored
    history valid for providers that reject an unanswered tool call.
    """

    def __init__(self, store: SessionStore, session_id: str) -> None:
        self._store, self._sid = store, session_id
        self._text: list[str] = []
        self._row: int | None = None          # assistant row currently collecting calls
        self._calls: list[dict[str, Any]] = []
        self._open: dict[str, str] = {}       # call_id -> tool name, awaiting a result
        self._answered_since = False

    def on_event(self, ev: EngineEvent) -> None:
        if isinstance(ev, TextDelta):
            self._text.append(ev.text)
        elif isinstance(ev, ToolCallStarted):
            call = {"id": ev.call_id, "name": ev.name, "args": ev.args}
            if self._row is not None and not self._answered_since:
                self._calls.append(call)
                self._store.update_meta(self._row, {"tool_calls": self._calls})
            else:
                self._calls = [call]
                self._row = self._store.add_message(
                    self._sid, "assistant", "".join(self._text).strip(), {"tool_calls": self._calls}
                )
                self._text = []
                self._answered_since = False
            self._open[ev.call_id] = ev.name
        elif isinstance(ev, ToolCallFinished):
            self._open.pop(ev.call_id, None)
            self._answered_since = True
            self._store.add_message(
                self._sid, "tool", ev.result.text,
                {"tool_call_id": ev.call_id, "name": ev.name, "is_error": ev.result.is_error},
            )

    def finish(self) -> None:
        for call_id, name in self._open.items():
            self._store.add_message(
                self._sid, "tool", INTERRUPTED,
                {"tool_call_id": call_id, "name": name, "is_error": True},
            )
        self._open.clear()
        text = "".join(self._text).strip()
        if text:
            self._store.add_message(self._sid, "assistant", text)
        self._text = []
