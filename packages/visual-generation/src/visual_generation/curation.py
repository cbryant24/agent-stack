"""Curation writes, extracted from the CLI so the chat tools and the commands share one path.

Each function does exactly what the Click command did; the commands now call these. Anything
that confirms interactively splits into a lookup (read) and the write, so a caller can show the
exact item between the two. Rules for the evaluation-era lesson fields live here too, so no
caller can skip them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from visual_generation.batch_file import read_batch, remove_spec, write_batch
from visual_generation.canon import CanonSubject, ProjectCanon
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import (
    LoraRef,
    ModelAsset,
    TechniqueLesson,
    VisualSpec,
    WorkflowTemplate,
)
from visual_generation.reads import render_subject
from visual_generation.slot_inference import infer_slots
from visual_generation.store import VisualGenerationStore

# ── lessons ──────────────────────────────────────────────────────────────────

CONDITIONING_TOPICS = frozenset({"identity", "staging", "set"})
_CONDITIONING_WORDS = re.compile(
    r"\b(identity|likeness|same (?:character|person|puppet)|staging|blocking|set geometry|"
    r"set layout|landmarks?)\b", re.I,
)
VALIDATED_MIN_N = 5


class LessonRuleError(ValueError):
    """A lesson breaks a guardrail; the message says what to add."""


class NotALesson(ValueError):
    """The id belongs to a point that is not a technique_lesson (never deleted)."""


def lesson_rule_violations(
    *,
    statement: str,
    layer: str | None,
    topic: str | None,
    claim_level: str,
    evidence_n: int | None,
    falsification_test: str | None,
    held_out_eval_exists: bool,
) -> list[str]:
    out: list[str] = []
    about_conditioning = topic in CONDITIONING_TOPICS or bool(_CONDITIONING_WORDS.search(statement))
    if layer == "prompt" and about_conditioning and not (falsification_test or "").strip():
        out.append(
            "a prompt-layer lesson about identity, staging or set geometry needs a "
            "falsification_test (a defined counter-case that would disprove it); these failures "
            "are conditioning or asset problems until shown otherwise"
        )
    if claim_level == "validated":
        if (evidence_n or 0) < VALIDATED_MIN_N:
            out.append(f"'validated' needs evidence_n >= {VALIDATED_MIN_N}; this has {evidence_n or 0}")
        if not held_out_eval_exists:
            out.append(
                "'validated' needs a held-out evaluation id that exists in memory (a test the tuning "
                "loop never saw); until then the claim level is 'tuned'"
            )
    return out


async def add_lesson(
    statement: str,
    scope: str,
    valence: str,
    *,
    store: VisualGenerationStore,
    layer: str | None = None,
    topic: str | None = None,
    evidence_n: int | None = None,
    falsification_test: str | None = None,
    claim_level: str = "tuned",
    derived_from: Sequence[str] = (),
    held_out_eval_id: str | None = None,
) -> TechniqueLesson:
    """Store a CONFIRMED lesson (the caller's confirmation is what makes it so). The
    evaluation-era rules apply whenever the new fields are used."""
    held_out = False
    if claim_level == "validated" and held_out_eval_id:
        held_out = (await store.get_evaluation(held_out_eval_id)) is not None
    problems = lesson_rule_violations(
        statement=statement, layer=layer, topic=topic, claim_level=claim_level,
        evidence_n=evidence_n, falsification_test=falsification_test, held_out_eval_exists=held_out,
    )
    if problems:
        raise LessonRuleError("; ".join(problems))
    await store.ensure_collection()
    lesson = TechniqueLesson(
        statement=statement, scope=scope, valence=valence, confirmed=True,  # type: ignore[arg-type]
        layer=layer, evidence_n=evidence_n, falsification_test=falsification_test,
        claim_level=claim_level, derived_from=list(derived_from),  # type: ignore[arg-type]
    )
    await store.upsert_lesson(lesson)
    return lesson


async def lookup_lesson(entry_id: str, store: VisualGenerationStore) -> TechniqueLesson:
    """The lesson with this id. Raises NotALesson (a different kind of point) or LookupError."""
    await store.ensure_collection()
    le = await store.get_lesson(entry_id)       # raises ValueError(<memory_type>) for non-lessons
    if le is None:
        raise LookupError(f"No technique lesson with id {entry_id}.")
    return le


async def resolve_lesson_id(ref: str, store: VisualGenerationStore) -> str:
    """A full id, or a unique prefix of 8+ characters (as the retrospective cites them)."""
    ref = ref.strip()
    lessons = await store.list_lessons(confirmed_only=False)
    exact = [le.entry_id for le in lessons if le.entry_id == ref]
    if exact:
        return exact[0]
    hits = [le.entry_id for le in lessons if len(ref) >= 8 and le.entry_id.startswith(ref.lower())]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise LookupError(f"{ref!r} matches {len(hits)} lessons; use more characters")
    raise LookupError(f"no lesson matches {ref!r} (a full id or a unique 8+ character prefix)")


async def remove_lesson(
    entry_id: str, store: VisualGenerationStore, *, lesson: TechniqueLesson | None = None
) -> TechniqueLesson:
    le = lesson or await lookup_lesson(entry_id, store)
    await store.delete_lesson(entry_id)
    return le


# ── facts (user_knowledge; only UserKnowledgeStore writes there) ──────────────


async def add_fact(
    statement: str,
    domain: str,
    *,
    uks: Any,
    confidence: str = "high",
    source_ref: str = "manual:cli",
) -> str:
    """Add a documented platform fact through UserKnowledgeStore's propose then confirm path.
    The caller's confirmation (the chat gate, or running the command) is the confirm step.
    Returns the new entry id."""
    await uks.ensure_collection()
    draft = await uks.propose_entry(
        statement, domain, "user_verified", source_ref=source_ref, confidence=confidence
    )
    return str(await uks.confirm_entry(draft.draft_id))


# ── batch specs ──────────────────────────────────────────────────────────────


def find_batch_spec(path: Path, spec_id: str) -> tuple[Any, VisualSpec]:
    parsed = read_batch(path)
    target = next((s for s in parsed.specs if s.spec_id == spec_id), None)
    if target is None:
        known = ", ".join(s.spec_id for s in parsed.specs) or "(none)"
        raise LookupError(f"No spec with id {spec_id} in this batch. Known: {known}")
    return parsed, target


def remove_batch_spec(path: Path, spec_id: str) -> tuple[VisualSpec, int]:
    """Remove one spec; returns (the removed spec, how many remain). Others are untouched."""
    parsed, target = find_batch_spec(path, spec_id)
    remove_spec(parsed, spec_id)
    write_batch(parsed, path)
    return target, len(parsed.specs)


# ── models ───────────────────────────────────────────────────────────────────


def lookup_model(name: str, registry: ModelRegistry | None = None) -> ModelAsset:
    asset = (registry or ModelRegistry()).get_model(name)
    if asset is None:
        raise LookupError(f"No registered asset named {name!r}. See: agent visual-generation model list")
    return asset


def remove_model(name: str, registry: ModelRegistry | None = None) -> ModelAsset:
    registry = registry or ModelRegistry()
    asset = lookup_model(name, registry)
    registry.remove(name)
    return asset


# ── canon ────────────────────────────────────────────────────────────────────


@dataclass
class CanonChange:
    project: str
    path: Path
    before: CanonSubject | None
    after: CanonSubject | None
    existed: bool = False


def parse_lora(spec: str) -> LoraRef:
    """NAME[:STRENGTH] -> LoraRef (strength defaults to 1.0)."""
    name, _, strength = spec.partition(":")
    name = name.strip()
    if not name:
        raise ValueError("a lora needs a registry name (NAME[:STRENGTH])")
    if not strength:
        return LoraRef(name=name)
    try:
        return LoraRef(name=name, strength=float(strength))
    except ValueError as exc:
        raise ValueError(f"lora strength {strength!r} is not a number") from exc


def _matches(subject: CanonSubject, alias: str) -> bool:
    return alias.lower() in [a.lower() for a in subject.aliases]


def plan_canon_set(
    project: str, aliases: list[str], *, lora: LoraRef | None = None, id: str | None = None,
    reference_pack: str | None = None, wardrobe: str | None = None, hair: str | None = None,
    region: str | None = None, canon: ProjectCanon | None = None,
) -> CanonChange:
    """What `canon set` would do (REPLACES the whole subject), writing nothing."""
    canon = canon or ProjectCanon(project)
    if not aliases:
        raise ValueError("a canon subject needs at least one alias")
    before = next((s for s in canon.load() if _matches(s, aliases[0])), None)
    after = CanonSubject(aliases=aliases, lora=lora, id=id, reference_pack=reference_pack,
                         wardrobe=wardrobe, hair=hair, region=region)
    return CanonChange(project, canon.path, before, after, existed=before is not None)


def set_canon_subject(
    project: str, aliases: list[str], *, lora: LoraRef | None = None, id: str | None = None,
    reference_pack: str | None = None, wardrobe: str | None = None, hair: str | None = None,
    region: str | None = None, canon: ProjectCanon | None = None,
) -> CanonChange:
    canon = canon or ProjectCanon(project)
    change = plan_canon_set(project, aliases, lora=lora, id=id, reference_pack=reference_pack,
                            wardrobe=wardrobe, hair=hair, region=region, canon=canon)
    subject = canon.set_subject(aliases, lora=lora, id=id, reference_pack=reference_pack,
                                wardrobe=wardrobe, hair=hair, region=region)
    return CanonChange(project, canon.path, change.before, subject, existed=change.existed)


@dataclass
class CanonEdit:
    add_aliases: list[str] = field(default_factory=list)
    remove_aliases: list[str] = field(default_factory=list)
    lora: LoraRef | None = None
    clear_lora: bool = False
    id: str | None = None
    reference_pack: str | None = None
    wardrobe: str | None = None
    hair: str | None = None
    region: str | None = None

    def is_empty(self) -> bool:
        return not (self.add_aliases or self.remove_aliases or self.lora is not None or self.clear_lora
                    or any(v is not None for v in (self.id, self.reference_pack, self.wardrobe, self.hair, self.region)))

    def kwargs(self) -> dict[str, Any]:
        return dict(add_aliases=self.add_aliases, remove_aliases=self.remove_aliases, lora=self.lora,
                    clear_lora=self.clear_lora, id=self.id, reference_pack=self.reference_pack,
                    wardrobe=self.wardrobe, hair=self.hair, region=self.region)


def plan_canon_edit(
    project: str, selector: str, edit: CanonEdit, *, canon: ProjectCanon | None = None
) -> CanonChange:
    """What `canon edit` would do, writing nothing. Raises ValueError like the real edit."""
    canon = canon or ProjectCanon(project)
    before, after = canon.preview_update(selector, **edit.kwargs())
    return CanonChange(project, canon.path, before, after, existed=True)


def edit_canon_subject(
    project: str, selector: str, edit: CanonEdit, *, canon: ProjectCanon | None = None
) -> CanonChange:
    canon = canon or ProjectCanon(project)
    before, _ = canon.preview_update(selector, **edit.kwargs())
    after = canon.update_subject(selector, **edit.kwargs())
    return CanonChange(project, canon.path, before, after, existed=True)


def find_canon_subject(project: str, alias: str, canon: ProjectCanon | None = None) -> CanonSubject | None:
    return next((s for s in (canon or ProjectCanon(project)).load() if _matches(s, alias)), None)


def remove_canon_subject(project: str, alias: str, canon: ProjectCanon | None = None) -> CanonSubject | None:
    """Remove the matching subject; returns it, or None if nothing matched."""
    canon = canon or ProjectCanon(project)
    found = find_canon_subject(project, alias, canon)
    if found is None or not canon.remove(alias):
        return None
    return found


def render_canon_change(change: CanonChange) -> str:
    lines = [f"Canon for {change.project!r} ({change.path})"]
    lines.append("Before:" if change.before is not None else "Before: (no such subject)")
    if change.before is not None:
        lines.extend(render_subject(change.before, indent="  "))
    lines.append("After:")
    lines.extend(render_subject(change.after, indent="  ") if change.after is not None else ["  (removed)"])
    return "\n".join(lines)


# ── workflow templates ───────────────────────────────────────────────────────


@dataclass
class WorkflowPlan:
    name: str
    graph: dict[str, Any]
    slot_map: dict[str, dict[str, Any]]
    required_models: list[str]
    missing_models: list[str]
    notes: list[str]
    negative_suppressed: bool = False
    negative_candidate: dict[str, Any] | None = None


def load_graph_file(path: Path) -> dict[str, Any]:
    import json

    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if not isinstance(graph, dict) or not graph:
        raise ValueError(
            "Expected an API-format graph (node_id → {class_type, inputs}). "
            "Export with ComfyUI's 'Export Workflow (API)'."
        )
    return graph


def plan_workflow(graph: dict[str, Any], name: str, registry: ModelRegistry | None = None) -> WorkflowPlan:
    """Propose: infer the slot map and check required models. Writes nothing."""
    inferred = infer_slots(graph)
    known = {a.name for a in (registry or ModelRegistry()).list_models()}
    return WorkflowPlan(
        name=name, graph=graph, slot_map=dict(inferred.slot_map),
        required_models=list(inferred.required_models),
        missing_models=[m for m in inferred.required_models if m not in known],
        notes=list(inferred.notes), negative_suppressed=bool(inferred.negative_suppressed),
        negative_candidate=inferred.negative_candidate,
    )


def render_workflow_plan(plan: WorkflowPlan) -> str:
    lines = [f"── Inferred slots for '{plan.name}' ──────────────────────"]
    if plan.slot_map:
        lines += [f"  {slot:14} → node {t['node_id']}.{t['input_key']}" for slot, t in plan.slot_map.items()]
    else:
        lines.append("  (none inferred)")
    if plan.notes:
        lines.append("\nNotes:")
        lines += [f"  • {n}" for n in plan.notes]
    return "\n".join(lines)


async def commit_workflow(
    plan: WorkflowPlan, descriptor: str, store: VisualGenerationStore, *, add_negative: bool = False
) -> WorkflowTemplate:
    """Confirm: store the template. `add_negative` adds the traced negative slot if one was suppressed."""
    slot_map = dict(plan.slot_map)
    if add_negative and plan.negative_suppressed and plan.negative_candidate is not None:
        slot_map["negative"] = plan.negative_candidate
    template = WorkflowTemplate(
        name=plan.name, descriptor=descriptor, graph=plan.graph, slot_map=slot_map,
        required_models=plan.required_models,
    )
    await store.ensure_collection()
    await store.upsert_template(template)
    return template
