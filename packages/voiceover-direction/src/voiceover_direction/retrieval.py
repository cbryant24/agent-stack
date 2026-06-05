"""Parallel retrieval across voiceover_direction_memory, user_knowledge, and tutorial_research.

Mirrors music-curation's three-collection composition. Each leg degrades silently:
a missing collection or an unreachable Qdrant returns an empty bucket rather than
raising, so `direct` stays useful from cold start when every collection is empty.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query
from qdrant_client.models import FieldCondition, Filter, MatchValue

from voiceover_direction.constants import (
    ELEVENLABS_MECHANICS_DOMAIN,
    REACTION_RENDER_FAILED,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from voiceover_direction.models import DirectionLesson, Take
from voiceover_direction.store import VoiceoverDirectionStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    """Typed buckets of retrieved content for direction context assembly."""

    prior_takes: list[tuple[float, Take]] = field(default_factory=list)
    direction_lessons: list[tuple[float, DirectionLesson]] = field(default_factory=list)
    elevenlabs_facts: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    tutorial_hits: list[tuple[float, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.prior_takes,
                self.direction_lessons,
                self.elevenlabs_facts,
                self.tutorial_hits,
            ]
        )


async def retrieve_context(
    query: str,
    store: VoiceoverDirectionStore,
    memory_store: MemoryStore,
    *,
    include_tutorial: bool = True,
    section_id: str | None = None,
    take_limit: int = 5,
    lesson_limit: int = 5,
    fact_limit: int = 5,
    tutorial_limit: int = 5,
) -> RetrievedContext:
    """Query all three collections in parallel and return typed buckets.

    user_knowledge hits receive a USER_KNOWLEDGE_SCORE_MULTIPLIER boost so
    user-verified mechanics outrank tutorial hits. Pending takes are excluded;
    only confirmed direction lessons are surfaced. When `section_id` is given, the
    prior-takes leg is scoped to that section (used by the option-B fold-in, where
    the relevant history is the section's own take chain).
    """
    ctx = RetrievedContext()

    tasks = [
        store.search_takes(query, section_id=section_id, exclude_pending=True, limit=take_limit),
        store.search_lessons(query, confirmed_only=True, limit=lesson_limit),
        _fetch_elevenlabs_facts(query, memory_store, limit=fact_limit),
    ]
    if include_tutorial:
        tasks.append(_fetch_tutorial(query, memory_store, limit=tutorial_limit))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    take_results, lesson_results, fact_results = results[:3]
    tutorial_results = results[3] if include_tutorial else []

    if not isinstance(take_results, Exception):
        ctx.prior_takes = [(s, t) for _, s, t in take_results]
        # Similarity is primary; on a tie, a higher rating outranks a lower one.
        ctx.prior_takes.sort(key=lambda st: (-st[0], -(st[1].rating or 0)))
    else:
        logger.warning("prior-takes retrieval failed (degrading gracefully): %s", take_results)

    if not isinstance(lesson_results, Exception):
        ctx.direction_lessons = [(s, le) for _, s, le in lesson_results]
    else:
        logger.warning("direction-lessons retrieval failed (degrading gracefully): %s", lesson_results)

    if not isinstance(fact_results, Exception):
        ctx.elevenlabs_facts = fact_results

    if include_tutorial and not isinstance(tutorial_results, Exception):
        ctx.tutorial_hits = tutorial_results
    elif include_tutorial and isinstance(tutorial_results, Exception):
        logger.warning("tutorial_research retrieval failed (degrading gracefully): %s", tutorial_results)

    return ctx


async def _fetch_elevenlabs_facts(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Query user_knowledge for elevenlabs_mechanics entries (active only, boosted)."""
    try:
        embedder = memory_store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        # `superseded_by == ""` selects active entries (the runtime's active sentinel).
        filters = Filter(
            must=[
                FieldCondition(key="domain", match=MatchValue(value=ELEVENLABS_MECHANICS_DOMAIN)),
                FieldCondition(key="superseded_by", match=MatchValue(value="")),
            ]
        )
        raw = await memory_store.query_by_vector(
            USER_KNOWLEDGE_COLLECTION, qv, limit=limit, filters=filters
        )
        boosted = [
            (score * USER_KNOWLEDGE_SCORE_MULTIPLIER, payload.get("statement", ""), payload)
            for _, score, payload in raw
        ]
        record_memory_query(USER_KNOWLEDGE_COLLECTION, query, len(boosted))
        return boosted
    except Exception as exc:
        logger.warning("user_knowledge elevenlabs_facts query failed (degrading gracefully): %s", exc)
        return []


async def _fetch_tutorial(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str]]:
    """Query tutorial_research for relevant knowledge chunks.

    The chunk text lives in MemoryPoint.text; `content_type` is only a type label
    ("text"/"image_with_caption"), so we read .text (falling back to .caption for
    image points), never content_type.
    """
    try:
        results = await memory_store.search(TUTORIAL_RESEARCH_COLLECTION, query, limit=limit)
        return [(r.score, r.point.text or r.point.caption or "") for r in results]
    except Exception as exc:
        logger.warning("tutorial_research query failed (degrading gracefully): %s", exc)
        return []


