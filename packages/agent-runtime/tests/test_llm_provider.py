"""Tests for the provider-agnostic LLM seam (agent_runtime.llm)."""

from __future__ import annotations

import pytest
from anthropic.types import TextBlock

from agent_runtime.config import reset_config
from agent_runtime.llm import LLMCompletion, LLMProvider, get_provider
from agent_runtime.llm.providers.anthropic import AnthropicProvider
from agent_runtime.llm.providers.openai import OpenAIProvider


# ── A fake Anthropic SDK client (no network) ───────────────────────────────────


class _FakeUsage:
    def __init__(self, i: int, o: int) -> None:
        self.input_tokens = i
        self.output_tokens = o


class _FakeResponse:
    def __init__(self, text: str, i: int, o: int) -> None:
        # A real TextBlock so the provider's isinstance(block, TextBlock) guard holds.
        self.content = [TextBlock.model_construct(type="text", text=text)]
        self.usage = _FakeUsage(i, o)


class _FakeMessages:
    def __init__(self, response: _FakeResponse, calls: list[dict]) -> None:
        self._response = response
        self._calls = calls

    async def create(self, **kwargs: object) -> _FakeResponse:
        self._calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, text: str = "{}", i: int = 10, o: int = 5) -> None:
        self.calls: list[dict] = []
        self.messages = _FakeMessages(_FakeResponse(text, i, o), self.calls)


# ── AnthropicProvider ──────────────────────────────────────────────────────────


def test_resolve_model_aliases() -> None:
    p = AnthropicProvider(client=_FakeClient())
    assert p.resolve_model(None) == "claude-sonnet-4-6"
    assert p.resolve_model("opus") == "claude-opus-4-8"
    assert p.resolve_model("sonnet") == "claude-sonnet-4-6"
    # an explicit concrete id passes through unchanged
    assert p.resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_anthropic_complete_returns_completion() -> None:
    client = _FakeClient(text='{"prompt": "x"}', i=12, o=7)
    provider = AnthropicProvider(client=client)
    comp = await provider.complete(
        system="sys", user_text="hello", model="opus", max_tokens=123
    )
    assert isinstance(comp, LLMCompletion)
    assert comp.text == '{"prompt": "x"}'
    assert comp.input_tokens == 12
    assert comp.output_tokens == 7
    assert comp.model == "claude-opus-4-8"
    # the resolved model + max_tokens reached the SDK
    assert client.calls[0]["model"] == "claude-opus-4-8"
    assert client.calls[0]["max_tokens"] == 123


# ── OpenAI stub ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_stub_raises() -> None:
    p = OpenAIProvider()
    assert p.name == "openai"
    with pytest.raises(NotImplementedError):
        p.resolve_model("x")
    with pytest.raises(NotImplementedError):
        await p.complete(system="s", user_text="u", max_tokens=10)


# ── Registry ─────────────────────────────────────────────────────────────────────


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("bogus")


def test_get_provider_openai_returns_stub() -> None:
    p = get_provider("openai")
    assert p.name == "openai"


def test_get_provider_anthropic(fake_env: None) -> None:
    reset_config()
    p = get_provider("anthropic")
    assert p.name == "anthropic"


def test_get_provider_default_is_anthropic(fake_env: None) -> None:
    reset_config()
    p = get_provider(None)
    assert p.name == "anthropic"


# ── A fake provider exercises callers structurally ──────────────────────────────


class FakeProvider:
    name = "fake"

    def resolve_model(self, alias: str | None) -> str:
        return alias or "fake-default"

    async def complete(
        self, *, system, user_text, image_paths=(), model=None, max_tokens
    ) -> LLMCompletion:
        return LLMCompletion(
            text="canned", input_tokens=1, output_tokens=2, model=self.resolve_model(model)
        )


@pytest.mark.asyncio
async def test_fake_provider_satisfies_protocol() -> None:
    def use(p: LLMProvider) -> str:
        return p.name

    fp = FakeProvider()
    assert use(fp) == "fake"
    comp = await fp.complete(system="s", user_text="u", max_tokens=5)
    assert comp.text == "canned"
    assert comp.model == "fake-default"
