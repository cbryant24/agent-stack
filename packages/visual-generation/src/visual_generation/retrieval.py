"""Parallel retrieval across visual_generation_memory, user_knowledge, and tutorial_research.

Mirrors voiceover/music's three-collection composition. Each leg degrades
silently: a missing collection or an unreachable Qdrant returns an empty bucket
rather than raising, so the agent stays useful from cold start when every
collection is empty.

The own-collection leg fans out into three memory types (generations,
technique_lessons, workflow_templates); `user_knowledge` carries the
score-boosted platform-mechanics facts (comfyui/runpod); `tutorial_research`
carries tutorial-derived diffusion technique.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.memory.store import MemoryStore
from agent_runtime.tracing.decorators import record_memory_query
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from visual_generation.constants import (
    MECHANICS_DOMAINS,
    REACTION_RENDER_FAILED,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
)
from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    """Typed buckets of retrieved content for generation-context assembly."""

    prior_generations: list[tuple[float, VisualGeneration]] = field(default_factory=list)
    technique_lessons: list[tuple[float, TechniqueLesson]] = field(default_factory=list)
    workflow_templates: list[tuple[float, WorkflowTemplate]] = field(default_factory=list)
    comfyui_facts: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    tutorial_hits: list[tuple[float, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.prior_generations,
                self.technique_lessons,
                self.workflow_templates,
                self.comfyui_facts,
                self.tutorial_hits,
            ]
        )

    def max_local_score(self) -> float:
        scores: list[float] = []
        scores.extend(s for s, _ in self.prior_generations)
        scores.extend(s for s, _ in self.technique_lessons)
        scores.extend(s for s, _ in self.workflow_templates)
        scores.extend(s for s, _, _ in self.comfyui_facts)
        scores.extend(s for s, _ in self.tutorial_hits)
        return max(scores, default=0.0)

    def max_user_knowledge_score(self) -> float:
        return max((s for s, _, _ in self.comfyui_facts), default=0.0)

    def max_tutorial_score(self) -> float:
        return max((s for s, _ in self.tutorial_hits), default=0.0)


async def retrieve_context(
    query: str,
    store: VisualGenerationStore,
    memory_store: MemoryStore,
    *,
    include_tutorial: bool = True,
    generation_limit: int = 5,
    lesson_limit: int = 5,
    template_limit: int = 3,
    fact_limit: int = 5,
    tutorial_limit: int = 5,
) -> RetrievedContext:
    """Query all three collections in parallel and return typed buckets.

    user_knowledge hits receive a USER_KNOWLEDGE_SCORE_MULTIPLIER boost so
    user-verified mechanics outrank tutorial hits. Pending generations are
    excluded; only confirmed technique lessons are surfaced. Each leg degrades
    silently — an exception on any leg leaves its bucket empty.
    """
    ctx = RetrievedContext()

    tasks = [
        store.search_generations(query, exclude_pending=True, limit=generation_limit),
        store.search_lessons(query, confirmed_only=True, limit=lesson_limit),
        store.search_templates(query, limit=template_limit),
        _fetch_mechanics_facts(query, memory_store, limit=fact_limit),
    ]
    if include_tutorial:
        tasks.append(_fetch_tutorial(query, memory_store, limit=tutorial_limit))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    gen_results, lesson_results, tmpl_results, fact_results = results[:4]
    tutorial_results = results[4] if include_tutorial else []

    if not isinstance(gen_results, Exception):
        ctx.prior_generations = [(s, g) for _, s, g in gen_results]
        # Similarity is primary; on a tie, a higher rating outranks a lower one.
        ctx.prior_generations.sort(key=lambda sg: (-sg[0], -(sg[1].rating or 0)))
    else:
        logger.warning("prior-generations retrieval failed (degrading gracefully): %s", gen_results)

    if not isinstance(lesson_results, Exception):
        ctx.technique_lessons = [(s, le) for _, s, le in lesson_results]
    else:
        logger.warning("technique-lessons retrieval failed (degrading gracefully): %s", lesson_results)

    if not isinstance(tmpl_results, Exception):
        ctx.workflow_templates = [(s, t) for _, s, t in tmpl_results]
    else:
        logger.warning("workflow-templates retrieval failed (degrading gracefully): %s", tmpl_results)

    if not isinstance(fact_results, Exception):
        ctx.comfyui_facts = fact_results

    if include_tutorial and not isinstance(tutorial_results, Exception):
        ctx.tutorial_hits = tutorial_results
    elif include_tutorial and isinstance(tutorial_results, Exception):
        logger.warning("tutorial_research retrieval failed (degrading gracefully): %s", tutorial_results)

    return ctx


async def _fetch_mechanics_facts(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Query user_knowledge for comfyui/runpod mechanics entries (active only, boosted)."""
    try:
        embedder = memory_store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        # `superseded_by == ""` selects active entries (the runtime's active sentinel).
        # Either mechanics domain is accepted (backend vs. platform).
        filters = Filter(
            must=[
                FieldCondition(key="domain", match=MatchAny(any=MECHANICS_DOMAINS)),
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
        logger.warning("user_knowledge mechanics_facts query failed (degrading gracefully): %s", exc)
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
    - [PRIOR GENERATION: reaction=...] — the user's own past generations
    - [TECHNIQUE LESSON: valence/scope] — confirmed technique preferences
    - [USER FACT: comfyui/runpod_mechanics] — user-verified platform knowledge
    - [TUTORIAL KNOWLEDGE] — tutorial research hits
    - [WORKFLOW TEMPLATE: name] — reusable parameterized graphs
    """
    parts: list[str] = []

    if ctx.prior_generations:
        parts.append("=== Prior Generations ===")
        for score, gen in ctx.prior_generations:
            reaction_label = gen.reaction.upper().replace("_", " ")
            header = f"reaction={reaction_label}"
            if gen.rating is not None:
                header += f", rating={gen.rating}"
            header += f", score={score:.2f}"
            if gen.context:
                header += f', context="{gen.context[:200]}"'
            block = f"[PRIOR GENERATION: {header}]\n"
            # render_failed is a render issue, not an aesthetic rejection: the intent
            # didn't render and the territory is still open. Surface it as a
            # learn-from-the-structure signal rather than a reason to avoid the
            # territory (disliked does the latter).
            if gen.reaction == REACTION_RENDER_FAILED:
                block += (
                    "(ComfyUI mis-rendered this spec — the direction/territory is still "
                    "open. Learn from this spec's structure; revise settings/prompt, do "
                    "not abandon the direction.)\n"
                )
            if gen.model:
                block += f"Model: {gen.model}"
                if gen.lora_stack:
                    loras = ", ".join(f"{lr.name}@{lr.strength}" for lr in gen.lora_stack)
                    block += f" | LoRAs: {loras}"
                block += "\n"
            block += f"Caption: {gen.caption[:200]}"
            if gen.prompt:
                block += f"\nPrompt: {gen.prompt[:300]}"
            parts.append(block)

    if ctx.technique_lessons:
        parts.append("=== Technique Lessons ===")
        for score, lesson in ctx.technique_lessons:
            parts.append(
                f"[TECHNIQUE LESSON: {lesson.valence}/{lesson.scope}, score={score:.2f}]\n{lesson.statement}"
            )

    if ctx.comfyui_facts:
        parts.append("=== Platform Knowledge (User Verified) ===")
        for score, statement, payload in ctx.comfyui_facts:
            domain = payload.get("domain", "mechanics")
            parts.append(f"[USER FACT: {domain}, score={score:.2f}]\n{statement}")

    if ctx.tutorial_hits:
        parts.append("=== Tutorial Research ===")
        for score, content in ctx.tutorial_hits:
            if content:
                parts.append(f"[TUTORIAL KNOWLEDGE, score={score:.2f}]\n{content[:300]}")

    if ctx.workflow_templates:
        parts.append("=== Related Workflow Templates ===")
        for score, tmpl in ctx.workflow_templates:
            req = f" | requires: {', '.join(tmpl.required_models)}" if tmpl.required_models else ""
            parts.append(f"[WORKFLOW TEMPLATE: {tmpl.name}, score={score:.2f}{req}]\n{tmpl.descriptor[:300]}")

    return "\n\n".join(parts)