def build_context_prompt(ctx: RetrievedContext) -> str:
    """Format retrieved context into a source-tagged prompt block for the chain.

    Prefixes distinguish source types so the model can weight them:
    - [PRIOR TAKE: reaction=...] — the user's own past takes (with reactions)
    - [DIRECTION LESSON: valence/scope] — confirmed direction preferences
    - [USER FACT: elevenlabs_mechanics] — user-verified ElevenLabs knowledge
    - [TUTORIAL KNOWLEDGE] — tutorial research hits
    """
    parts: list[str] = []

    if ctx.prior_takes:
        parts.append("=== Prior Takes ===")
        for score, take in ctx.prior_takes:
            reaction_label = take.reaction.upper().replace("_", " ")
            header = f"reaction={reaction_label}"
            if take.rating is not None:
                header += f", rating={take.rating}"
            header += f", score={score:.2f}"
            if take.context:
                header += f', context="{take.context[:200]}"'
            block = f"[PRIOR TAKE: {header}]\n"
            # render_failed is a render issue, not an aesthetic rejection: the direction was
            # fine and the territory is still open. Surface it as a learn-from-the-structure
            # signal rather than a reason to avoid the territory (disliked does the latter).
            if take.reaction == REACTION_RENDER_FAILED:
                block += (
                    "(ElevenLabs mis-rendered this take — the direction/territory is still "
                    "open. Learn from this take's structure; revise tags/params, do not "
                    "abandon the direction.)\n"
                )
            block += f"Voice: {take.voice_id or '(unset)'} | Model: {take.model}\n"
            if take.emotion_tags:
                block += f"Tags: {', '.join(take.emotion_tags)}\n"
            block += f"Text: {take.text[:300]}"
            parts.append(block)

    if ctx.direction_lessons:
        parts.append("=== Direction Lessons ===")
        for score, lesson in ctx.direction_lessons:
            parts.append(
                f"[DIRECTION LESSON: {lesson.valence}/{lesson.scope}, score={score:.2f}]\n{lesson.statement}"
            )

    if ctx.elevenlabs_facts:
        parts.append("=== ElevenLabs Knowledge (User Verified) ===")
        for score, statement, _ in ctx.elevenlabs_facts:
            parts.append(f"[USER FACT: elevenlabs_mechanics, score={score:.2f}]\n{statement}")

    if ctx.tutorial_hits:
        parts.append("=== Tutorial Research ===")
        for score, content in ctx.tutorial_hits:
            if content:
                parts.append(f"[TUTORIAL KNOWLEDGE, score={score:.2f}]\n{content[:300]}")

    return "\n\n".join(parts)
