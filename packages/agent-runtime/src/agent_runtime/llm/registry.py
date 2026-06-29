"""Provider registry — resolve an `LLMProvider` by name (or the config default).

Imports of provider SDKs are lazy (inside the branch) so that merely importing the
seam never pulls a provider's SDK unless that provider is actually requested.
"""

from __future__ import annotations

from agent_runtime.config import get_config
from agent_runtime.llm.base import LLMProvider


def get_provider(name: str | None = None) -> LLMProvider:
    """Return the provider for `name`, or the configured default when None.

    Known providers: ``anthropic`` (implemented), ``openai`` (documented stub).
    Raises ``ValueError`` for an unknown name.
    """
    resolved = name or get_config().default_llm_provider
    key = resolved.strip().lower()
    if key == "anthropic":
        from agent_runtime.llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    if key == "openai":
        from agent_runtime.llm.providers.openai import OpenAIProvider

        return OpenAIProvider()
    raise ValueError(
        f"Unknown LLM provider {resolved!r}. Known providers: anthropic, openai."
    )
