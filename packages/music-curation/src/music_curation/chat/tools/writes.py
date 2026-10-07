"""Write tools: every one goes through the executor's gate, and none calls a store write method
itself. They call the library functions the CLI calls (`music_curation.curation`)."""

from __future__ import annotations

from typing import Literal

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel

from music_curation.chat.schemas import UNHEARD, ReportArgs, TasteInput
from music_curation.chat.state import ChatState, reaction_key, taste_key
from music_curation.chat.tools._common import fail, ok, resolve_ref, title_of
from music_curation.constants import POSITIVE_REACTIONS
from music_curation.curation import add_fact, add_taste, record_reaction


class FactArgs(BaseModel):
    statement: str
    domain: str = "suno_mechanics"
    confidence: Literal["high", "medium", "low"] = "high"


def make_write_tools(state: ChatState) -> list[ToolSpec]:
    async def report_precheck(a: ReportArgs) -> str | None:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return f"Could not resolve {a.generation!r}: {why}"
        if a.rating is not None and a.reaction in UNHEARD:
            return f"a rating does not apply to '{a.reaction}': the track was not heard"
        return None

    async def report_preview(a: ReportArgs) -> str:
        gen_id, _ = await resolve_ref(state, a.generation)
        target = title_of(state, gen_id) if gen_id else f"{a.generation} (unresolved)"
        lines = [f"Record reaction on {target}: {a.reaction}" + (f" ★{a.rating}" if a.rating else "")]
        if a.notes:
            lines.append(f"notes: {a.notes}")
        if a.context:
            lines.append(f"context: {a.context}")
        if a.rating is not None and a.reaction not in POSITIVE_REACTIONS:
            lines.append("note: ratings are meaningful for positive reactions; recording it anyway")
        lines.append("The prompt stops being pending. Its reaction shapes what later prompts draw on.")
        return "\n".join(lines)

    async def report_tool(a: ReportArgs) -> ToolResult:
        gen_id, why = await resolve_ref(state, a.generation)
        if gen_id is None:
            return fail(f"Could not resolve {a.generation!r}: {why}")
        store, _, _ = state.stores()
        gen = await record_reaction(gen_id, a.reaction, store=store, rating=a.rating, notes=a.notes, context=a.context)
        if gen is None:
            return fail(f"No generation with id {gen_id}.")
        state.written(reaction_key(gen_id))
        return ok(f"Recorded: {gen.suggested_track_title or gen_id[:12]} → {a.reaction}"
                  + (f" ★{a.rating}" if a.rating is not None else ""), data={"gen_id": gen_id, "reaction": a.reaction})

    async def taste_tool(a: TasteInput) -> ToolResult:
        store, _, _ = state.stores()
        lesson = await add_taste(a.statement, a.valence, a.scope, store=store)
        state.written(taste_key(a.statement))
        return ok(f"Added taste lesson [{a.valence}/{a.scope}]: {a.statement[:80]}", data={"lesson_id": lesson.entry_id})

    async def fact_tool(a: FactArgs) -> ToolResult:
        _, _, uks = state.stores()
        entry_id = await add_fact(a.statement, a.domain, a.confidence, uks=uks, source_ref="manual:chat")
        return ok(f"Added fact to {a.domain}: {a.statement[:80]} (entry {entry_id})", data={"entry_id": entry_id})

    M = EffectClass.MEMORY_WRITE
    return [
        ToolSpec(name="report", effect=M, input_model=ReportArgs, handler=report_tool,
                 precheck=report_precheck, preview=report_preview,
                 description="Record the director's reaction to a prompt they ran in Suno (it stops being pending). "
                             "Pass what propose_reaction returned. The director confirms, edits or defers."),
        ToolSpec(name="taste_add", effect=M, input_model=TasteInput, handler=taste_tool,
                 preview=lambda a: f"Add a confirmed taste lesson [{a.valence}/{a.scope}]:\n  {a.statement}\n"
                                   "Every later prompt is written with it in view.",
                 description="Add ONE confirmed taste lesson. Offer lessons one at a time; never add one the director "
                             "did not state or accept."),
        ToolSpec(name="fact_add", effect=M, input_model=FactArgs, handler=fact_tool,
                 preview=lambda a: f"Add a verified fact to user_knowledge, domain {a.domain} ({a.confidence}):\n  {a.statement}",
                 description="Add a verified fact about how Suno behaves to user_knowledge (shared by all agents)."),
    ]
