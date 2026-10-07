from __future__ import annotations

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from music_curation.chat.state import ChatState
from music_curation.chat.tools._common import fail, ok, resolve_ref
from music_curation.reads import render_chain, render_pending, render_recall
from music_curation.retrieval import retrieve_context


class RecallArgs(BaseModel):
    query: str = Field(description="What to look for: prior generations, taste lessons, Suno facts, tutorial notes.")
    limit: int = Field(default=5, ge=1, le=10, description="Max results per kind.")


class NoArgs(BaseModel):
    pass


class ChainArgs(BaseModel):
    generation: str = Field(description="Any generation in the chain (id, 8+ character prefix, or 'latest').")


def make_read_tools(state: ChatState) -> list[ToolSpec]:
    async def recall_tool(a: RecallArgs) -> ToolResult:
        store, memory, _ = state.stores()
        await store.ensure_collection()
        ctx = await retrieve_context(a.query, store, memory, generation_limit=a.limit, taste_limit=a.limit,
                                     suno_fact_limit=a.limit)
        gens = [g for _, g in ctx.prior_generations]
        state.remember(gens)
        ids = "".join(f"\n  {g.suggested_track_title or '(untitled)'}: {g.entry_id}" for g in gens)
        return ok(render_recall(ctx) + (f"\n\nGeneration ids:{ids}" if ids else ""), data={
            "generation_ids": [g.entry_id for g in gens], "taste_lessons": len(ctx.taste_lessons),
            "suno_facts": len(ctx.suno_facts), "tutorial_hits": len(ctx.tutorial_hits),
        })

    async def pending_tool(a: NoArgs) -> ToolResult:
        store, _, _ = state.stores()
        await store.ensure_collection()
        pending = await store.list_pending()
        state.remember(pending)
        return ok(render_pending(pending), data={"generation_ids": [g.entry_id for g in pending]})

    async def chain_tool(a: ChainArgs) -> ToolResult:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}", data={"open_questions": [why]})
        store, _, _ = state.stores()
        gen = await store.get_generation(gen_id)
        root = (gen.chain_root_id if gen else "") or gen_id
        chain = await store.get_chain(root)
        state.remember(chain)
        return ok(render_chain(root, chain), data={"chain_root_id": root, "generation_ids": [g.entry_id for g in chain]})

    R = EffectClass.READ
    return [
        ToolSpec(name="recall", effect=R, input_model=RecallArgs, handler=recall_tool,
                 description="Search memory: prior generations with their reactions, taste lessons, Suno facts and "
                             "tutorial notes. Returns hits, not answers."),
        ToolSpec(name="review_pending", effect=R, input_model=NoArgs, handler=pending_tool,
                 description="List generated prompts that have no reaction yet. 'Pending' means the director has not "
                             "reported on it, not that it failed."),
        ToolSpec(name="chain_show", effect=R, input_model=ChainArgs, handler=chain_tool,
                 description="Show the evolution chain (original prompt and its revisions) containing a generation."),
    ]
