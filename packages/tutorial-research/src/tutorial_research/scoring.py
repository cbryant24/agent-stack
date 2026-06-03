from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic

from agent_runtime import BudgetExhaustedError, TraceEvent
from agent_runtime.budget import BudgetTracker
from agent_runtime.tracing import get_current_persister

from tutorial_research.constants import MODEL_SCORER
from tutorial_research.models import CandidateEntry, ScoredCandidate

logger = logging.getLogger(__name__)

_SCORE_TOOL = {
    "name": "score_video",
    "description": "Score a YouTube video for topical relevance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "integer",
                "description": "Relevance score 1-5 (5 = highly relevant).",
                "minimum": 1,
                "maximum": 5,
            },
            "rationale": {
                "type": "string",
                "description": "One sentence explaining the score.",
            },
        },
        "required": ["score", "rationale"],
    },
}

_SYSTEM = (
    "You score YouTube videos for relevance to a research topic. "
    "Weigh topical fit above all other factors. "
    "A video with no captions costs more wall-time due to local Whisper transcription "
    "but no extra API cost — treat has_captions=false as a minor soft negative only when "
    "two videos are otherwise equal."
)


async def score_candidates(
    topic: str,
    candidates: list[CandidateEntry],
    tracker: BudgetTracker,
    client: AsyncAnthropic,
) -> list[ScoredCandidate]:
    scored: list[ScoredCandidate] = []
    total_input = 0
    total_output = 0

    for candidate in candidates:
        prompt = (
            f"Topic: {topic}\n"
            f"Title: {candidate.title}\n"
            f"Channel: {candidate.channel}\n"
            f"Description: {candidate.description[:300]}\n"
            f"Duration: {candidate.duration_seconds}s\n"
            f"Views: {candidate.view_count:,}\n"
            f"Has captions: {candidate.has_captions}"
        )
        try:
            response = await client.messages.create(
                model=MODEL_SCORER,
                max_tokens=150,
                system=_SYSTEM,
                tools=[_SCORE_TOOL],
                tool_choice={"type": "tool", "name": "score_video"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            logger.warning("Scoring failed for %s: %s — skipping", candidate.url, exc)
            continue

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if not tool_block:
            logger.warning("No tool_use block for %s — skipping", candidate.url)
            continue

        result = tool_block.input
        scored.append(
            ScoredCandidate(
                url=candidate.url,
                title=candidate.title,
                channel=candidate.channel,
                duration_seconds=candidate.duration_seconds,
                view_count=candidate.view_count,
                has_captions=candidate.has_captions,
                score=int(result["score"]),
                rationale=result["rationale"],
            )
        )

    if total_input or total_output:
        tracker.add_llm_cost(MODEL_SCORER, total_input, total_output)

    persister = get_current_persister()
    if persister:
        persister.record(
            TraceEvent(
                event_type="info",
                metadata={
                    "event_subtype": "candidate_scoring",
                    "topic": topic,
                    "candidates_scored": len(scored),
                    "scores": [{"url": s.url, "score": s.score, "rationale": s.rationale} for s in scored],
                },
            )
        )

    return scored
