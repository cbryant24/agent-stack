from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import visual_generation.chat.tools.reads as reads_mod
from visual_generation.batch_file import write_batch
from visual_generation.chat.tools import tool_pack
from visual_generation.models import (
    GenerationBatch,
    TechniqueLesson,
    VisualGeneration,
    VisualSpec,
    WorkflowTemplate,
)
from visual_generation.verify import VerifyReport

from .conftest import Built, make_gens  # type: ignore[import-not-found]  # noqa: F401

pytestmark = pytest.mark.asyncio


async def call(built: Built, name: str, **kw: Any):  # type: ignore[no-untyped-def]
    tool = next(t for t in tool_pack(built.state) if t.name == name)
    return await tool.handler(tool.input_model(**kw))


async def test_recall_returns_hits_with_labels(build: Callable[..., Built]) -> None:
    gens = make_gens(3)
    b = build(gens=gens)
    r = await call(b, "recall", query="neon alley", limit=3)
    assert not r.is_error and r.data["generation_ids"] == [g.entry_id for g in gens]
    assert "In this project: attempt-01" in r.text and "attempt-03" in r.text
    b.store.search_generations.assert_awaited()          # one-shot reads, no sync wrapper


async def test_review_pending_is_scoped_to_the_project_and_not_called_failed(build: Callable[..., Built]) -> None:
    mine, other = make_gens(1)[0], VisualGeneration(caption="x", project="other")
    b = build(gens=[mine], pending=[mine, other])
    r = await call(b, "review_pending")
    assert r.data["generation_ids"] == [mine.entry_id]
    assert "not failed" in next(t for t in tool_pack(b.state) if t.name == "review_pending").description
    assert (await call(b, "review_pending", all_projects=True)).data["generation_ids"] == [mine.entry_id, other.entry_id]


async def test_chain_show_accepts_a_label_and_finds_the_chain_root(build: Callable[..., Built]) -> None:
    root = make_gens(1)[0]
    child = VisualGeneration(caption="rev", project="demo", parent_id=root.entry_id, chain_root_id=root.entry_id,
                             created_at="2026-01-01T00:00:09+00:00")
    b = build(gens=[root, child])
    r = await call(b, "chain_show", generation="attempt-02")
    assert not r.is_error and r.data["chain_root_id"] == root.entry_id
    assert set(r.data["generation_ids"]) == {root.entry_id, child.entry_id}


async def test_unresolved_label_is_an_error_carrying_an_open_question(build: Callable[..., Built]) -> None:
    b = build(gens=make_gens(2))
    for name, key in (("chain_show", "generation"), ("inspect_generation", "generation")):
        r = await call(b, name, **{key: "attempt-09"})
        assert r.is_error and r.data["open_questions"] and "attempt-09" in r.text


async def test_inspect_generation_by_label_and_by_full_id_from_another_project(build: Callable[..., Built]) -> None:
    foreign = VisualGeneration(caption="far away", prompt="a lighthouse", project="other")
    b = build(gens=make_gens(2), by_id={foreign.entry_id: foreign})
    r = await call(b, "inspect_generation", generation="attempt-01")
    assert "attempt-01" in r.text and r.data["generation_id"]
    r2 = await call(b, "inspect_generation", generation=foreign.entry_id)
    assert not r2.is_error and "a lighthouse" in r2.text


async def test_digest_needs_a_project(build: Callable[..., Built]) -> None:
    r = await call(build(project=None), "digest")
    assert r.is_error and "--project" in r.text
    ok = await call(build(gens=make_gens(2)), "digest")
    assert not ok.is_error and ok.data["generations"] == 2 and "In this project" in ok.text


async def test_batch_list_without_a_file(build: Callable[..., Built]) -> None:
    r = await call(build(), "batch_list")
    assert not r.is_error and "No batch file yet" in r.text and r.data["specs"] == []


async def test_batch_list_reports_specs_whose_metadata_failed_to_parse(build: Callable[..., Built]) -> None:
    b = build()
    path = b.state.batch_path()
    write_batch(GenerationBatch(project="demo", specs=[
        VisualSpec(heading="Good", prompt="a", settings={"steps": 8}),
        VisualSpec(heading="Broken", prompt="b", settings={"steps": 9}, rationale="use a --> b"),
    ]), path)
    r = await call(b, "batch_list")
    assert not r.is_error and len(r.data["specs"]) == 2
    assert [i["heading"] for i in r.data["issues"]] == ["Broken"]
    assert "Metadata problems" in r.text and "Broken" in r.text and r.artifacts == [str(path)]


async def test_batch_list_with_no_project(build: Callable[..., Built]) -> None:
    r = await call(build(project=None), "batch_list")
    assert r.is_error and "no project" in r.text


async def test_workflow_lesson_model_canon(build: Callable[..., Built], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmpl = WorkflowTemplate(name="z-image-turbo", descriptor="stills", graph={}, slot_map={})
    lesson = TechniqueLesson(statement="denoise 0.5 keeps the coat", valence="positive", scope="settings", confirmed=True)
    b = build(templates=[tmpl], lessons=[lesson])
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))
    assert (await call(b, "workflow_list")).data["templates"] == ["z-image-turbo"]
    r = await call(b, "lesson_list", scope="settings")
    assert r.data["lesson_ids"] == [lesson.entry_id]
    b.store.list_lessons.assert_awaited_with(confirmed_only=True, scope="settings", valence=None)
    assert "registered" in (await call(b, "model_list")).text.lower() or "No models" in (await call(b, "model_list")).text
    assert (await call(b, "canon_show")).data["subjects"] == 0
    assert (await call(build(project=None), "canon_show")).is_error


async def test_knowledge_verify(build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch) -> None:
    report = VerifyReport(query="denoise", legs=[], gaps=["nothing visual surfaced"], collection_counts={"c": 3})
    spy = AsyncMock(return_value=report)
    monkeypatch.setattr(reads_mod, "verify_knowledge", spy)
    b = build()
    r = await call(b, "knowledge_verify", query="denoise", limit=4)
    assert r.data["gaps"] == ["nothing visual surfaced"] and "Gaps" in r.text
    assert spy.await_args.kwargs == {"project": "demo", "limit": 4}


async def test_long_output_is_clipped(build: Callable[..., Built]) -> None:
    gens = [VisualGeneration(caption="x" * 70, prompt="y" * 70, project="demo",
                             created_at=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00") for i in range(200)]
    r = await call(build(gens=gens), "recall", query="x", limit=10)
    assert len(r.text) <= 3500 + 120
