from __future__ import annotations

from typing import Literal

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from visual_generation import reads
from visual_generation.batch_file import read_batch_diagnosed
from visual_generation.chat.state import ChatState
from visual_generation.chat.tools._common import (
    fail,
    label_footer,
    ok,
    project_note,
    resolve_ref,
    resolver_for,
)
from visual_generation.inspect import (
    get_chain,
    get_generation,
    list_pending,
    recall,
    render_chain,
    render_generation,
    render_pending,
    render_recall,
)
from visual_generation.verify import verify_knowledge

Scope = Literal["prompt", "settings", "workflow", "model"]


class RecallArgs(BaseModel):
    query: str = Field(description="What to look for in your own memory (generations, lessons, templates).")
    limit: int = Field(default=5, ge=1, le=10, description="Max results per kind.")


class PendingArgs(BaseModel):
    all_projects: bool = Field(default=False, description="Include other projects' generations.")


class RefArgs(BaseModel):
    generation: str = Field(description="An attempt label like 'attempt-07', 'latest', or a generation id.")


class ChainArgs(BaseModel):
    generation: str = Field(description="Any generation in the chain (label or id); its whole chain is shown.")


class DigestArgs(BaseModel):
    project: str | None = Field(default=None, description="Project slug (defaults to the active project).")
    limit: int = Field(default=8, ge=1, le=30)


class ProjectArgs(BaseModel):
    project: str | None = Field(default=None, description="Project slug (defaults to the active project).")


class NoArgs(BaseModel):
    pass


class WorkflowArgs(BaseModel):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=50)


class LessonArgs(BaseModel):
    include_unconfirmed: bool = False
    scope: Scope | None = None
    valence: Literal["positive", "negative"] | None = None


class VerifyArgs(BaseModel):
    query: str = Field(description="A topic to check the knowledge legs for.")
    limit: int = Field(default=8, ge=1, le=20)


