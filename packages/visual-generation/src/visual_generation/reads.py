"""Read-only views shared by the CLI and the chat tool pack.

Each view is a typed fetch (stores are injected, never built here) plus a `render_*`
string builder. The Click commands print the render; the chat tools reuse both. Nothing
in this module writes to Qdrant, the registry, canon, or any file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from visual_generation.canon import CanonSubject, ProjectCanon
from visual_generation.constants import REACTIONS
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    ModelAsset,
    ProvenanceLeg,
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)
from visual_generation.store import VisualGenerationStore
from visual_generation.verify import VerifyReport

# ── digest ────────────────────────────────────────────────────────────────────


@dataclass
class Digest:
    project: str
    generations: list[VisualGeneration]       # oldest first
    lessons: list[TechniqueLesson]
    pending: list[VisualGeneration]
    limit: int


async def build_digest(project: str, store: VisualGenerationStore, *, limit: int = 8) -> Digest:
    await store.ensure_collection()
    gens = await store.list_generations(project=project)
    lessons = await store.list_lessons(confirmed_only=True)
    pending = [g for g in await store.list_pending() if g.project == project]
    return Digest(project=project, generations=gens, lessons=lessons, pending=pending, limit=limit)


def render_digest(d: Digest) -> str:
    gens, limit = d.generations, d.limit
    lines = [f"Digest for {d.project!r}"]
    lines.append(f"\n── Recent generations ({min(len(gens), limit)} of {len(gens)}) ──────────")
    if not gens:
        lines.append("  (none yet — draft → generate → report to build memory)")
    for g in gens[-limit:][::-1]:
        reaction = g.reaction.upper().replace("_", " ")
        rating = f" ★{g.rating}" if g.rating is not None else ""
        lines.append(f"  {g.entry_id[:12]}  [{reaction}{rating}]  {(g.caption or g.prompt or '')[:70]}")
    if d.pending:
        lines.append(f"\n── Awaiting your reaction ({len(d.pending)}) ───────────────")
        for g in d.pending:
            lines.append(f"  {(g.caption or g.prompt or '')[:66]}")
            lines.append(
                f"    agent visual-generation report {g.entry_id} "
                f"--reaction <{'|'.join(REACTIONS)}>"
            )
    if d.lessons:
        lines.append(f"\n── Confirmed technique lessons ({len(d.lessons)}) ──────────")
        for le in d.lessons:
            lines.append(f"  [{le.valence}/{le.scope}] {le.statement[:80]}")
    return "\n".join(lines)


# ── workflow templates ────────────────────────────────────────────────────────


@dataclass
class TemplateListing:
    templates: list[WorkflowTemplate]
    known_models: set[str]


async def list_templates(
    store: VisualGenerationStore,
    *,
    query: str = "",
    limit: int = 20,
    registry: ModelRegistry | None = None,
) -> TemplateListing:
    await store.ensure_collection()
    results = await store.search_templates(query or "workflow template", limit=limit)
    known = {a.name for a in (registry or ModelRegistry()).list_models()} if results else set()
    return TemplateListing(templates=[t for _id, _score, t in results], known_models=known)


def render_templates(listing: TemplateListing) -> str:
    if not listing.templates:
        return "No workflow templates registered."
    lines = [f"{len(listing.templates)} template(s):", ""]
    for tmpl in listing.templates:
        lines.append(f"  {tmpl.name}  ({len(tmpl.slot_map)} slots)")
        lines.append(f"    {tmpl.descriptor[:80]}")
        if tmpl.required_models:
            missing = [m for m in tmpl.required_models if m not in listing.known_models]
            status = "all present" if not missing else f"missing: {', '.join(missing)}"
            lines.append(f"    requires: {', '.join(tmpl.required_models)}  [{status}]")
    return "\n".join(lines)


# ── lessons ───────────────────────────────────────────────────────────────────


async def list_lessons(
    store: VisualGenerationStore,
    *,
    include_unconfirmed: bool = False,
    scope: str | None = None,
    valence: str | None = None,
) -> list[TechniqueLesson]:
    await store.ensure_collection()
    return await store.list_lessons(
        confirmed_only=not include_unconfirmed, scope=scope, valence=valence
    )


def render_lessons(lessons: list[TechniqueLesson]) -> str:
    if not lessons:
        return "No technique lessons."
    lines = [f"Technique lessons ({len(lessons)}):"]
    for le in lessons:
        conf = "" if le.confirmed else " (unconfirmed)"
        lines.append(f"  {le.entry_id}  [{le.valence}/{le.scope}]{conf} {le.statement[:80]}")
    return "\n".join(lines)


# ── models ────────────────────────────────────────────────────────────────────


def list_models(registry: ModelRegistry | None = None) -> list[ModelAsset]:
    return (registry or ModelRegistry()).list_models()


def render_models(assets: list[ModelAsset]) -> str:
    if not assets:
        return "No models registered. Run: agent visual-generation model sync --endpoint <url>"
    lines = [f"{len(assets)} registered asset(s):", ""]
    for a in sorted(assets, key=lambda x: (x.kind, x.name)):
        flags = []
        if a.identity_bearing:
            flags.append("identity-bearing")
        if not a.present_on_endpoint:
            flags.append("absent-from-last-sync")
        flag_str = f"  ({', '.join(flags)})" if flags else ""
        lines.append(f"  [{a.kind:10}] {a.name}  <{a.source}>{flag_str}")
    return "\n".join(lines)


# ── canon ─────────────────────────────────────────────────────────────────────


@dataclass
class CanonView:
    project: str
    path: Path
    subjects: list[CanonSubject]


def show_canon(project: str, canon: ProjectCanon | None = None) -> CanonView:
    canon = canon or ProjectCanon(project)
    return CanonView(project=project, path=canon.path, subjects=canon.load())


def render_subject(s: object, *, indent: str = "  ") -> list[str]:
    """One canon subject's fields as lines (shared by canon set/edit/show)."""
    lines = [f"{indent}aliases: {', '.join(s.aliases)}"]  # type: ignore[attr-defined]
    for label, attr in (
        ("id:      ", "id"),
        ("refs:    ", "reference_pack"),
        ("wardrobe:", "wardrobe"),
        ("hair:    ", "hair"),
        ("region:  ", "region"),
    ):
        value = getattr(s, attr, None)
        if value:
            lines.append(f"{indent}{label} {value}")
    lora = getattr(s, "lora", None)
    if lora:
        lines.append(f"{indent}lora:     {lora.name}@{lora.strength}")
    extras = getattr(s, "__pydantic_extra__", None) or {}
    if "locked" in extras or "forbid" in extras:
        lines.append(f"{indent}(legacy locked/forbid present — ignored)")
    return lines


