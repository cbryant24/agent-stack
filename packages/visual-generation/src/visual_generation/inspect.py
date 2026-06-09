"""Inspect commands — review-pending, chain show, recall.

All three are pure reads over the agent's OWN memory (the
`visual_generation_memory` collection). `recall` deliberately does NOT span the
three-collection retrieval (that serves draft/explain); it searches the user's
own generations, technique lessons, and workflow templates and returns hits, not
answers. Generation search goes through the store's multimodal query-space
(voyage-multimodal-3, text-only query), the same query-space rule as draft.

Orchestration helpers return typed data (testable directly); the `render_*`
functions are pure string builders (testable without a store).
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_runtime import MemoryStore, get_memory_store

from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate
from visual_generation.store import VisualGenerationStore


# ── helpers ───────────────────────────────────────────────────────────────────


def _settings_summary(gen: VisualGeneration) -> str:
    """A compact one-line settings recipe: model + the load-bearing knobs."""
    parts: list[str] = []
    if gen.model:
        parts.append(gen.model)
    s = gen.settings or {}
    for key in ("steps", "cfg", "flux_guidance", "sampler", "scheduler"):
        if key in s and s[key] is not None:
            parts.append(f"{key}={s[key]}")
    if gen.lora_stack:
        parts.append("LoRAs: " + ", ".join(f"{lr.name}@{lr.strength}" for lr in gen.lora_stack))
    return " | ".join(parts) if parts else "(no settings)"


def _reaction_label(gen: VisualGeneration) -> str:
    label = gen.reaction.upper().replace("_", " ")
    if gen.rating is not None:
        label += f" ★{gen.rating}"
    return label


# ── review-pending ─────────────────────────────────────────────────────────────


async def list_pending(
    *,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> list[VisualGeneration]:
    store = store or VisualGenerationStore(memory_store or get_memory_store())
    await store.ensure_collection()
    return await store.list_pending()


def render_pending(gens: list[VisualGeneration]) -> str:
    if not gens:
        return "No pending generations."
    lines = [f"{len(gens)} pending generation(s):", ""]
    for gen in gens:
        lines.append(f"  {gen.entry_id}")
        prompt = gen.prompt or gen.caption
        lines.append(f"  Prompt:   {prompt[:80]}")
        lines.append(f"  Settings: {_settings_summary(gen)}")
        if gen.asset_path:
            tag = "  [identity-bearing]" if gen.identity_bearing else ""
            lines.append(f"  Asset:    {gen.asset_path}{tag}")
        lines.append(f"  Created:  {gen.created_at}")
        lines.append("  Use: visual-generation report <id> --reaction <X>")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def list_pending_sync(**kwargs: Any) -> list[VisualGeneration]:
    return asyncio.run(list_pending(**kwargs))


# ── chain show ───────────────────────────────────────────────────────────────


async def get_chain(
    chain_root_id: str,
    *,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> list[VisualGeneration]:
    store = store or VisualGenerationStore(memory_store or get_memory_store())
    await store.ensure_collection()
    return await store.get_chain(chain_root_id)


def render_chain(chain_root_id: str, gens: list[VisualGeneration]) -> str:
    if not gens:
        return f"No generations found in chain '{chain_root_id}'."

    by_id = {g.entry_id: g for g in gens}
    # children[parent_id] -> ordered child entries.
    children: dict[str | None, list[VisualGeneration]] = {}
    for g in gens:
        # The root's parent_id is None / itself; treat both as top-level.
        parent = g.parent_id if (g.parent_id and g.parent_id in by_id and g.parent_id != g.entry_id) else None
        children.setdefault(parent, []).append(g)
    for kids in children.values():
        kids.sort(key=lambda g: g.created_at)

    lines = [f"Chain {chain_root_id[:12]} — {len(gens)} generation(s):", ""]

    def _emit(gen: VisualGeneration, depth: int) -> None:
        indent = "  " * depth
        marker = "•" if depth else "▸"
        lines.append(f"{indent}{marker} {gen.entry_id[:12]}  [{_reaction_label(gen)}]")
        if gen.asset_path:
            tag = "  [identity-bearing]" if gen.identity_bearing else ""
            lines.append(f"{indent}    {gen.asset_path}{tag}")
        prompt = gen.prompt or gen.caption
        if prompt:
            lines.append(f"{indent}    {prompt[:80]}")
        for child in children.get(gen.entry_id, []):
            _emit(child, depth + 1)

    for top in children.get(None, []):
        _emit(top, 0)
    return "\n".join(lines)


def get_chain_sync(chain_root_id: str, **kwargs: Any) -> list[VisualGeneration]:
    return asyncio.run(get_chain(chain_root_id, **kwargs))


# ── recall ───────────────────────────────────────────────────────────────────


async def recall(
    query: str,
    *,
    limit: int = 5,
    store: VisualGenerationStore | None = None,
    memory_store: MemoryStore | None = None,
) -> tuple[
    list[tuple[str, float, VisualGeneration]],
    list[tuple[str, float, TechniqueLesson]],
    list[tuple[str, float, WorkflowTemplate]],
]:
    """Search own memory: generations (multimodal query-space), lessons, templates.

    Own-memory only by design — the three-collection retrieve_context already
    serves the draft/explain path. Returns hits, not answers.
    """
    store = store or VisualGenerationStore(memory_store or get_memory_store())
    await store.ensure_collection()
    gens, lessons, templates = await asyncio.gather(
        store.search_generations(query, exclude_pending=True, limit=limit),
        store.search_lessons(query, confirmed_only=False, limit=limit),
        store.search_templates(query, limit=limit),
    )
    return gens, lessons, templates


def render_recall(
    gens: list[tuple[str, float, VisualGeneration]],
    lessons: list[tuple[str, float, TechniqueLesson]],
    templates: list[tuple[str, float, WorkflowTemplate]],
) -> str:
    if not gens and not lessons and not templates:
        return "No results found."

    lines: list[str] = []

    if gens:
        lines.append(f"── Prior Generations ({len(gens)}) ──────────────────")
        for _id, score, gen in gens:
            prompt = gen.prompt or gen.caption
            lines.append(f"  [{score:.3f}] [{_reaction_label(gen)}] {prompt[:80]}")
            detail = _settings_summary(gen)
            if gen.asset_path:
                detail = f"{gen.asset_path} | {detail}"
            lines.append(f"      {detail}")
            if gen.chain_root_id and gen.chain_root_id != gen.entry_id:
                lines.append(f"      chain root: {gen.chain_root_id[:12]}")
        lines.append("")

    if lessons:
        lines.append(f"── Technique Lessons ({len(lessons)}) ──────────────────")
        for _id, score, lesson in lessons:
            conf = "" if lesson.confirmed else " (unconfirmed)"
            lines.append(
                f"  [{score:.3f}] [{lesson.valence}/{lesson.scope}]{conf} {lesson.statement[:80]}"
            )
        lines.append("")

    if templates:
        lines.append(f"── Workflow Templates ({len(templates)}) ──────────────────")
        for _id, score, tmpl in templates:
            lines.append(f"  [{score:.3f}] {tmpl.name} ({len(tmpl.slot_map)} slots) — {tmpl.descriptor[:60]}")

    return "\n".join(lines).rstrip("\n")


def recall_sync(query: str, **kwargs: Any) -> tuple[Any, Any, Any]:
    return asyncio.run(recall(query, **kwargs))
