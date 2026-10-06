from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_shell.engine.base import (
    EngineEvent,
    SessionHandle,
    SessionRef,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCost,
    TurnEnd,
)
from agent_shell.tools.registry import ToolResult, ToolSpec


class Say(BaseModel):
    text: str
    cost_usd: float = 0.0


class Call(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


Step = Say | Call


class FakeEngine:
    """Scripted engine: each user message consumes the next turn (a list of steps).

    Tool calls are made through the bound handlers the session hands to `start`, so the
    gate, dry-run and audit apply exactly as with a real engine. When the script runs out,
    the engine echoes the user's text.
    """

    provider: Literal["claude", "openai", "fake"] = "fake"

    def __init__(
        self, script: list[list[Step]] | None = None, *, model: str = "fake-1", delay: float = 0.0
    ) -> None:
        self.script = script or []
        self.model = model
        self.delay = delay
        self.turn = 0
        self.started_with: SessionRef | None = None
        self.system_prompt = ""
        self._tools: dict[str, ToolSpec] = {}
        self._interrupted = asyncio.Event()
        self.closed = False

    async def start(
        self, system_prompt: str, tools: list[ToolSpec], session: SessionRef | None
    ) -> SessionHandle:
        self.system_prompt = system_prompt
        self._tools = {t.name: t for t in tools}
        self.started_with = session
        self.turn = sum(1 for m in (session.transcript if session else []) if m["role"] == "user")
        sid = session.session_id if session else "fake"
        return SessionHandle(session_id=sid, native_handle=f"fake-{self.turn}")

    async def send(self, handle: SessionHandle, user_text: str) -> AsyncIterator[EngineEvent]:
        self._interrupted.clear()
        steps = self.script[self.turn] if self.turn < len(self.script) else [Say(text=f"echo: {user_text}")]
        self.turn += 1
        handle.native_handle = f"fake-{self.turn}"
        n = 0
        for step in steps:
            if self._interrupted.is_set():
                yield TurnEnd(reason="interrupted")
                return
            if isinstance(step, Say):
                for word in step.text.split(" "):
                    yield TextDelta(text=word + " ")
                    await asyncio.sleep(self.delay)
                if step.cost_usd:
                    yield TurnCost(cost_usd=step.cost_usd, model=self.model)
            else:
                n += 1
                call_id = f"call-{self.turn}-{n}"
                yield ToolCallStarted(call_id=call_id, name=step.name, args=step.args)
                spec = self._tools.get(step.name)
                if spec is None:
                    result = ToolResult(text=f"unknown tool: {step.name}", is_error=True)
                else:
                    result = await spec.handler(step.args)
                yield ToolCallFinished(call_id=call_id, name=step.name, result=result)
        yield TurnEnd(reason="complete")

    async def interrupt(self, handle: SessionHandle) -> None:
        self._interrupted.set()

    async def close(self, handle: SessionHandle) -> None:
        self.closed = True
