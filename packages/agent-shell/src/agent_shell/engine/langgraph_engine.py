"""The one real engine: a small LangGraph model/tools loop behind the `Engine` protocol.

The only module in agent_shell allowed to import langchain/langgraph (an import-linter
contract enforces it). Shape follows the old orchestrator graph (one model node, one tools
node, a conditional edge) with three differences: it streams through `astream_events`, it has
no checkpointer (history is rebuilt each turn from the neutral transcript, so switching
provider or model reuses it unchanged), and every tool call goes through the agent_shell
executor via the bound handlers it is given. LangGraph interrupts are not used: the executor
is the only gate.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from pydantic import SecretStr
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent_runtime.budget import estimate_cost
from agent_shell.context import trim_history
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

_CACHE = {"type": "ephemeral"}
_TOOL_FINISHED = "agent_shell_tool_finished"

Provider = Literal["claude", "openai"]


class _State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def text_of(content: Any) -> str:
    """Plain text of a message/chunk: a string, or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) and b.get("type", "text") == "text" else
            (b if isinstance(b, str) else "")
            for b in content
        )
    return ""


def to_langchain(history: list[dict[str, Any]], user_text: str) -> list[BaseMessage]:
    """Neutral transcript -> LangChain messages (same for every provider)."""
    out: list[BaseMessage] = []
    for m in history:
        role = m["role"]
        if role == "user":
            out.append(HumanMessage(content=m["content"]))
        elif role == "assistant":
            calls = [
                {"id": c["id"], "name": c["name"], "args": c.get("args", {}), "type": "tool_call"}
                for c in m.get("tool_calls", [])
            ]
            if m["content"] or calls:
                out.append(AIMessage(content=m["content"], tool_calls=calls))
        elif role == "tool":
            out.append(ToolMessage(
                content=m["content"], tool_call_id=m["tool_call_id"], name=m.get("name"),
                status="error" if m.get("is_error") else "success",
            ))
    out.append(HumanMessage(content=user_text))
    return out


def _cache_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    d = usage.get("input_token_details") or {}
    read = int(d.get("cache_read") or 0)
    # langchain-anthropic zeroes `cache_creation` when it reports the 5m/1h split instead
    write = sum(int(d.get(k) or 0) for k in ("cache_creation", "ephemeral_5m_input_tokens",
                                             "ephemeral_1h_input_tokens"))
    return read, write


