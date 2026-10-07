"""The shared knowledge pack against a real UserKnowledgeStore draft directory and a store double
for Qdrant: drafts are listed, confirmed and rejected only through the gate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_runtime import UserKnowledgeStore

from agent_shell.config import ShellSettings
from agent_shell.demo import demo_config, demo_engine
from agent_shell.engine.fake import Call, FakeEngine
from agent_shell.guard.gate import AutoConfirmer
from agent_shell.packs.knowledge import KNOWLEDGE_TOOL_NAMES, knowledge_tools
from agent_shell.session.api import Session
from agent_shell.testing import drain
from agent_shell.tools.registry import EffectClass

pytestmark = pytest.mark.asyncio


@pytest.fixture
def uks(tmp_path: Path) -> UserKnowledgeStore:
    memory = MagicMock()
    memory.ensure_collection = AsyncMock()
    memory.upsert_raw_points = AsyncMock()
    memory.embedding_client = SimpleNamespace(embed=AsyncMock(return_value=[[0.0] * 1024]))
    memory.query_by_vector = AsyncMock(return_value=[("e1", 0.91, {
        "statement": "Suno caps the style field at 1000 characters", "domain": "suno_mechanics",
        "confidence": "high", "source_type": "user_verified", "entry_id": "e1"})])
    store = UserKnowledgeStore(memory)
    store.memory = memory                                    # type: ignore[attr-defined]
    return store


def tools(uks: UserKnowledgeStore) -> dict[str, Any]:
    return {t.name: t for t in knowledge_tools(lambda: uks)}


async def test_the_pack_is_four_tools_with_reads_free_and_writes_gated(uks: UserKnowledgeStore) -> None:
    t = tools(uks)
    assert tuple(t) == KNOWLEDGE_TOOL_NAMES
    assert {n for n, s in t.items() if s.effect is EffectClass.READ} == {"knowledge_drafts", "knowledge_search"}
    for name in ("knowledge_confirm", "knowledge_reject"):
        assert t[name].effect is EffectClass.MEMORY_WRITE and t[name].preview and t[name].precheck


async def test_drafts_are_listed_and_resolved_by_id_or_unique_prefix(uks: UserKnowledgeStore) -> None:
    t = tools(uks)
    assert "No pending knowledge drafts." == (await t["knowledge_drafts"].handler(t["knowledge_drafts"].input_model())).text
    d = await uks.propose_entry("prefer shorter intros on cut-downs", "editing_preference", "agent_inferred",
                                source_ref="feedback-iteration:brief-7")
    r = await t["knowledge_drafts"].handler(t["knowledge_drafts"].input_model())
    assert d.draft_id in r.text and "prefer shorter intros" in r.text and "feedback-iteration:brief-7" in r.text
    assert r.data["draft_ids"] == [d.draft_id]

    args = t["knowledge_confirm"].input_model
    assert await t["knowledge_confirm"].precheck(args(draft=d.draft_id[:8])) is None
    assert "prefer shorter intros" in await t["knowledge_confirm"].preview(args(draft=d.draft_id[:8]))
    assert "no pending knowledge draft matches" in await t["knowledge_confirm"].precheck(args(draft="zzzzzzzz"))
    assert "no pending knowledge draft matches" in await t["knowledge_confirm"].precheck(args(draft=d.draft_id[:4]))


async def test_search_returns_confirmed_knowledge(uks: UserKnowledgeStore) -> None:
    t = tools(uks)
    r = await t["knowledge_search"].handler(t["knowledge_search"].input_model(query="style field limit"))
    assert "[0.910] (suno_mechanics, high) Suno caps the style field at 1000 characters" in r.text


def session(uks: UserKnowledgeStore, settings: ShellSettings, name: str, draft_id: str, answer: str,
            dry_run: bool = False) -> tuple[Session, AutoConfirmer]:
    c = AutoConfirmer(answer)                                  # type: ignore[arg-type]
    config = demo_config().model_copy(update={"tool_pack": lambda: knowledge_tools(lambda: uks), "on_session_end": None})
    s = Session(config, ShellSettings(**{**settings.model_dump(), "dry_run": dry_run}),
                FakeEngine([[Call(name=name, args={"draft": draft_id})]]), confirmer=c)
    return s, c


async def test_confirm_writes_only_when_the_director_accepts(uks: UserKnowledgeStore, settings: ShellSettings) -> None:
    d = await uks.propose_entry("no vocals under dialogue", "editing_preference", "agent_inferred")
    for answer, dry in (("reject", False), ("accept", True)):
        s, c = session(uks, settings, "knowledge_confirm", d.draft_id, answer, dry)
        await s.start()
        await drain(s, "go")
        assert uks.memory.upsert_raw_points.await_count == 0 and len(await uks.list_drafts()) == 1   # type: ignore[attr-defined]

    s, c = session(uks, settings, "knowledge_confirm", d.draft_id, "accept")
    await s.start()
    await drain(s, "go")
    assert c.requests[0].tool == "knowledge_confirm" and "no vocals under dialogue" in (c.requests[0].preview or "")
    assert uks.memory.upsert_raw_points.await_count == 1 and await uks.list_drafts() == []           # type: ignore[attr-defined]


async def test_reject_deletes_the_draft_and_writes_nothing(uks: UserKnowledgeStore, settings: ShellSettings) -> None:
    d = await uks.propose_entry("always open on a wide", "editing_preference", "agent_inferred")
    s, c = session(uks, settings, "knowledge_reject", d.draft_id, "accept")
    await s.start()
    await drain(s, "go")
    assert "Discard this draft" in (c.requests[0].preview or "")
    assert await uks.list_drafts() == [] and uks.memory.upsert_raw_points.await_count == 0             # type: ignore[attr-defined]
    assert demo_engine() is not None
