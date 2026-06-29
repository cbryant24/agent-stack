"""Anthropic implementation of the `LLMProvider` seam.

Houses the friendly model aliases (`opus`/`sonnet`) that used to live in
visual-generation's constants — they are Anthropic model ids, so they belong with
the Anthropic provider. Every alias target must have a pricing row in
`agent_runtime.budget._PRICING`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from anthropic import AsyncAnthropic
from anthropic.types import TextBlock

from agent_runtime.config import get_config
from agent_runtime.llm.base import LLMCompletion

# An omitted alias (None) resolves to the default (Sonnet). A known alias maps to its
# concrete id; anything else passes through (so an explicit model id is honored).
_DEFAULT_MODEL = "claude-sonnet-4-6"
MODEL_ALIASES: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}


class AnthropicProvider:
    """Talks to Claude via the official Anthropic SDK."""

    name = "anthropic"

    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        self._client = client or AsyncAnthropic(api_key=get_config().anthropic_api_key)

    def resolve_model(self, alias: str | None) -> str:
        if alias is None:
            return _DEFAULT_MODEL
        return MODEL_ALIASES.get(alias, alias)

    async def complete(
        self,
        *,
        system: str,
        user_text: str,
        image_paths: Sequence[Path] = (),
        model: str | None = None,
        max_tokens: int,
    ) -> LLMCompletion:
        # `image_paths` is accepted for forward-compat (vision) but not yet sent.
        resolved = self.resolve_model(model)
        response = await self._client.messages.create(
            model=resolved,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        block = response.content[0] if response.content else None
        text = block.text if isinstance(block, TextBlock) else ""
        return LLMCompletion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=resolved,
        )
