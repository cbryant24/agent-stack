"""Parallel retrieval across music_curation_memory, user_knowledge, and tutorial_research."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query

from music_curation.constants import (
    REACTION_PROMPT_FAILED,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from music_curation.models import Generation, GenerationRef, TasteLesson, Template
from music_curation.store import MusicCurationStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    """Typed buckets of retrieved content for generation context assembly."""
    prior_generations: list[tuple[float, Generation]] = field(default_factory=list)
    taste_lessons: list[tuple[float, TasteLesson]] = field(default_factory=list)
    templates: list[tuple[float, Template]] = field(default_factory=list)
    suno_facts: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    tutorial_hits: list[tuple[float, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.prior_generations, self.taste_lessons, self.templates,
            self.suno_facts, self.tutorial_hits,
        ])

    def max_local_score(self) -> float:
        scores: list[float] = []
        scores.extend(s for s, _ in self.prior_generations)
        scores.extend(s for s, _ in self.taste_lessons)
        scores.extend(s for s, _ in self.templates)
        scores.extend(s for s, _, _ in self.suno_facts)
        scores.extend(s for s, _ in self.tutorial_hits)
        return max(scores, default=0.0)

    def max_user_knowledge_score(self) -> float:
        return max((s for s, _, _ in self.suno_facts), default=0.0)

    def max_tutorial_score(self) -> float:
        return max((s for s, _ in self.tutorial_hits), default=0.0)


async def retrieve_context(
    query: str,
    curation_store: MusicCurationStore,
    memory_store: MemoryStore,
    *,
    include_tutorial: bool = True,
    include_pending_generations: bool = False,
    generation_limit: int = 5,
    taste_limit: int = 5,
    template_limit: int = 3,
    suno_fact_limit: int = 5,
    tutorial_limit: int = 5,
) -> RetrievedContext:
    """Query all three collections in parallel and return typed buckets.

    user_knowledge hits receive a USER_KNOWLEDGE_SCORE_MULTIPLIER boost.
    tutorial_research hits are included only if include_tutorial=True.
    Pending generations are excluded by default (included only for review-pending flow).
    """
    ctx = RetrievedContext()

    # Parallel fetches
    tasks = [
        curation_store.search_generations(
            query,
            exclude_pending=not include_pending_generations,
            limit=generation_limit,
        ),
        curation_store.search_taste(query, confirmed_only=True, limit=taste_limit),
        curation_store.search_templates(query, limit=template_limit),
        _fetch_suno_facts(query, memory_store, limit=suno_fact_limit),
    ]
    if include_tutorial:
        tasks.append(_fetch_tutorial(query, memory_store, limit=tutorial_limit))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    gen_results, taste_results, tmpl_results, fact_results = results[:4]
    tutorial_results = results[4] if include_tutorial else []

    if not isinstance(gen_results, Exception):
        ctx.prior_generations = [(s, g) for _, s, g in gen_results]
        # Rating tiebreaker: similarity score is primary; within equal-score matches,
        # a higher rating outranks a lower one (loved+5 above loved+3 on equal match).
        ctx.prior_generations.sort(key=lambda sg: (-sg[0], -(sg[1].rating or 0)))

    if not isinstance(taste_results, Exception):
        ctx.taste_lessons = [(s, t) for _, s, t in taste_results]

    if not isinstance(tmpl_results, Exception):
        ctx.templates = [(s, t) for _, s, t in tmpl_results]

    if not isinstance(fact_results, Exception):
        ctx.suno_facts = fact_results

    if include_tutorial and not isinstance(tutorial_results, Exception):
        ctx.tutorial_hits = tutorial_results
    elif include_tutorial and isinstance(tutorial_results, Exception):
        logger.warning("tutorial_research retrieval failed (degrading gracefully): %s", tutorial_results)

    return ctx


async def _fetch_suno_facts(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str, dict]]:
    """Query user_knowledge for suno_mechanics domain entries."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    try:
        embedder = memory_store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        filters = Filter(must=[
            FieldCondition(key="domain", match=MatchValue(value="suno_mechanics")),
            FieldCondition(key="superseded_by", match=MatchValue(value="")),
        ])
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
        logger.warning("user_knowledge suno_facts query failed (degrading gracefully): %s", exc)
        return []


async def _fetch_tutorial(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str]]:
    """Query tutorial_research for relevant knowledge chunks."""
    try:
        results = await memory_store.search(
            TUTORIAL_RESEARCH_COLLECTION, query, limit=limit
        )
        return [(r.score, r.point.content_type or r.point.caption or "") for r in results]
    except Exception as exc:
        logger.warning("tutorial_research query failed (degrading gracefully): %s", exc)
        return []


def build_context_prompt(ctx: RetrievedContext) -> str:
    """Format retrieved context into a structured prompt block for the generation chain.

    Prefixes distinguish source types so the model can cite correctly:
    - [PRIOR GENERATION: reaction=loved] — user's own past prompts
    - [USER FACT: suno_mechanics] — user-verified Suno knowledge
    - [TUTORIAL KNOWLEDGE] — tutorial research hits
    - [TASTE: positive/genre] — user taste lessons
    """
    parts: list[str] = []

    if ctx.prior_generations:
        parts.append("=== Prior Generations ===")
        for score, gen in ctx.prior_generations:
            reaction_label = gen.reaction.upper().replace("_", " ")
            title = gen.suggested_track_title or gen.entry_id[:8]
            # Header fields: reaction, optional rating, score, optional context.
            header = f"reaction={reaction_label}"
            if gen.rating is not None:
                header += f", rating={gen.rating}"
            header += f", score={score:.2f}"
            if gen.context:
                header += f', context="{gen.context[:200]}"'
            block = f"[PRIOR GENERATION: {header}]\n"
            # prompt_failed is a render failure, not an aesthetic rejection: the
            # territory is still open. Surface it as a learn-from-the-attempt signal
            # rather than a reason to avoid the territory (disliked does the latter).
            if gen.reaction == REACTION_PROMPT_FAILED:
                block += (
                    "(Suno mis-rendered this prompt — the territory is still open. "
                    "Learn from this prompt's structure; do not avoid the territory.)\n"
                )
            block += (
                f"Title: {title}\n"
                f"Style: {gen.style_field[:300]}"
                + (f"\nLyrics: {gen.lyrics_field[:200]}" if gen.lyrics_field else "")
            )
            parts.append(block)

    if ctx.taste_lessons:
        parts.append("=== User Taste ===")
        for score, lesson in ctx.taste_lessons:
            parts.append(
                f"[TASTE: {lesson.valence}/{lesson.scope}, score={score:.2f}]\n{lesson.statement}"
            )

    if ctx.suno_facts:
        parts.append("=== Suno Knowledge (User Verified) ===")
        for score, statement, _ in ctx.suno_facts:
            parts.append(f"[USER FACT: suno_mechanics, score={score:.2f}]\n{statement}")

    if ctx.tutorial_hits:
        parts.append("=== Tutorial Research ===")
        for score, content in ctx.tutorial_hits:
            if content:
                parts.append(f"[TUTORIAL KNOWLEDGE, score={score:.2f}]\n{content[:300]}")

    if ctx.templates:
        parts.append("=== Related Templates ===")
        for score, tmpl in ctx.templates:
            parts.append(
                f"[TEMPLATE: {tmpl.name}, score={score:.2f}]\n{tmpl.style_pattern[:300]}"
            )

    return "\n\n".join(parts)
