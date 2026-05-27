from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from agent_runtime.budget import BudgetTracker
from agent_runtime.reporting import notify_budget_threshold

from tutorial_research.constants import MODEL_SYNTHESIZER
from tutorial_research.models import RetrievedChunk

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a research assistant synthesizing information from YouTube tutorial transcripts. "
    "Produce a structured research summary with: "
    "1) A 2-3 sentence overview of the topic, "
    "2) Key concepts and techniques covered (bulleted), "
    "3) Source attribution — for each major point, cite the source_id of the chunk it came from. "
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
        context_parts.append(f"[{chunk.source_id}] {chunk.content[:800]}")
    context = "\n\n".join(context_parts)

    prompt = f"Research question: {request}\n\nSource chunks:\n{context}"

    response = await client.messages.create(
        model=MODEL_SYNTHESIZER,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    tracker.add_llm_cost(
        MODEL_SYNTHESIZER,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    # TODO(agent-runtime): notify_budget_threshold should fire from BudgetTracker.check_budget;
    # see handoff discrepancy 2026-05-26
    notify_budget_threshold("tutorial-research", tracker.consumption, tracker.envelope)

    return response.content[0].text
