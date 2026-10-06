"""Scripted chat model for LangGraph-engine tests (no network, no keys).

Lives in a conftest because pytest's importlib mode cannot import sibling helper modules.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, cast

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.ai import InputTokenDetails, UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from agent_shell.engine.langgraph_engine import LangGraphEngine

CLAUDE_MODEL = "claude-sonnet-4-6"   # priced in agent_runtime
OPENAI_MODEL = "gpt-5-mini"          # priced in agent_runtime


class SimChat(BaseChatModel):
    """Each model call consumes one script step:
    {"text": str, "calls": [(name, args)], "usage": (input, output, cache_read, cache_write)}.
    `shape` picks the provider's content format: Anthropic block lists vs OpenAI strings.
    """

    script: list[dict[str, Any]] = Field(default_factory=list)
    shape: str = "openai"
    delay: float = 0.0
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    bound: list[Any] = Field(default_factory=list)
    _i: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "sim"

    def bind_tools(self, tools: Any, **kwargs: Any) -> SimChat:  # type: ignore[override]
        self.bound = list(tools)
        return self

    def _content(self, text: str) -> Any:
        return [{"type": "text", "text": text, "index": 0}] if self.shape == "anthropic" else text

    def _chunks(self, messages: list[BaseMessage]) -> Iterator[AIMessageChunk]:
        self.seen.append(list(messages))
        step = self.script[self._i] if self._i < len(self.script) else {"text": "(script ended)"}
        self._i += 1
        text = step.get("text", "")
        for word in [w + " " for w in text.split(" ")] if text else []:
            yield AIMessageChunk(content=self._content(word))
        for n, (name, args) in enumerate(step.get("calls", [])):
            yield AIMessageChunk(
                content="" if self.shape == "openai" else [],
                tool_call_chunks=[{
                    "name": name, "args": json.dumps(args), "id": f"call_{self._i}_{n}", "index": n,
                }],
            )
        inp, out, read, write = cast(tuple[int, int, int, int], step.get("usage", (100, 20, 0, 0)))
        details = InputTokenDetails(cache_read=read)
        if self.shape == "anthropic":
            details["cache_creation"] = write
        yield AIMessageChunk(
            content="",
            usage_metadata=UsageMetadata(
                input_tokens=inp, output_tokens=out, total_tokens=inp + out,
                input_token_details=details,
            ),
        )

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any,
    ) -> ChatResult:
        final: AIMessageChunk | None = None
        for c in self._chunks(messages):
            final = c if final is None else final + c
        assert final is not None
        msg = AIMessage(
            content=final.content, tool_calls=final.tool_calls, usage_metadata=final.usage_metadata
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _astream(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for c in self._chunks(messages):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield ChatGenerationChunk(message=c)


class Sim:
    """An engine wired to a SimChat, plus access to what the model received."""

    def __init__(self, engine: LangGraphEngine, holder: dict[str, SimChat]) -> None:
        self.engine, self._holder = engine, holder

    @property
    def model(self) -> SimChat:
        return self._holder["model"]


@pytest.fixture
def sim() -> Callable[..., Sim]:
    def build(
        script: list[dict[str, Any]], *, provider: str = "claude", model: str | None = None,
        delay: float = 0.0, **engine_kw: Any,
    ) -> Sim:
        holder: dict[str, SimChat] = {}

        def factory() -> SimChat:
            holder["model"] = SimChat(
                script=script, shape="anthropic" if provider == "claude" else "openai", delay=delay
            )
            return holder["model"]

        name = model or (CLAUDE_MODEL if provider == "claude" else OPENAI_MODEL)
        engine = LangGraphEngine(provider, name, "key", model_factory=factory, **engine_kw)  # type: ignore[arg-type]
        return Sim(engine, holder)

    return build
