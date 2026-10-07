"""The shared `knowledge` tool pack: the propose-then-confirm workflow over `user_knowledge`.

Agents propose knowledge entries as drafts (files that expire after 7 days); until now nothing
surfaced those drafts in a conversation. An agent's chat includes this pack by passing a function
that returns its `UserKnowledgeStore`. The store's own methods do every read and write.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec

MIN_PREFIX = 8
KNOWLEDGE_TOOL_NAMES = ("knowledge_drafts", "knowledge_search", "knowledge_confirm", "knowledge_reject")


class NoArgs(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str
    domain: str | None = Field(default=None, description="Limit to one domain, e.g. 'suno_mechanics'.")
    limit: int = Field(default=5, ge=1, le=20)


class DraftArgs(BaseModel):
    draft: str = Field(description="The draft's id, or a unique prefix of 8+ characters.")


def _render(d: Any) -> str:
    lines = [f"  {d.statement}", f"  domain: {d.domain}   confidence: {d.confidence}   source: {d.source_type}"]
    if d.source_ref:
        lines.append(f"  from: {d.source_ref}")
    if d.topic_tags:
        lines.append(f"  tags: {', '.join(d.topic_tags)}")
    return "\n".join(lines)


def knowledge_tools(get_store: Callable[[], Any]) -> list[ToolSpec]:
    """`get_store()` returns the agent's `UserKnowledgeStore` (called per tool call)."""

    async def find(ref: str) -> tuple[Any | None, str]:
        """(draft, why-not). Full id or a unique 8+ character prefix; never a guess."""
        key = ref.strip().lower()
        drafts = await get_store().list_drafts()
        exact = [d for d in drafts if d.draft_id.lower() == key]
        if exact:
            return exact[0], ""
        if len(key) >= MIN_PREFIX:
            hits = [d for d in drafts if d.draft_id.lower().startswith(key)]
            if len(hits) == 1:
                return hits[0], ""
            if len(hits) > 1:
                return None, f"{ref!r} matches {len(hits)} drafts; use more characters"
        return None, f"no pending knowledge draft matches {ref!r} (drafts expire after 7 days)"

    async def drafts_tool(a: NoArgs) -> ToolResult:
        drafts = await get_store().list_drafts()
        if not drafts:
            return ToolResult(text="No pending knowledge drafts.", data={"draft_ids": []})
        blocks = [f"{d.draft_id}  (proposed {d.created_at:%Y-%m-%d})\n{_render(d)}" for d in drafts]
        return ToolResult(
            text=f"{len(drafts)} pending knowledge draft(s); each expires 7 days after it was proposed:\n\n"
                 + "\n\n".join(blocks),
            data={"draft_ids": [d.draft_id for d in drafts]},
        )

    async def search_tool(a: SearchArgs) -> ToolResult:
        hits = await get_store().search(a.query, domain=a.domain, limit=a.limit)
        if not hits:
            return ToolResult(text="No confirmed knowledge matches.", data={"entry_ids": []})
        lines = [f"[{h.score:.3f}] ({h.domain}, {h.confidence}) {h.statement}" for h in hits]
        return ToolResult(text="\n".join(lines), data={"entry_ids": [h.entry_id for h in hits]})

    async def precheck(a: DraftArgs) -> str | None:
        draft, why = await find(a.draft)
        return None if draft is not None else why

    async def confirm_preview(a: DraftArgs) -> str:
        draft, _ = await find(a.draft)
        return f"Confirm this draft into user_knowledge (it becomes retrievable by every agent):\n{_render(draft)}"

    async def confirm_tool(a: DraftArgs) -> ToolResult:
        draft, why = await find(a.draft)
        if draft is None:
            return ToolResult(text=why, is_error=True)
        entry_id = await get_store().confirm_entry(draft.draft_id)
        return ToolResult(text=f"Confirmed into user_knowledge as {entry_id}: {draft.statement[:100]}",
                          data={"entry_id": entry_id, "draft_id": draft.draft_id})

    async def reject_preview(a: DraftArgs) -> str:
        draft, _ = await find(a.draft)
        return f"Discard this draft (nothing is written to user_knowledge; the draft file is deleted):\n{_render(draft)}"

    async def reject_tool(a: DraftArgs) -> ToolResult:
        draft, why = await find(a.draft)
        if draft is None:
            return ToolResult(text=why, is_error=True)
        await get_store().reject_entry(draft.draft_id)
        return ToolResult(text=f"Discarded draft {draft.draft_id}: {draft.statement[:100]}",
                          data={"draft_id": draft.draft_id})

    M = EffectClass.MEMORY_WRITE
    return [
        ToolSpec(name="knowledge_drafts", effect=EffectClass.READ, input_model=NoArgs, handler=drafts_tool,
                 description="List knowledge entries that agents proposed and nobody has confirmed yet (they expire after 7 days)."),
        ToolSpec(name="knowledge_search", effect=EffectClass.READ, input_model=SearchArgs, handler=search_tool,
                 description="Search confirmed user knowledge (verified facts and preferences shared by all agents)."),
        ToolSpec(name="knowledge_confirm", effect=M, input_model=DraftArgs, handler=confirm_tool,
                 precheck=precheck, preview=confirm_preview,
                 description="Confirm ONE pending knowledge draft into user_knowledge. The director sees it first. "
                             "Offer drafts one at a time; never confirm on your own judgment."),
        ToolSpec(name="knowledge_reject", effect=M, input_model=DraftArgs, handler=reject_tool,
                 precheck=precheck, preview=reject_preview,
                 description="Discard ONE pending knowledge draft. The director sees it first."),
    ]
