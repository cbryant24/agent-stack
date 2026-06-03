from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from agent_runtime.budget import BudgetTracker

from tutorial_research.constants import MAX_SYNTHESIS_TOKENS, MODEL_SYNTHESIZER
from tutorial_research.models import RetrievedChunk

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a research assistant synthesizing information from YouTube tutorial transcripts "
    "and user-verified knowledge. "
    "Produce a structured research summary with: "
    "1) A 2-3 sentence overview of the topic, "
    "2) Key concepts and techniques covered (bulleted), "
    "3) Source attribution — for each major point, cite the source_id of the chunk it came from.\n\n"
    "Source chunk types:\n"
    "- Chunks prefixed [SOURCE: ...] come from YouTube tutorial transcripts.\n"
    "- Chunks prefixed [USER-KNOWLEDGE: ...] come from the user's own verified notes and "
    "documentation. Treat these as authoritative: when a USER-KNOWLEDGE chunk conflicts "
    "with a tutorial chunk on the same point, prefer the USER-KNOWLEDGE fact. "
    'Cite USER-KNOWLEDGE chunks with provenance-aware language: "per the user\'s verified notes" '
    'or "per verified knowledge" — not as a generic source. '
    "Be concise. Do not repeat content verbatim."
)


async def synthesize(
    request: str,
    chunks: list[RetrievedChunk],
    tracker: BudgetTracker,
    client: AsyncAnthropic,
) -> str:
    if not chunks:
        return ""

    context_parts = []
    for chunk in chunks:
        if chunk.collection_name == "user_knowledge":
            prefix = f"[USER-KNOWLEDGE: {chunk.source_id}]"
        else:
            prefix = f"[SOURCE: {chunk.source_id}]"
        context_parts.append(f"{prefix} {chunk.content[:800]}")
    context = "\n\n".join(context_parts)

    prompt = f"Research question: {request}\n\nSource chunks:\n{context}"

    response = await client.messages.create(
        model=MODEL_SYNTHESIZER,
        max_tokens=MAX_SYNTHESIS_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    tracker.add_llm_cost(
        MODEL_SYNTHESIZER,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    return response.content[0].text
