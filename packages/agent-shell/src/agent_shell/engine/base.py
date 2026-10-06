from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agent_shell.tools.registry import ToolResult, ToolSpec


class TextDelta(BaseModel):
    text: str


class ToolCallStarted(BaseModel):
    call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallFinished(BaseModel):
    call_id: str
    name: str
    result: ToolResult


class TurnCost(BaseModel):
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str = ""


class TurnEnd(BaseModel):
    reason: Literal["complete", "interrupted", "budget_exhausted", "error"] = "complete"
    detail: str = ""


EngineEvent = TextDelta | ToolCallStarted | ToolCallFinished | TurnCost | TurnEnd


class SessionRef(BaseModel):
    """What an engine gets to resume: the neutral transcript plus its own native handle."""

    session_id: str
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    native_handle: str | None = None


class SessionHandle(BaseModel):
    session_id: str
    native_handle: str | None = None


class Engine(Protocol):
    provider: Literal["claude", "openai", "fake"]
    model: str

    async def start(
        self, system_prompt: str, tools: list[ToolSpec], session: SessionRef | None
    ) -> SessionHandle: ...

    def send(
        self, handle: SessionHandle, user_text: str, history: list[dict[str, Any]]
    ) -> AsyncIterator[EngineEvent]:
        """Run one turn. `history` is the neutral transcript before `user_text`.

        Engines that keep native history may ignore it.
        """
        ...

    async def interrupt(self, handle: SessionHandle) -> None: ...

    async def close(self, handle: SessionHandle) -> None: ...
