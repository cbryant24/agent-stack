from __future__ import annotations

from typing import Literal, cast

from agent_shell.engine.base import Engine

Provider = Literal["fake", "claude", "openai"]


class EngineConfigError(Exception):
    """Raised before any model call when an engine cannot be built safely."""


def make_engine(provider: str, model: str | None = None) -> Engine:
    """Build an engine. Fails fast on a missing key or an unpriced model.

    Keys are passed to the model client, never exported to the environment. The OpenAI key is
    CHAT_OPENAI_API_KEY (separate cost attribution), falling back to the shared one.
    """
    if provider == "fake":
        from agent_shell.demo import demo_engine

        return demo_engine()

    from agent_runtime.config import get_config

    cfg = get_config()
    if provider == "claude":
        key = cfg.anthropic_api_key
        model = model or DEFAULT_MODELS["claude"]
    elif provider == "openai":
        key = cfg.chat_openai_api_key or cfg.openai_api_key
        if not model:
            raise EngineConfigError(
                "pass a model for --provider openai (e.g. --model gpt-5.4-mini); "
                "it must have a price row in agent_runtime.budget._PRICING"
            )
        if not key:
            raise EngineConfigError("set CHAT_OPENAI_API_KEY (or PRODUCTION_AGENTS_OPENAI_API_KEY)")
    else:
        raise EngineConfigError(f"unknown provider: {provider}")

    if key and key.startswith("op://"):
        raise EngineConfigError(
            "the API key is an unresolved 1Password reference (op://...). Run under op run, "
            "e.g. `op run --env-file=.env -- <command>`."
        )

    from agent_shell.engine.langgraph_engine import LangGraphEngine

    try:
        return LangGraphEngine(cast(Literal["claude", "openai"], provider), model, key)
    except ValueError as e:
        raise EngineConfigError(str(e)) from e


DEFAULT_MODELS = {"claude": "claude-sonnet-4-6"}