def render_canon(view: CanonView) -> str:
    if not view.subjects:
        return f"No canon for {view.project!r} (looked at {view.path})."
    lines = [f"Canon for {view.project!r} ({len(view.subjects)} subject(s)):"]
    for s in view.subjects:
        lines.append("")
        lines.extend(render_subject(s, indent="  "))
    return "\n".join(lines)


# ── knowledge provenance / verify ─────────────────────────────────────────────


def render_provenance(legs: list[ProvenanceLeg]) -> str:
    """The deterministic 'what was surfaced' block (shared by draft/redraft/verify)."""
    if not legs:
        return ""
    lines = ["\n── Knowledge surfaced (deterministic) ───────────────"]
    for leg in legs:
        lines.append(
            f"  [{leg.tier}] {leg.label} ({leg.collection}): "
            f"{leg.count} hit(s), top {leg.top_score:.2f}"
        )
        for snip in leg.snippets:
            lines.append(f"      ↳ {snip}")
    return "\n".join(lines)


def render_verify(report: VerifyReport) -> str:
    lines = [f"Query: {report.query}"]
    if report.project:
        lines.append(f"Project: {report.project}")
    lines.append("\n── Collection sizes ─────────────────────────────────")
    for name, n in report.collection_counts.items():
        lines.append(f"  {name}: {'unreachable/absent' if n < 0 else n}")
    if report.legs:
        lines.append(render_provenance(report.legs))
    else:
        lines.append("\n⚠ Nothing surfaced for this query.")
    if report.gaps:
        lines.append("\n⚠ Gaps (knowledge that may be getting ignored):")
        for g in report.gaps:
            lines.append(f"  • {g}")
    else:
        lines.append("\n✓ No gaps flagged — relevant knowledge is reachable for this query.")
    return "\n".join(lines)