def make_read_tools(state: ChatState) -> list[ToolSpec]:
    note = project_note(state)

    async def recall_tool(a: RecallArgs) -> ToolResult:
        store, _ = state.stores()
        gens, lessons, templates = await recall(a.query, limit=a.limit, store=store)
        resolver = await resolver_for(state)
        text = render_recall(gens, lessons, templates) + label_footer(resolver, [g.entry_id for _, _, g in gens])
        return ok(text, data={
            "generation_ids": [g.entry_id for _, _, g in gens],
            "lesson_ids": [le.entry_id for _, _, le in lessons],
            "template_names": [t.name for _, _, t in templates],
        })

    async def pending_tool(a: PendingArgs) -> ToolResult:
        store, _ = state.stores()
        gens = await list_pending(store=store)
        if state.project and not a.all_projects:
            gens = [g for g in gens if g.project == state.project]
        resolver = await resolver_for(state)
        # KI-4: a rendered generation stays 'pending' until it is reacted to, by design;
        # this list is "awaiting a reaction", not "failed".
        return ok(render_pending(gens) + label_footer(resolver, [g.entry_id for g in gens]),
                  data={"generation_ids": [g.entry_id for g in gens]})

    async def chain_tool(a: ChainArgs) -> ToolResult:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        store, _ = state.stores()
        gen = await get_generation(gen_id, store=store)
        root = gen.chain_root_id if gen else gen_id
        chain = await get_chain(root, store=store)
        resolver = await resolver_for(state)
        return ok(render_chain(root, chain) + label_footer(resolver, [g.entry_id for g in chain]),
                  data={"chain_root_id": root, "generation_ids": [g.entry_id for g in chain]})

    async def inspect_tool(a: RefArgs) -> ToolResult:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        store, _ = state.stores()
        gen = await get_generation(gen_id, store=store)
        resolver = await resolver_for(state)
        head = f"{resolver.display(gen_id)}\n" if resolver.name_of(gen_id) else ""
        return ok(head + render_generation(gen, gen_id), data={"generation_id": gen_id})

    async def digest_tool(a: DigestArgs) -> ToolResult:
        slug = a.project or state.project
        if not slug:
            return fail("No project: start the chat with --project <slug> or pass `project`.")
        store, _ = state.stores()
        d = await reads.build_digest(slug, store, limit=a.limit)
        resolver = await resolver_for(state, slug)
        return ok(reads.render_digest(d) + label_footer(resolver, [g.entry_id for g in d.generations]),
                  data={"project": slug, "generations": len(d.generations), "pending": len(d.pending)})

    async def batch_list_tool(a: ProjectArgs) -> ToolResult:
        try:
            path = state.batch_path(a.project)
        except ValueError as e:
            return fail(str(e))
        if not path.is_file():
            return ok(f"No batch file yet at {path}. `draft` creates it.", data={"specs": [], "issues": []})
        batch, issues = read_batch_diagnosed(path)
        lines = [f"{len(batch.specs)} spec(s) in {path}:", ""]
        for s in batch.specs:
            title = s.heading or (s.prompt[:60] if s.prompt else "(untitled)")
            lines.append(f"  {s.spec_id}  [{s.workflow_ref or 'no template'}]  {title}")
        if issues:
            lines.append("\n⚠ Metadata problems (these specs' settings fell back to defaults; fix the file):")
            lines.extend(f"  • {i.heading}: {i.problem}" for i in issues)
        return ok("\n".join(lines), artifacts=[str(path)], data={
            "specs": [s.spec_id for s in batch.specs],
            "issues": [{"heading": i.heading, "problem": i.problem} for i in issues],
        })

    async def model_tool(a: NoArgs) -> ToolResult:
        assets = reads.list_models()
        return ok(reads.render_models(assets), data={"count": len(assets)})

    async def workflow_tool(a: WorkflowArgs) -> ToolResult:
        store, _ = state.stores()
        listing = await reads.list_templates(store, query=a.query, limit=a.limit)
        return ok(reads.render_templates(listing), data={"templates": [t.name for t in listing.templates]})

    async def lesson_tool(a: LessonArgs) -> ToolResult:
        store, _ = state.stores()
        lessons = await reads.list_lessons(
            store, include_unconfirmed=a.include_unconfirmed, scope=a.scope, valence=a.valence)
        return ok(reads.render_lessons(lessons), data={"lesson_ids": [le.entry_id for le in lessons]})

    async def canon_tool(a: ProjectArgs) -> ToolResult:
        slug = a.project or state.project
        if not slug:
            return fail("No project: start the chat with --project <slug> or pass `project`.")
        view = reads.show_canon(slug)
        return ok(reads.render_canon(view), data={"subjects": len(view.subjects)})

    async def verify_tool(a: VerifyArgs) -> ToolResult:
        store, ms = state.stores()
        report = await verify_knowledge(a.query, store, ms, project=state.project, limit=a.limit)
        return ok(reads.render_verify(report), data={"gaps": report.gaps})

    R = EffectClass.READ
    return [
        ToolSpec(name="recall", effect=R, input_model=RecallArgs, handler=recall_tool,
                 description="Search your own memory: prior generations, technique lessons, workflow templates. "
                             "Returns hits, not answers. " + note),
        ToolSpec(name="review_pending", effect=R, input_model=PendingArgs, handler=pending_tool,
                 description="List generations awaiting a reaction. 'Pending' means not yet reacted to, "
                             "not failed: a rendered image stays pending until reported. " + note),
        ToolSpec(name="chain_show", effect=R, input_model=ChainArgs, handler=chain_tool,
                 description="Show the lineage chain (parent -> revisions) containing a generation."),
        ToolSpec(name="inspect_generation", effect=R, input_model=RefArgs, handler=inspect_tool,
                 description="Full detail of one generation: prompt, settings, lineage, reaction, notes."),
        ToolSpec(name="digest", effect=R, input_model=DigestArgs, handler=digest_tool,
                 description="'Where did I leave off': recent generations with reactions, pending items, "
                             "confirmed lessons. " + note),
        ToolSpec(name="batch_list", effect=R, input_model=ProjectArgs, handler=batch_list_tool,
                 description="List the specs in the project's batch file, and report any whose metadata "
                             "could not be parsed. " + note),
        ToolSpec(name="model_list", effect=R, input_model=NoArgs, handler=model_tool,
                 description="List registered checkpoints/LoRAs (identity-bearing and presence shown)."),
        ToolSpec(name="workflow_list", effect=R, input_model=WorkflowArgs, handler=workflow_tool,
                 description="List registered workflow templates and whether their required models are present."),
        ToolSpec(name="lesson_list", effect=R, input_model=LessonArgs, handler=lesson_tool,
                 description="List technique lessons (confirmed only by default)."),
        ToolSpec(name="canon_show", effect=R, input_model=ProjectArgs, handler=canon_tool,
                 description="Show a project's canon subjects (identity locks). " + note),
        ToolSpec(name="knowledge_verify", effect=R, input_model=VerifyArgs, handler=verify_tool,
                 description="Prove what the knowledge legs surface for a topic and flag gaps. Read-only."),
    ]
