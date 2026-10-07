"""Confirm / reject / edit / defer / dry-run judged by real Qdrant point counts.

Each test gets a throwaway collection on the local Qdrant (embeddings are faked, so no Voyage
calls and nothing touches the real `visual_generation_memory`). Skipped, with the reason shown by
`pytest -rs`, when Qdrant is not running at localhost:6333.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from agent_runtime import MemoryStore
from agent_runtime.config import get_config
from agent_shell.config import ShellSettings
from agent_shell.engine.fake import Call, FakeEngine
from agent_shell.guard.gate import AutoConfirmer, Decision
from agent_shell.session.api import Session
from agent_shell.testing import drain

from visual_generation.chat.config import build_chat_config
from visual_generation.chat.state import ChatState
from visual_generation.evaluation import EXECUTION_TRUTH_ENV
from visual_generation.model_registry import ModelRegistry
from visual_generation.models import VisualGeneration
from visual_generation.store import VisualGenerationStore


def _qdrant_up() -> bool:
    try:
        return httpx.get("http://localhost:6333/healthz", timeout=1.0).status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _qdrant_up(), reason="Qdrant not running at localhost:6333: point-count tests skipped"),
]

EV = dict(generation="attempt-02", raw_feedback="the face reads plastic", reaction="disliked", rating=2,
          findings=[dict(layer="conditioning_asset", evidence="observed", statement="button eyes read as paint",
                         basis="attempt-02 asset")])
LESSON = dict(statement="a masked eye inpaint fixes button eyes", scope="workflow", valence="positive",
              layer="conditioning_asset", topic="identity", evidence_n=2)


class FakeEmbedder:
    """Deterministic 1024-d unit vectors from the text: distinct texts, stable across calls."""

    @staticmethod
    def vec(text: str) -> list[float]:
        raw = hashlib.sha256(text.encode()).digest() * 32
        v = [b - 127.5 for b in raw[:1024]]
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]

    async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        return [self.vec(t) for t in texts]

    async def embed_multimodal(self, inputs: list[Any], input_type: str = "document") -> list[list[float]]:
        return [self.vec(i.text or "") for i in inputs]


class World:
    def __init__(self, store: VisualGenerationStore, memory: MemoryStore, collection: str, gens: list[VisualGeneration],
                 tmp: Path) -> None:
        self.store, self.memory, self.collection, self.gens, self.tmp = store, memory, collection, gens, tmp

    async def count(self, memory_type: str | None = None) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        f = None if memory_type is None else Filter(must=[FieldCondition(key="memory_type", match=MatchValue(value=memory_type))])
        return await self.memory.count_points(self.collection, filters=f)

    def session(self, script: list[list[Call]], confirmer: AutoConfirmer, *, dry_run: bool = False) -> Session:
        state = ChatState(project="demo", config=get_config(), store=self.store, memory_store=self.memory)
        s = Session(build_chat_config(state),
                    ShellSettings(agent_data_dir=self.tmp / "shell", dry_run=dry_run),
                    FakeEngine(script), confirmer=confirmer)
        state.session = s
        self.state = state
        return s


@pytest_asyncio.fixture
async def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    monkeypatch.delenv(EXECUTION_TRUTH_ENV, raising=False)
    monkeypatch.setenv("AGENT_PROJECTS_DIR", str(tmp_path / "projects"))
    from agent_runtime.config import reset_config

    reset_config()
    monkeypatch.setattr(MemoryStore, "embedding_client", property(lambda self: FakeEmbedder()))
    collection = f"vg_test_{uuid.uuid4().hex[:12]}"
    memory = MemoryStore(url=get_config().qdrant_url)
    store = VisualGenerationStore(memory, collection_name=collection, model_registry=ModelRegistry(tmp_path / "models.json"))
    await store.ensure_collection()
    gens = [VisualGeneration(caption=f"shot {i}", prompt=f"prompt {i}", project="demo",
                             created_at=f"2026-01-01T00:00:{i:02d}+00:00") for i in (1, 2, 3)]
    for g in gens:
        await store.upsert_generation(g)
    try:
        yield World(store, memory, collection, gens, tmp_path)
    finally:
        await memory._client.delete_collection(collection)
        reset_config()


def record(**over: Any) -> list[list[Call]]:
    return [[Call(name="record_evaluation", args={**EV, **over})]]


# ── evaluations ───────────────────────────────────────────────────────────────


async def test_confirm_adds_exactly_one_evaluation_and_sets_the_reaction(world: World) -> None:
    before, evals_before = await world.count(), await world.count("evaluation")
    s = world.session(record(), AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    assert await world.count() == before + 1 and await world.count("evaluation") == evals_before + 1
    gen = await world.store.get_generation(world.gens[1].entry_id)
    assert gen is not None and gen.reaction == "disliked" and gen.rating == 2 and gen.status == "complete"


async def test_reject_leaves_the_point_count_unchanged(world: World) -> None:
    before = await world.count()
    s = world.session(record(), AutoConfirmer("reject"))
    await s.start()
    await drain(s, "go")
    assert await world.count() == before
    gen = await world.store.get_generation(world.gens[1].entry_id)
    assert gen is not None and gen.reaction == "pending"


async def test_defer_dry_run_and_a_refused_record_also_leave_the_count_unchanged(world: World) -> None:
    before = await world.count()
    for confirmer, kw, script in (
        (AutoConfirmer("defer"), {}, record()),
        (AutoConfirmer("accept"), {"dry_run": True}, record()),
        (AutoConfirmer("accept"), {}, record(change=["set denoise to 0.35"])),     # refused by the precheck
    ):
        s = world.session(script, confirmer, **kw)
        await s.start()
        await drain(s, "go")
        assert await world.count() == before
    assert list((world.tmp / "shell" / "drafts" / "visual-generation").glob("*.json"))     # the deferred draft


async def test_edit_stores_the_edited_record(world: World) -> None:
    s = world.session(record(), AutoConfirmer(Decision(kind="edit", payload={**EV, "reaction": "liked_with_changes", "rating": 4})))
    await s.start()
    await drain(s, "go")
    (e,) = await world.store.list_evaluations(gen_id=world.gens[1].entry_id)
    assert (e.reaction, e.rating) == ("liked_with_changes", 4)
    assert (await world.store.get_generation(world.gens[1].entry_id)).reaction == "liked_with_changes"   # type: ignore[union-attr]


async def test_an_evaluation_is_retrievable_by_generation_by_chain_by_project_and_through_recall(world: World) -> None:
    child = VisualGeneration(caption="child", project="demo", parent_id=world.gens[1].entry_id,
                             chain_root_id=world.gens[1].entry_id, created_at="2026-01-01T00:00:09+00:00")
    await world.store.upsert_generation(child)
    s = world.session(record(), AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    gid, root = world.gens[1].entry_id, world.gens[1].chain_root_id
    by_gen = await world.store.list_evaluations(gen_id=gid)
    by_chain = await world.store.list_evaluations(chain_root_id=child.chain_root_id)    # found from the child's chain
    by_project = await world.store.list_evaluations(project="demo")
    assert len(by_gen) == len(by_chain) == len(by_project) == 1 and root == child.chain_root_id
    assert await world.store.list_evaluations(gen_id=world.gens[0].entry_id) == []
    hits = await world.store.search_evaluations("the face reads plastic", project="demo")
    assert [h[2].entry_id for h in hits] == [by_gen[0].entry_id]
    exact = await world.store.search_evaluations(by_gen[0].embed_text, project="demo")
    assert exact[0][1] > 0.99                                                            # the embedded text itself
    # and through the chat's recall tool
    s2 = world.session([[Call(name="recall", args={"query": "the face reads plastic"})]], AutoConfirmer())
    await s2.start()
    events = await drain(s2, "recall")
    from agent_shell.engine.base import ToolCallFinished

    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.data["evaluation_ids"] == [by_gen[0].entry_id] and "── Evaluations (1)" in fin.result.text


async def test_the_pre_fix_marking_is_what_is_stored(world: World) -> None:
    s = world.session(record(), AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    (e,) = await world.store.list_evaluations(project="demo")
    assert e.agent_status == "unresolved" and any("seed may not match" in f.statement for f in e.findings)
    assert e.session_id == s.session_id and e.engine_provider == "fake"


async def test_rerunning_the_same_confirmed_evaluation_does_not_add_a_second_point(world: World) -> None:
    s = world.session([*record(), *record()], AutoConfirmer("accept", "accept"))
    await s.start()
    await drain(s, "one")
    after_first = await world.count("evaluation")
    await drain(s, "two")
    assert await world.count("evaluation") == after_first == 1


async def test_an_unwritten_proposal_applied_at_exit_adds_the_point(world: World) -> None:
    import io

    from agent_shell.repl.app import ShellApp, _bindings
    from prompt_toolkit import PromptSession
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from rich.console import Console

    before = await world.count("evaluation")
    s = world.session([[Call(name="propose_interpretation", args=EV)]], AutoConfirmer())
    with create_pipe_input() as pipe:
        pipe.send_text("feedback\r/exit\ry\r")
        prompt: PromptSession[str] = PromptSession(input=pipe, output=DummyOutput(), key_bindings=_bindings(), multiline=True)
        await ShellApp(s, console=Console(file=io.StringIO(), width=110), prompt=prompt).run()
    assert await world.count("evaluation") == before + 1


# ── lessons ───────────────────────────────────────────────────────────────────


async def test_lesson_confirm_adds_one_reject_adds_none_and_removal_follows_the_gate(world: World) -> None:
    base = await world.count("technique_lesson")
    s = world.session([[Call(name="add_lesson", args=LESSON)]], AutoConfirmer("reject"))
    await s.start()
    await drain(s, "no")
    assert await world.count("technique_lesson") == base

    s = world.session([[Call(name="add_lesson", args=LESSON)]], AutoConfirmer("accept"))
    await s.start()
    await drain(s, "yes")
    assert await world.count("technique_lesson") == base + 1
    (le,) = await world.store.list_lessons()
    assert le.layer == "conditioning_asset" and le.confirmed

    s = world.session([[Call(name="lesson_rm", args={"lesson": le.entry_id[:8]})]], AutoConfirmer("reject"))
    await s.start()
    await drain(s, "keep")
    assert await world.count("technique_lesson") == base + 1                      # rejected: still there
    s = world.session([[Call(name="lesson_rm", args={"lesson": le.entry_id[:8]})]], AutoConfirmer("accept"))
    await s.start()
    await drain(s, "remove")
    assert await world.count("technique_lesson") == base                          # removed by prefix


async def test_a_refused_lesson_writes_nothing(world: World) -> None:
    bad = {**LESSON, "layer": "prompt", "statement": "phrase the face precisely to keep identity"}
    s = world.session([[Call(name="add_lesson", args=bad)]], AutoConfirmer("accept"))
    await s.start()
    events = await drain(s, "go")
    from agent_shell.engine.base import ToolCallFinished

    fin = next(e for e in events if isinstance(e, ToolCallFinished))
    assert fin.result.is_error and "falsification_test" in fin.result.text
    assert await world.count("technique_lesson") == 0


async def test_the_audit_log_matches_what_the_collection_holds(world: World) -> None:
    s = world.session(record(), AutoConfirmer("accept"))
    await s.start()
    await drain(s, "go")
    assert s.audit is not None
    rec = next(r for r in s.audit.read() if r["kind"] == "tool_call")
    (stored,) = await world.store.list_evaluations(project="demo")
    assert rec["result_data"]["evaluation_id"] == stored.entry_id and rec["args"]["raw_feedback"] == stored.raw_feedback
    assert json.loads(json.dumps(rec["args"]))["reaction"] == stored.reaction
