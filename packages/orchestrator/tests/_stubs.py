"""Shared test stubs: a fake chat model + a trivial tool."""
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.tools import tool


class StubModel:
    """A minimal stand-in for ChatAnthropic. Returns queued AIMessages in order;
    bind_tools is a no-op that records the tools and returns self."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.bound_tools: list | None = None

    def bind_tools(self, tools: list) -> "StubModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, *args, **kwargs) -> AIMessage:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def make_tool_call_message(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def make_echo_tool() -> tuple:
    """Return (tool, ran). ran['called'] flips True iff the tool executed; ran['count']
    is the number of executions; ran['args'] is the most recent argument."""
    ran = {"called": False, "count": 0, "args": None}

    @tool
    def echo(x: str) -> str:
        """Echo the input back."""
        ran["called"] = True
        ran["count"] += 1
        ran["args"] = x
        return f"echo:{x}"

    return echo, ran
