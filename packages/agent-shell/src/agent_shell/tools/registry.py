from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EffectClass(str, Enum):
    NONE = "none"                        # pure
    READ = "read"                        # local reads, Qdrant queries
    EXTERNAL_READ = "external_read"      # network read, no spend
    LLM_SPEND = "llm_spend"              # paid LLM call inside the tool
    GPU_SPEND = "gpu_spend"              # pod time, ElevenLabs characters
    MEMORY_WRITE = "memory_write"        # Qdrant or knowledge-base write
    DESTRUCTIVE_LOCAL = "destructive_local"


class ToolResult(BaseModel):
    text: str                                   # short summary for the model
    data: dict[str, Any] = Field(default_factory=dict)   # structured payload (ids, counts)
    artifacts: list[str] = Field(default_factory=list)
    is_error: bool = False


class ToolSpec(BaseModel):
    """A tool. `handler` receives the validated `input_model` instance.

    `estimate_cost` (optional) returns the expected USD cost for the gate; real cost is read
    from `ToolResult.data["cost_usd"]` after the call.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    effect: EffectClass
    handler: Callable[..., Awaitable[ToolResult]]
    # Text shown in the confirm panel. May be async, so it can read what the call will touch.
    preview: Callable[..., str | Awaitable[str]] | None = None
    estimate_cost: Callable[..., float] | None = None
    # Optional async check run BEFORE the gate: return a message and the call is refused with it
    # (an error result, no prompt), so the user is never asked to approve a call that would fail.
    precheck: Callable[..., Awaitable[str | None]] | None = None


class Registry:
    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for t in tools or []:
            self.register(t)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool: {name}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schema(self, name: str) -> dict[str, Any]:
        return self.get(name).input_model.model_json_schema()

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
