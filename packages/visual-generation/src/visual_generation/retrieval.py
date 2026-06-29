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
    CANON_DOMAINS,
    CANON_SCORE_MULTIPLIER,
    COLLECTION_NAME,
    MECHANICS_DOMAINS,
    REACTION_RENDER_FAILED,
    TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
    TECHNIQUE_VISUAL_SCOPES,
    TUTORIAL_RESEARCH_COLLECTION,
    USER_KNOWLEDGE_COLLECTION,
    USER_KNOWLEDGE_SCORE_MULTIPLIER,
    VISUAL_TUTORIAL_TAGS,
)
from visual_generation.models import (
    ProvenanceLeg,
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)
from visual_generation.store import VisualGenerationStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    """Typed buckets of retrieved content for generation-context assembly."""

    prior_generations: list[tuple[float, VisualGeneration]] = field(default_factory=list)
    technique_lessons: list[tuple[float, TechniqueLesson]] = field(default_factory=list)
    workflow_templates: list[tuple[float, WorkflowTemplate]] = field(default_factory=list)
    comfyui_facts: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    canon_facts: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    technique_reports: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    tutorial_hits: list[tuple[float, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.prior_generations,
                self.technique_lessons,
                self.workflow_templates,
                self.comfyui_facts,
                self.canon_facts,
                self.technique_reports,
                self.tutorial_hits,
            ]
        )

    def max_local_score(self) -> float:
        scores: list[float] = []
        scores.extend(s for s, _ in self.prior_generations)
        scores.extend(s for s, _ in self.technique_lessons)
        scores.extend(s for s, _ in self.workflow_templates)
        scores.extend(s for s, _, _ in self.comfyui_facts)
        scores.extend(s for s, _, _ in self.canon_facts)
        scores.extend(s for s, _, _ in self.technique_reports)
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
    canon_limit: int = 5,
    technique_report_limit: int = 3,
    tutorial_limit: int = 5,
) -> RetrievedContext:
    """Query every knowledge leg in parallel and return typed buckets.

    Legs (each degrades silently — an exception leaves its bucket empty):
    own memory (generations/lessons/templates), user_knowledge mechanics facts
    (boosted), project canon (boosted highest — locked authority),
    technique_research_outputs (visual-tagged), and tutorial_research
    (visual-tag-biased). Pending generations are excluded; only confirmed
    technique lessons are surfaced.
    """
    ctx = RetrievedContext()

    # Labeled so adding/removing a leg can't desync positional unpacking.
    legs: dict[str, Any] = {
        "generations": store.search_generations(query, exclude_pending=True, limit=generation_limit),
        "lessons": store.search_lessons(query, confirmed_only=True, limit=lesson_limit),
        "templates": store.search_templates(query, limit=template_limit),
        "facts": _fetch_mechanics_facts(query, memory_store, limit=fact_limit),
        "canon": _fetch_canon(query, memory_store, limit=canon_limit),
        "technique_reports": _fetch_technique_reports(query, memory_store, limit=technique_report_limit),
    }
    if include_tutorial:
        legs["tutorial"] = _fetch_tutorial(query, memory_store, limit=tutorial_limit)

    labels = list(legs)
    gathered = await asyncio.gather(*legs.values(), return_exceptions=True)
    out = dict(zip(labels, gathered))

    def _log(label: str, value: BaseException) -> None:
        logger.warning("%s retrieval failed (degrading gracefully): %s", label, value)

    gen_results = out["generations"]
    if isinstance(gen_results, BaseException):
        _log("prior-generations", gen_results)
    else:
        ctx.prior_generations = [(s, g) for _, s, g in gen_results]
        # Similarity is primary; on a tie, a higher rating outranks a lower one.
        ctx.prior_generations.sort(key=lambda sg: (-sg[0], -(sg[1].rating or 0)))

    lesson_results = out["lessons"]
    if isinstance(lesson_results, BaseException):
        _log("technique-lessons", lesson_results)
    else:
        ctx.technique_lessons = [(s, le) for _, s, le in lesson_results]

    tmpl_results = out["templates"]
    if isinstance(tmpl_results, BaseException):
        _log("workflow-templates", tmpl_results)
    else:
        ctx.workflow_templates = [(s, t) for _, s, t in tmpl_results]

    facts = out["facts"]
    if isinstance(facts, BaseException):
        _log("user_knowledge", facts)
    else:
        ctx.comfyui_facts = facts

    canon = out["canon"]
    if isinstance(canon, BaseException):
        _log("project-canon", canon)
    else:
        ctx.canon_facts = canon

    reports = out["technique_reports"]
    if isinstance(reports, BaseException):
        _log("technique_research_outputs", reports)
    else:
        ctx.technique_reports = reports

    if include_tutorial:
        tut = out["tutorial"]
        if isinstance(tut, BaseException):
            _log("tutorial_research", tut)
        else:
            ctx.tutorial_hits = tut

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