class LangGraphEngine:
    def __init__(
        self,
        provider: Provider,
        model: str,
        api_key: str | None = None,
        *,
        max_tokens: int = 4096,
        history_turns: int = 20,
        tool_text_cap: int = 1500,
        recursion_limit: int = 25,
        model_factory: Callable[[], BaseChatModel] | None = None,
    ) -> None:
        if estimate_cost(model, 0, 0) is None:
            raise ValueError(
                f"no price for model {model!r}: add it to agent_runtime.budget._PRICING "
                "before using it (an unpriced model would bypass the budget cap)"
            )
        self.provider: Literal["claude", "openai", "fake"] = provider
        self.model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._history_turns = history_turns
        self._tool_text_cap = tool_text_cap
        self._recursion_limit = recursion_limit
        self._model_factory = model_factory
        self._system_prompt = ""
        self._tools: dict[str, StructuredTool] = {}
        self._graph: Any = None
        self._stop = False
        self._ready = asyncio.Event()

    # -- construction ------------------------------------------------------
    def _build_model(self) -> BaseChatModel:
        if self._model_factory is not None:
            return self._model_factory()
        if self.provider == "claude":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(  # type: ignore[call-arg]
                model=self.model,
                api_key=SecretStr(self._api_key) if self._api_key else None,  # type: ignore[arg-type]
                max_tokens=self._max_tokens,
                streaming=True,
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=self.model, api_key=self._api_key, stream_usage=True)  # type: ignore[arg-type]

    def _compile_tools(self, specs: list[ToolSpec]) -> list[StructuredTool]:
        tools: list[StructuredTool] = []
        for i, spec in enumerate(specs):
            async def run(__spec: ToolSpec = spec, **kwargs: Any) -> tuple[str, ToolResult]:
                result = await __spec.handler(kwargs)
                return result.text, result

            extras = {"cache_control": _CACHE} if self.provider == "claude" and i == len(specs) - 1 else None
            tools.append(StructuredTool(
                name=spec.name, description=spec.description,
                args_schema=spec.input_model.model_json_schema(),  # raw args: our executor validates
                coroutine=run, response_format="content_and_artifact", extras=extras,
            ))
        return tools

    async def start(
        self, system_prompt: str, tools: list[ToolSpec], session: SessionRef | None
    ) -> SessionHandle:
        self._system_prompt = system_prompt
        lc_tools = self._compile_tools(tools)
        self._tools = {t.name: t for t in lc_tools}
        model = self._build_model()
        bound = model.bind_tools(lc_tools) if lc_tools else model
        self._graph = self._build_graph(bound)
        return SessionHandle(session_id=session.session_id if session else "langgraph")

    def _system_message(self) -> SystemMessage:
        if self.provider == "claude":
            return SystemMessage(content=[
                {"type": "text", "text": self._system_prompt, "cache_control": _CACHE}
            ])
        return SystemMessage(content=self._system_prompt)

    def _build_graph(self, bound: Any) -> Any:
        async def model_node(state: _State) -> dict[str, Any]:
            response = await bound.ainvoke([self._system_message(), *state["messages"]])
            return {"messages": [response]}

        async def tools_node(state: _State) -> dict[str, Any]:
            # astream_events runs the graph ahead of its consumer. Wait until the session has
            # handled this model step's events (cost, tool-call starts), so a spent budget or an
            # interrupt stops the turn before any tool runs, and confirm prompts follow the
            # "tool started" line.
            await self._ready.wait()
            self._ready.clear()
            last = state["messages"][-1]
            out: list[ToolMessage] = []
            # one at a time: confirm prompts must never overlap
            for call in getattr(last, "tool_calls", []) or []:
                msg = await self._run_tool(call)
                out.append(msg)
                await adispatch_custom_event(_TOOL_FINISHED, msg)
            return {"messages": out}

        def route(state: _State) -> str:
            return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

        g = StateGraph(_State)
        g.add_node("model", model_node)
        g.add_node("tools", tools_node)
        g.add_edge(START, "model")
        g.add_conditional_edges("model", route, {"tools": "tools", END: END})
        g.add_edge("tools", "model")
        return g.compile()

    async def _run_tool(self, call: dict[str, Any]) -> ToolMessage:
        tool = self._tools.get(call["name"])
        if tool is None:
            result = ToolResult(text=f"unknown tool: {call['name']}", is_error=True)
            return ToolMessage(
                content=result.text, tool_call_id=call["id"], name=call["name"],
                status="error", artifact=result,
            )
        try:
            msg: ToolMessage = await tool.ainvoke({
                "name": call["name"], "args": call["args"], "id": call["id"], "type": "tool_call"
            })
        except Exception as e:  # noqa: BLE001 - becomes an error result the model can see
            result = ToolResult(text=f"{type(e).__name__}: {e}", is_error=True)
            return ToolMessage(
                content=result.text, tool_call_id=call["id"], name=call["name"],
                status="error", artifact=result,
            )
        artifact = msg.artifact if isinstance(msg.artifact, ToolResult) else None
        if artifact is not None and artifact.is_error:
            msg.status = "error"
        return msg

    # -- turns -------------------------------------------------------------
    async def send(
        self, handle: SessionHandle, user_text: str, history: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[EngineEvent]:
        self._stop = False
        self._ready = asyncio.Event()
        window = trim_history(
            history or [], last_n_turns=self._history_turns, tool_text_cap=self._tool_text_cap
        )
        messages = to_langchain(window, user_text)
        try:
            async with aclosing(self._graph.astream_events(
                {"messages": messages}, version="v2",
                config={"recursion_limit": self._recursion_limit},
            )) as stream:
                async for ev in stream:
                    if self._stop:
                        yield TurnEnd(reason="interrupted")
                        return
                    for out in self._translate(ev):
                        yield out
                    if ev["event"] == "on_chat_model_end":
                        self._ready.set()  # the session has now handled this step's events
        except GraphRecursionError:
            yield TurnEnd(reason="error", detail=f"stopped after {self._recursion_limit} steps")
            return
        yield TurnEnd(reason="complete")

    def _translate(self, ev: dict[str, Any]) -> list[EngineEvent]:
        kind = ev["event"]
        if kind == "on_chat_model_stream":
            text = text_of(ev["data"]["chunk"].content)
            return [TextDelta(text=text)] if text else []
        if kind == "on_chat_model_end":
            msg = ev["data"]["output"]
            out: list[EngineEvent] = []
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                read, write = _cache_tokens(usage)
                cost = estimate_cost(
                    self.model, usage["input_tokens"], usage["output_tokens"], read, write
                )
                out.append(TurnCost(
                    cost_usd=cost or 0.0, input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"], cache_read_tokens=read,
                    cache_write_tokens=write, model=self.model,
                ))
            for tc in getattr(msg, "tool_calls", []) or []:
                out.append(ToolCallStarted(call_id=tc["id"], name=tc["name"], args=tc["args"]))
            return out
        if kind == "on_custom_event" and ev.get("name") == _TOOL_FINISHED:
            m: ToolMessage = ev["data"]
            result = m.artifact if isinstance(m.artifact, ToolResult) else ToolResult(
                text=text_of(m.content), is_error=m.status == "error"
            )
            return [ToolCallFinished(call_id=m.tool_call_id, name=m.name or "", result=result)]
        return []

    async def interrupt(self, handle: SessionHandle) -> None:
        self._stop = True

    async def close(self, handle: SessionHandle) -> None:
        self._graph = None
