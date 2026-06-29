"""Provider-agnostic LLM completion seam.

A deliberately small **multimodal text-completion** interface so callers can target
Claude, OpenAI, or any other provider the way `--model` is chosen today. The seam
returns raw text + token counts; JSON parsing and any domain schema stay in the
caller, so the seam never learns anything about a specific agent's output shape.

`image_paths` is part of the signature for forward-compatibility (vision); a provider
may ignore it until vision support lands. Cost attribution stays caller-side: the
caller records `LLMCompletion.{model,input_tokens,output_tokens}` through the budget
tracker, which is already keyed by model id and provider-agnostic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class LLMCompletion:
    """One completion result, with token counts for cost attribution."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str  # concrete model id actually used (for cost attribution)


class LLMProvider(Protocol):
    """A pluggable text-completion provider (Claude first; OpenAI/others later)."""

    name: str

    def resolve_model(self, alias: str | None) -> str:
        """Map a `--model` alias (or None) to a concrete model id for this provider.

        None resolves to the provider's default; a known alias maps to its target;
        anything else passes through unchanged (so an explicit model id works)."""
        ...

    async def complete(
        self,
        *,
        system: str,
        user_text: str,
        image_paths: Sequence[Path] = (),
        model: str | None = None,
        max_tokens: int,
    ) -> LLMCompletion:
        """Run one completion and return the raw text + token usage."""
        ...