def _visual_tags_filter() -> Filter:
    """Match a chunk whose `domain_tags` OR `topic_tags` carry any visual tag.

    `should` = at least one condition matches, so a chunk tagged visually under
    either field is selected and music/langgraph/editing chunks are excluded."""
    return Filter(
        should=[
            FieldCondition(key="domain_tags", match=MatchAny(any=VISUAL_TUTORIAL_TAGS)),
            FieldCondition(key="topic_tags", match=MatchAny(any=VISUAL_TUTORIAL_TAGS)),
        ]
    )


def _technique_scope_filter() -> Filter:
    """Match a technique_research_outputs chunk scoped to image work.

    technique_research_outputs is tagged by the technique-research agent's scope
    vocabulary (TechniqueReport.scope → `topic_tags` ∈ {editing, generation, both};
    `domain_tags` is the freeform technique title, not a controlled tag). So we
    filter on `topic_tags` against the visual scopes — NOT VISUAL_TUTORIAL_TAGS,
    which uses tutorial_research's vocabulary and matches zero rows here."""
    return Filter(
        must=[FieldCondition(key="topic_tags", match=MatchAny(any=TECHNIQUE_VISUAL_SCOPES))]
    )


async def _fetch_tutorial(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str]]:
    """Query tutorial_research, biased toward visually-tagged chunks.

    tutorial_research is a shared, cross-domain pool (music/langgraph/etc.), so an
    unfiltered semantic search lets relevant z-image/diffusion chunks get crowded
    out. We first search with the visual-tag filter; only if nothing visually
    tagged matches do we fall back to an unfiltered search (so a cold/untagged
    collection still returns something rather than going blind).

    The chunk text lives in MemoryPoint.text; `content_type` is only a type label
    ("text"/"image_with_caption"), so we read .text (falling back to .caption for
    image points), never content_type.
    """
    try:
        results = await memory_store.search(
            TUTORIAL_RESEARCH_COLLECTION, query, limit=limit, filters=_visual_tags_filter()
        )
        if not results:
            results = await memory_store.search(TUTORIAL_RESEARCH_COLLECTION, query, limit=limit)
        return [(r.score, r.point.text or r.point.caption or "") for r in results]
    except Exception as exc:
        logger.warning("tutorial_research query failed (degrading gracefully): %s", exc)
        return []


