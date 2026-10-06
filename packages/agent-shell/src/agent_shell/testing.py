"""Small helpers for testing tools and sessions (used by this package's tests)."""

from __future__ import annotations

from pydantic import BaseModel

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec


class Args(BaseModel):
    text: str = "x"


class Counter:
    """Records handler calls so tests can prove a tool did or did not run."""

    def __init__(self) -> None:
        self.calls: list[str] = []


def make_tool(
    name: str, effect: EffectClass, counter: Counter, *, cost: float = 0.0, boom: bool = False,
    est: float = 0.0,
) -> ToolSpec:
    async def handler(a: Args) -> ToolResult:
        counter.calls.append(a.text)
        if boom:
            raise RuntimeError("kaput")
        return ToolResult(text=f"{name} ran {a.text}", data={"cost_usd": cost})

    return ToolSpec(
        name=name, description=name, input_model=Args, effect=effect, handler=handler,
        preview=lambda a: f"preview {a.text}", estimate_cost=lambda a: est,
    )
