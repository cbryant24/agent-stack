"""OpenAI implementation of the `LLMProvider` seam — NOT YET IMPLEMENTED.

A documented stub so the seam is real and selectable (`--provider openai`) while the
actual integration is deferred. It constructs fine (so the registry can return it) but
raises a clear `NotImplementedError` on use.

To implement (do NOT do this yet — it is intentionally out of scope):
- Build a Chat Completions request against a vision-capable model (e.g. ``gpt-4o``):
  ``messages=[{"role": "system", "content": system},
              {"role": "user", "content": [{"type": "text", "text": user_text},
                                           {"type": "image_url", "image_url": {...}}]}]``
  (image parts only when ``image_paths`` is non-empty; base64-encode via a shared helper).
- Read the text from ``choices[0].message.content``.
- Map ``usage.prompt_tokens`` / ``usage.completion_tokens`` into ``LLMCompletion``.
- Add pricing rows for the chosen OpenAI models to ``agent_runtime.budget._PRICING``.
- Resolve the API key from ``get_config().openai_api_key``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_runtime.llm.base import LLMCompletion

_NOT_IMPLEMENTED = (
    "OpenAI provider is not yet implemented. The seam is in place; see the "
    "implementation checklist in agent_runtime/llm/providers/openai.py. Use "
    "--provider anthropic (the default) for now."
)


class OpenAIProvider:
    """Selectable stub; raises until the OpenAI integration is built."""

    name = "openai"

    def resolve_model(self, alias: str | None) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def complete(
        self,
        *,
        system: str,
        user_text: str,
        image_paths: Sequence[Path] = (),
        model: str | None = None,
        max_tokens: int,
    ) -> LLMCompletion:
        raise NotImplementedError(_NOT_IMPLEMENTED)