async def _fetch_canon(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Query user_knowledge for locked project-canon entries (active only, boosted highest).

    Mirrors `_fetch_mechanics_facts` but on CANON_DOMAINS with the higher
    CANON_SCORE_MULTIPLIER, since canon is locked authority. Surfaced under the
    [PROJECT CANON] tier; deterministic enforcement (canon.py) is what *guarantees*
    it — this leg only makes it visible to the author/grader."""
    try:
        embedder = memory_store.embedding_client
        [qv] = await embedder.embed([query], input_type="query")
        filters = Filter(
            must=[
                FieldCondition(key="domain", match=MatchAny(any=CANON_DOMAINS)),
                FieldCondition(key="superseded_by", match=MatchValue(value="")),
            ]
        )
        raw = await memory_store.query_by_vector(
            USER_KNOWLEDGE_COLLECTION, qv, limit=limit, filters=filters
        )
        boosted = [
            (score * CANON_SCORE_MULTIPLIER, payload.get("statement", ""), payload)
            for _, score, payload in raw
        ]
        record_memory_query(USER_KNOWLEDGE_COLLECTION, query, len(boosted))
        return boosted
    except Exception as exc:
        logger.warning("user_knowledge canon query failed (degrading gracefully): %s", exc)
        return []


async def _fetch_technique_reports(
    query: str,
    memory_store: MemoryStore,
    limit: int,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Query technique_research_outputs for visually-tagged technique findings.

    This collection is shared with the editing pipeline (DaVinci/color-grade), so
    we filter to image-scoped reports (`topic_tags` ∈ {generation, both}) with NO
    unfiltered fallback — surfacing a visual report (e.g. the stop-motion/storybook
    one, scoped `both`) is the goal; pulling in `editing`-scoped noise is not."""
    try:
        results = await memory_store.search(
            TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION,
            query,
            limit=limit,
            filters=_technique_scope_filter(),
        )
        return [
            (
                r.score,
                r.point.text or r.point.caption or "",
                {
                    "source_title": r.point.source_title,
                    "domain_tags": r.point.domain_tags,
                    "topic_tags": r.point.topic_tags,
                },
            )
            for r in results
        ]
    except Exception as exc:
        logger.warning("technique_research_outputs query failed (degrading gracefully): %s", exc)
        return []


def build_context_prompt(ctx: RetrievedContext) -> str:
    """Format retrieved context into a source-tagged prompt block for the chain.

    Prefixes distinguish source types so the model can weight them (by tier):
    - [PROJECT CANON: domain] — LOCKED authority; never contradict (highest)
    - [PRIOR GENERATION: reaction=...] — the user's own past generations
    - [TECHNIQUE LESSON: valence/scope] — confirmed technique preferences
    - [TECHNIQUE REPORT] — visual technique-research findings
    - [USER FACT: comfyui/runpod_mechanics] — user-verified platform knowledge
    - [TUTORIAL KNOWLEDGE] — tutorial research hits (reference; defer to the above)
    - [WORKFLOW TEMPLATE: name] — reusable parameterized graphs
    """
    parts: list[str] = []

    if ctx.canon_facts:
        parts.append("=== Project Canon (LOCKED — never contradict) ===")
        for score, statement, payload in ctx.canon_facts:
            domain = payload.get("domain", "canon")
            parts.append(f"[PROJECT CANON: {domain}, score={score:.2f}]\n{statement}")

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

    if ctx.technique_reports:
        parts.append("=== Technique Reports (Visual) ===")
        for score, content, payload in ctx.technique_reports:
            if not content:
                continue
            title = payload.get("source_title")
            header = f"[TECHNIQUE REPORT, score={score:.2f}]"
            if title:
                header = f"[TECHNIQUE REPORT: {title}, score={score:.2f}]"
            parts.append(f"{header}\n{content[:300]}")

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


def _snip(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


def summarize_provenance(ctx: RetrievedContext, *, per_leg: int = 2) -> list[ProvenanceLeg]:
    """Deterministically summarize what each retrieval leg surfaced — the
    'prove it, don't trust it' record. Computed from code, never the LLM's claim.

    Only non-empty legs appear, ordered by tier (locked → strong → reference)."""
    legs: list[ProvenanceLeg] = []

    def add(label: str, collection: str, tier: str, scored: list[tuple[float, str]]) -> None:
        if not scored:
            return
        legs.append(
            ProvenanceLeg(
                label=label,
                collection=collection,
                tier=tier,  # type: ignore[arg-type]
                count=len(scored),
                top_score=max(s for s, _ in scored),
                snippets=[_snip(t) for _, t in scored[:per_leg] if t],
            )
        )

    add("Project canon", USER_KNOWLEDGE_COLLECTION, "locked",
        [(s, t) for s, t, _ in ctx.canon_facts])
    add("Prior generations", COLLECTION_NAME, "strong",
        [(s, g.caption or g.prompt or "") for s, g in ctx.prior_generations])
    add("Technique lessons", COLLECTION_NAME, "strong",
        [(s, le.statement) for s, le in ctx.technique_lessons])
    add("Technique reports", TECHNIQUE_RESEARCH_OUTPUTS_COLLECTION, "strong",
        [(s, (p.get("source_title") or t)) for s, t, p in ctx.technique_reports])
    add("Platform facts", USER_KNOWLEDGE_COLLECTION, "strong",
        [(s, t) for s, t, _ in ctx.comfyui_facts])
    add("Tutorial research", TUTORIAL_RESEARCH_COLLECTION, "reference", ctx.tutorial_hits)
    add("Workflow templates", COLLECTION_NAME, "reference",
        [(s, t.name) for s, t in ctx.workflow_templates])
    return legs
