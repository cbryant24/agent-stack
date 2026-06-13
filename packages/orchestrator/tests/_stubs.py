"""Shared test stubs: a fake chat model + a trivial tool."""
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.tools import tool


class StubModel:
    """A minimal stand-in for ChatAnthropic. Returns queued AIMessages in order.

    Binding-aware: bind_tools returns a NEW StubModel flagged tools-bound that shares
    the response queue, call counter, and invocation log with the original. A model
    that is NOT tools-bound cannot emit tool_use — so if a queued response carries
    tool_calls, the unbound instance strips them, mirroring real ChatAnthropic invoked
    with no tools (the orchestrator's budget-exhausted final-summary step)."""

    def __init__(self, responses: list[AIMessage], *, _shared=None, _tools_bound=False) -> None:
        self._shared = _shared if _shared is not None else {
            "responses": list(responses),
            "calls": 0,
            "invocations": [],
        }
        self._tools_bound = _tools_bound
        self.bound_tools: list | None = None

    @property
    def calls(self) -> int:
        return self._shared["calls"]

    @property
    def invocations(self) -> list:
        """Every message list the model has been invoked with, in order."""
        return self._shared["invocations"]

    @property
    def last_invocation(self) -> list | None:
        inv = self._shared["invocations"]
        return inv[-1] if inv else None

    def bind_tools(self, tools: list, **kwargs) -> "StubModel":
        bound = StubModel([], _shared=self._shared, _tools_bound=True)
        bound.bound_tools = tools
        return bound

    async def ainvoke(self, messages, *args, **kwargs) -> AIMessage:
        self._shared["invocations"].append(list(messages))
        responses = self._shared["responses"]
        resp = responses[min(self._shared["calls"], len(responses) - 1)]
        self._shared["calls"] += 1
        if not self._tools_bound and getattr(resp, "tool_calls", None):
            # No tools bound -> the model cannot call tools; drop the tool_use blocks.
            resp = AIMessage(content=resp.content or "(summary)")
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
