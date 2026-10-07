"""Write tools: every one goes through the executor's gate, and none calls a store write method itself.

Memory writes call library functions (`record_evaluation`, `add_lesson`, ...); destructive ones
show the exact item first. A `precheck` refuses a call that would fail (a broken rule, a missing
item) before the director is asked to approve it, and an async `preview` shows exactly what will
be written or removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from agent_runtime import UserKnowledgeStore
from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from visual_generation.chat.interpretation import (
    InterpretationError,
    build_evaluation,
    gather_context,
    render_entry,
    render_lesson,
)
from visual_generation.chat.schemas import EvaluationInput, LessonInput
from visual_generation.chat.state import ChatState, evaluation_key, lesson_key
from visual_generation.chat.tools._common import fail, ok, project_note, resolve_ref, resolver_for
from visual_generation.constants import POSITIVE_REACTIONS
from visual_generation.curation import (
    CanonEdit,
    LessonRuleError,
    add_fact,
    add_lesson,
    commit_workflow,
    edit_canon_subject,
    find_batch_spec,
    find_canon_subject,
    load_graph_file,
    lookup_lesson,
    lookup_model,
    parse_lora,
    plan_canon_edit,
    plan_canon_set,
    plan_workflow,
    remove_batch_spec,
    remove_canon_subject,
    remove_lesson,
    remove_model,
    render_canon_change,
    render_workflow_plan,
    resolve_lesson_id,
    set_canon_subject,
)
from visual_generation.evaluation import (
    EvaluationPartialWrite,
    execution_truth_verified_since,
    list_evaluations as _list_evaluations,
    record_evaluation as _record_evaluation,
    render_evaluations,
)
from visual_generation.reads import render_subject
from visual_generation.report import report as _report

Reaction = Literal["loved", "liked", "liked_with_changes", "disliked", "render_failed"]


class ReportArgs(BaseModel):
    generation: str = Field(description="The attempt: a label like 'attempt-07' or an id.")
    reaction: Reaction
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, description="Action-oriented: what to change next time.")
    context: str | None = Field(default=None, description="Why the director reacted this way.")


class FactArgs(BaseModel):
    statement: str
    domain: Literal["comfyui_mechanics", "runpod_mechanics"]
    confidence: Literal["high", "medium", "low"] = "high"


class LessonRmArgs(BaseModel):
    lesson: str = Field(description="The lesson's id, or a unique prefix of 8+ characters.")


class BatchRmArgs(BaseModel):
    spec_id: str
    project: str | None = None


class ModelRmArgs(BaseModel):
    name: str = Field(description="Registry name. Registry only: the file on the pod is untouched.")


class CanonRmArgs(BaseModel):
    alias: str = Field(description="Any alias of the subject to remove.")
    project: str | None = None


class CanonSetArgs(BaseModel):
    aliases: list[str] = Field(min_length=1, description="aliases[0] is the key. REPLACES the whole subject.")
    id: str | None = None
    reference_pack: str | None = None
    wardrobe: str | None = None
    hair: str | None = None
    region: str | None = None
    lora: str | None = Field(default=None, description="NAME[:STRENGTH]; NAME is a registry name.")
    project: str | None = None


class CanonEditArgs(BaseModel):
    subject: str = Field(description="Any alias of the subject to edit.")
    add_aliases: list[str] = Field(default_factory=list)
    remove_aliases: list[str] = Field(default_factory=list)
    id: str | None = Field(default=None, description="Empty string clears it.")
    reference_pack: str | None = None
    wardrobe: str | None = None
    hair: str | None = None
    region: str | None = None
    lora: str | None = Field(default=None, description="NAME[:STRENGTH]")
    clear_lora: bool = False
    project: str | None = None


class WorkflowArgs(BaseModel):
    graph_path: str = Field(description="An API-format ComfyUI graph exported from the UI.")
    name: str | None = Field(default=None, description="Default: the file stem.")
    descriptor: str | None = Field(default=None, description="What the template serves (embedded for retrieval).")
    add_negative_slot: bool = False


class ListEvaluationsArgs(BaseModel):
    generation: str | None = Field(default=None, description="Evaluations of this attempt (label or id).")
    chain_of: str | None = Field(default=None, description="Evaluations in the whole chain containing this attempt.")


def _json(d: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in d.items() if v not in (None, [], "", False)}, indent=2, default=str)


def make_write_tools(state: ChatState) -> list[ToolSpec]:
    note = project_note(state)

    def project_of(p: str | None) -> str | None:
        return p or state.project

    # ── report ────────────────────────────────────────────────────────────────

    async def report_preview(a: ReportArgs) -> str:
        gen_id, _ = await resolve_ref(state, a.generation)
        resolver = await resolver_for(state)
        target = resolver.display(gen_id) if gen_id else f"{a.generation} (unresolved)"
        lines = [f"Record reaction on {target}: {a.reaction}" + (f" ★{a.rating}" if a.rating else "")]
        if a.notes:
            lines.append(f"notes: {a.notes}")
        if a.context:
            lines.append(f"context: {a.context}")
        if a.rating is not None and a.reaction not in POSITIVE_REACTIONS:
            lines.append("note: ratings are meaningful for positive reactions; recording it anyway")
        return "\n".join(lines)

    async def report_precheck(a: ReportArgs) -> str | None:
        gen_id, why = await resolve_ref(state, a.generation)
        return None if gen_id else f"Could not resolve {a.generation!r}: {why}"

    async def report_tool(a: ReportArgs) -> ToolResult:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}")
        store, _ = state.stores()
        gen = await _report(gen_id, a.reaction, rating=a.rating, notes=a.notes, context=a.context, store=store)
        if gen is None:
            return fail(f"No generation with id {gen_id}.")
        return ok(f"Recorded: {gen_id} -> {a.reaction}" + (f" ★{a.rating}" if a.rating else ""),
                  data={"gen_id": gen_id, "reaction": a.reaction})

    # ── evaluation ────────────────────────────────────────────────────────────

    async def eval_precheck(a: EvaluationInput) -> str | None:
        try:
            build_evaluation(a, await gather_context(state, a))
        except InterpretationError as e:
            return str(e)
        return None

    async def eval_preview(a: EvaluationInput) -> str:
        ctx = await gather_context(state, a)
        entry, questions = build_evaluation(a, ctx)
        lines = [render_entry(entry, ctx.resolver)]
        if entry.agent_status == "unresolved" and a.agent_status != "unresolved":
            since = execution_truth_verified_since()
            lines.append(f"  (agent_status set to unresolved automatically: this generation predates the "
                         f"verified-execution date, {since or 'which is not set'})")
        lines += [f"  open question: {q}" for q in questions]
        lines.append("Also sets the generation's reaction (what `report` does).")
        return "\n".join(lines)

    async def eval_tool(a: EvaluationInput) -> ToolResult:
        try:
            ctx = await gather_context(state, a)
            entry, questions = build_evaluation(a, ctx)
        except InterpretationError as e:
            return fail(str(e))
        store, _ = state.stores()
        try:
            written = await _record_evaluation(entry, store=store)
        except EvaluationPartialWrite as e:
            state.written(evaluation_key(entry.entry_id))
            return fail(str(e), data={"evaluation_id": entry.entry_id, "gen_id": entry.gen_id, "partial": True})
        except (LookupError, ValueError) as e:
            return fail(str(e))
        state.written(evaluation_key(written.entry_id))
        return ok(
            f"Wrote evaluation {written.entry_id} for {ctx.resolver.display(written.gen_id)} "
            f"({written.reaction}); the generation's reaction is set. agent_status={written.agent_status}.",
            data={"evaluation_id": written.entry_id, "gen_id": written.gen_id,
                  "chain_root_id": written.chain_root_id, "agent_status": written.agent_status,
                  "open_questions": questions},
        )

    # ── lessons ───────────────────────────────────────────────────────────────

    async def lesson_precheck(a: LessonInput) -> str | None:
        from visual_generation.curation import lesson_rule_violations

        store, _ = state.stores()
        held = bool(a.held_out_eval_id and await store.get_evaluation(a.held_out_eval_id) is not None)
        problems = lesson_rule_violations(
            statement=a.statement, layer=a.layer.value, topic=a.topic, claim_level=a.claim_level,
            evidence_n=a.evidence_n, falsification_test=a.falsification_test, held_out_eval_exists=held)
        return "; ".join(problems) or None

    async def lesson_tool(a: LessonInput) -> ToolResult:
        store, _ = state.stores()
        try:
            le = await add_lesson(
                a.statement, a.scope, a.valence, store=store, layer=a.layer.value, topic=a.topic,
                evidence_n=a.evidence_n, falsification_test=a.falsification_test,
                claim_level=a.claim_level, derived_from=a.source_eval_ids, held_out_eval_id=a.held_out_eval_id)
        except LessonRuleError as e:
            return fail(str(e))
        state.written(lesson_key(a.statement))
        return ok(f"Added lesson {le.entry_id}: [{a.valence}/{a.scope}] {a.statement[:80]}",
                  data={"lesson_id": le.entry_id, "claim_level": le.claim_level})

    async def fact_tool(a: FactArgs) -> ToolResult:
        _, ms = state.stores()
        entry_id = await add_fact(a.statement, a.domain, uks=UserKnowledgeStore(ms),
                                  confidence=a.confidence, source_ref="manual:chat")
        return ok(f"Added fact to {a.domain}: {a.statement[:80]} (entry {entry_id})", data={"entry_id": entry_id})

    # ── destructive removals ──────────────────────────────────────────────────

    async def lesson_rm_precheck(a: LessonRmArgs) -> str | None:
        store, _ = state.stores()
        try:
            await lookup_lesson(await resolve_lesson_id(a.lesson, store), store)
        except (LookupError, ValueError) as e:
            return str(e)
        return None

    async def lesson_rm_preview(a: LessonRmArgs) -> str:
        store, _ = state.stores()
        le = await lookup_lesson(await resolve_lesson_id(a.lesson, store), store)
        return (f"Delete lesson {le.entry_id}\n  [{le.valence}/{le.scope}] {le.statement}\n"
                f"  claim={le.claim_level} layer={le.layer} confirmed={le.confirmed}")

    async def lesson_rm_tool(a: LessonRmArgs) -> ToolResult:
        store, _ = state.stores()
        try:
            full = await resolve_lesson_id(a.lesson, store)
            le = await remove_lesson(full, store)
        except (LookupError, ValueError) as e:
            return fail(str(e))
        return ok(f"Removed lesson {le.entry_id}: {le.statement[:80]}",
                  data={"lesson_id": le.entry_id, "statement": le.statement})

    def batch_path_for(project: str | None) -> Path:
        return state.batch_path(project)

    async def batch_rm_precheck(a: BatchRmArgs) -> str | None:
        try:
            find_batch_spec(batch_path_for(a.project), a.spec_id)
        except (LookupError, ValueError, OSError) as e:
            return str(e)
        return None

    async def batch_rm_preview(a: BatchRmArgs) -> str:
        path = batch_path_for(a.project)
        _, spec = find_batch_spec(path, a.spec_id)
        return f"Remove spec {spec.spec_id} from {path}\n  {spec.heading or '(untitled)'}\n  {spec.prompt[:200]}"

    async def batch_rm_tool(a: BatchRmArgs) -> ToolResult:
        try:
            spec, remaining = remove_batch_spec(batch_path_for(a.project), a.spec_id)
        except (LookupError, ValueError, OSError) as e:
            return fail(str(e))
        return ok(f"Removed spec {spec.spec_id}. {remaining} spec(s) remain.",
                  data={"spec_id": spec.spec_id, "remaining": remaining})

    async def model_rm_precheck(a: ModelRmArgs) -> str | None:
        try:
            lookup_model(a.name)
        except LookupError as e:
            return str(e)
        return None

    async def model_rm_preview(a: ModelRmArgs) -> str:
        asset = lookup_model(a.name)
        flag = " [identity-bearing]" if asset.identity_bearing else ""
        return f"Unregister [{asset.kind}] {asset.name}{flag} (registry only; the pod file is untouched)"

    async def model_rm_tool(a: ModelRmArgs) -> ToolResult:
        try:
            asset = remove_model(a.name)
        except LookupError as e:
            return fail(str(e))
        return ok(f"Unregistered {asset.name}.", data={"name": asset.name})

    async def canon_rm_precheck(a: CanonRmArgs) -> str | None:
        slug = project_of(a.project)
        if not slug:
            return "no project: start the chat with --project <slug> or pass `project`"
        return None if find_canon_subject(slug, a.alias) else f"No canon subject matching {a.alias!r} in {slug!r}."

    async def canon_rm_preview(a: CanonRmArgs) -> str:
        slug = project_of(a.project) or ""
        found = find_canon_subject(slug, a.alias)
        assert found is not None
        return f"Remove canon subject from {slug!r}:\n" + "\n".join(render_subject(found, indent="  "))

    async def canon_rm_tool(a: CanonRmArgs) -> ToolResult:
        slug = project_of(a.project)
        if not slug:
            return fail("no project: start the chat with --project <slug> or pass `project`")
        removed = remove_canon_subject(slug, a.alias)
        if removed is None:
            return fail(f"No canon subject matching {a.alias!r} in {slug!r}.")
        return ok(f"Removed canon subject {removed.aliases[0]!r} from {slug!r}.", data={"alias": removed.aliases[0]})

    # ── canon set / edit ──────────────────────────────────────────────────────

    def canon_edit_of(a: CanonEditArgs) -> CanonEdit:
        return CanonEdit(add_aliases=a.add_aliases, remove_aliases=a.remove_aliases,
                         lora=parse_lora(a.lora) if a.lora else None, clear_lora=a.clear_lora, id=a.id,
                         reference_pack=a.reference_pack, wardrobe=a.wardrobe, hair=a.hair, region=a.region)

    def canon_set_plan(a: CanonSetArgs):  # type: ignore[no-untyped-def]
        slug = project_of(a.project)
        if not slug:
            raise ValueError("no project: start the chat with --project <slug> or pass `project`")
        return slug, plan_canon_set(
            slug, a.aliases, lora=parse_lora(a.lora) if a.lora else None, id=a.id,
            reference_pack=a.reference_pack, wardrobe=a.wardrobe, hair=a.hair, region=a.region)

    async def canon_set_precheck(a: CanonSetArgs) -> str | None:
        try:
            canon_set_plan(a)
        except ValueError as e:
            return str(e)
        return None

    async def canon_set_preview(a: CanonSetArgs) -> str:
        _, plan = canon_set_plan(a)
        text = render_canon_change(plan)
        return text + ("\nThis REPLACES the whole subject (use canon_edit for one field)." if plan.existed else "")

    async def canon_set_tool(a: CanonSetArgs) -> ToolResult:
        try:
            slug, _ = canon_set_plan(a)
            change = set_canon_subject(
                slug, a.aliases, lora=parse_lora(a.lora) if a.lora else None, id=a.id,
                reference_pack=a.reference_pack, wardrobe=a.wardrobe, hair=a.hair, region=a.region)
        except ValueError as e:
            return fail(str(e))
        verb = "Replaced" if change.existed else "Set"
        return ok(f"{verb} canon subject {a.aliases[0]!r} for {slug!r} ({change.path}).", data={"path": str(change.path)})

    def canon_edit_plan(a: CanonEditArgs):  # type: ignore[no-untyped-def]
        slug = project_of(a.project)
        if not slug:
            raise ValueError("no project: start the chat with --project <slug> or pass `project`")
        edit = canon_edit_of(a)
        if edit.is_empty():
            raise ValueError("Nothing to edit: pass at least one change.")
        return slug, edit, plan_canon_edit(slug, a.subject, edit)

    async def canon_edit_precheck(a: CanonEditArgs) -> str | None:
        try:
            canon_edit_plan(a)
        except ValueError as e:
            return str(e)
        return None

    async def canon_edit_preview(a: CanonEditArgs) -> str:
        return render_canon_change(canon_edit_plan(a)[2])

    async def canon_edit_tool(a: CanonEditArgs) -> ToolResult:
        try:
            slug, edit, _ = canon_edit_plan(a)
            change = edit_canon_subject(slug, a.subject, edit)
        except ValueError as e:
            return fail(str(e))
        return ok(f"Edited canon subject {a.subject!r} for {slug!r}.", data={"path": str(change.path)})

    # ── workflow register ─────────────────────────────────────────────────────

    def workflow_plan(a: WorkflowArgs):  # type: ignore[no-untyped-def]
        path = Path(a.graph_path).expanduser()
        if not path.is_file():
            raise ValueError(f"No such file: {a.graph_path}")
        return path, plan_workflow(load_graph_file(path), a.name or path.stem)

    async def workflow_precheck(a: WorkflowArgs) -> str | None:
        try:
            workflow_plan(a)
        except ValueError as e:
            return str(e)
        return None

    async def workflow_preview(a: WorkflowArgs) -> str:
        path, plan = workflow_plan(a)
        lines = [render_workflow_plan(plan), f"\nDescriptor: {a.descriptor or plan.name}"]
        if plan.negative_suppressed and plan.negative_candidate is not None:
            lines.append("A negative slot was suppressed; " + ("it WILL be added." if a.add_negative_slot else "it will NOT be added."))
        if plan.missing_models:
            lines.append("Not in the model registry: " + ", ".join(plan.missing_models))
        return "\n".join(lines)

    async def workflow_tool(a: WorkflowArgs) -> ToolResult:
        try:
            _, plan = workflow_plan(a)
        except ValueError as e:
            return fail(str(e))
        store, _ = state.stores()
        tmpl = await commit_workflow(plan, a.descriptor or plan.name, store, add_negative=a.add_negative_slot)
        return ok(f"Registered template {tmpl.name!r} ({tmpl.entry_id[:12]}) with {len(tmpl.slot_map)} slot(s).",
                  data={"template": tmpl.name, "slots": len(tmpl.slot_map), "missing_models": plan.missing_models})

    # ── read: list_evaluations ────────────────────────────────────────────────

    async def list_eval_tool(a: ListEvaluationsArgs) -> ToolResult:
        store, _ = state.stores()
        gen_id = chain_root = None
        if a.generation:
            gen_id, why = await resolve_ref(state, a.generation)
            if gen_id is None:
                return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        if a.chain_of:
            cid, why = await resolve_ref(state, a.chain_of)
            if cid is None:
                return fail(f"Could not resolve {a.chain_of!r}: {why}", data={"open_questions": [why]})
            g = await store.get_generation(cid)
            chain_root = g.chain_root_id if g else cid
        project = None if (gen_id or chain_root) else state.project
        entries = await _list_evaluations(store, gen_id=gen_id, chain_root_id=chain_root, project=project)
        return ok(render_evaluations(entries), data={"evaluation_ids": [e.entry_id for e in entries]})

    M, D = EffectClass.MEMORY_WRITE, EffectClass.DESTRUCTIVE_LOCAL
    return [
        ToolSpec(name="report", effect=M, input_model=ReportArgs, handler=report_tool,
                 preview=report_preview, precheck=report_precheck,
                 description="Record the director's reaction to a rendered generation (flips it from pending). "
                             "Asks the director first."),
        ToolSpec(name="record_evaluation", effect=M, input_model=EvaluationInput, handler=eval_tool,
                 preview=eval_preview, precheck=eval_precheck,
                 description="Write the evaluation from propose_interpretation (pass the same fields) and set the "
                             "generation's reaction. The director sees the full record and confirms, edits or defers. "
                             + note),
        ToolSpec(name="add_lesson", effect=M, input_model=LessonInput, handler=lesson_tool,
                 preview=lambda a: "Add technique lesson:\n" + render_lesson(a), precheck=lesson_precheck,
                 description="Add ONE confirmed technique lesson (offer them one at a time; never auto-confirm). "
                             "Rules: a prompt-layer lesson about identity/staging/set needs a falsification_test; "
                             "'validated' needs evidence_n >= 5 and an existing held-out evaluation id."),
        ToolSpec(name="add_fact", effect=M, input_model=FactArgs, handler=fact_tool,
                 preview=lambda a: f"Add documented fact to {a.domain} ({a.confidence}):\n  {a.statement}",
                 description="Add a documented platform fact to user_knowledge (comfyui or runpod mechanics)."),
        ToolSpec(name="canon_set", effect=M, input_model=CanonSetArgs, handler=canon_set_tool,
                 preview=canon_set_preview, precheck=canon_set_precheck,
                 description="Set a canon subject (REPLACES the whole subject). The director sees the diff. " + note),
        ToolSpec(name="canon_edit", effect=M, input_model=CanonEditArgs, handler=canon_edit_tool,
                 preview=canon_edit_preview, precheck=canon_edit_precheck,
                 description="Edit one field of a canon subject without restating the rest. The director sees the diff. " + note),
        ToolSpec(name="workflow_register", effect=M, input_model=WorkflowArgs, handler=workflow_tool,
                 preview=workflow_preview, precheck=workflow_precheck,
                 description="Register an exported API-format ComfyUI graph as a workflow template. The director "
                             "sees the proposed slot map first."),
        ToolSpec(name="lesson_rm", effect=D, input_model=LessonRmArgs, handler=lesson_rm_tool,
                 preview=lesson_rm_preview, precheck=lesson_rm_precheck,
                 description="Delete one technique lesson (id or unique 8+ character prefix). The director sees it first."),
        ToolSpec(name="batch_rm", effect=D, input_model=BatchRmArgs, handler=batch_rm_tool,
                 preview=batch_rm_preview, precheck=batch_rm_precheck,
                 description="Remove one spec from the project's batch file. " + note),
        ToolSpec(name="model_rm", effect=D, input_model=ModelRmArgs, handler=model_rm_tool,
                 preview=model_rm_preview, precheck=model_rm_precheck,
                 description="Unregister a model/LoRA from the registry (the pod file is untouched)."),
        ToolSpec(name="canon_rm", effect=D, input_model=CanonRmArgs, handler=canon_rm_tool,
                 preview=canon_rm_preview, precheck=canon_rm_precheck,
                 description="Remove a canon subject. The director sees it first. " + note),
        ToolSpec(name="list_evaluations", effect=EffectClass.READ, input_model=ListEvaluationsArgs,
                 handler=list_eval_tool,
                 description="List evaluations for an attempt, for a whole chain, or for the active project. " + note),
    ]
