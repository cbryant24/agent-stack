"""Nothing that spends GPU or writes to memory is reachable from the chat tool pack."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_shell.tools.registry import EffectClass

import visual_generation.chat as chat_pkg
from visual_generation.chat.tools import tool_pack

from .conftest import Built  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

EXPECTED = {
    "recall", "review_pending", "chain_show", "inspect_generation", "digest", "batch_list",
    "model_list", "workflow_list", "lesson_list", "canon_show", "knowledge_verify",
    "explain", "draft", "redraft", "batch_build", "propose_interpretation",
}
# Commands the phase deliberately does not expose. Their absence is the guarantee.
ABSENT = {
    "generate", "quick", "report", "lesson_add", "lesson_rm", "fact_add", "fact_ingest_docs",
    "workflow_register", "model_sync", "model_rm", "canon_set", "canon_edit", "canon_rm",
    "batch_rm", "batch_rebuild", "research", "record_evaluation",
}
READS = {"recall", "review_pending", "chain_show", "inspect_generation", "digest", "batch_list",
         "model_list", "workflow_list", "lesson_list", "canon_show", "knowledge_verify"}
LLM = {"explain", "draft", "redraft", "batch_build"}

# Every name chat/ may import from the rest of visual_generation. Adding to this list is the
# review point: anything that renders on a GPU or writes memory must never appear here.
ALLOWED_IMPORTS = {
    ("visual_generation", "reads"),
    ("visual_generation.batch_file", "read_batch_diagnosed"),
    ("visual_generation.discovery", "discover_scenes"),
    ("visual_generation.draft", "RefinementSourceError"),
    ("visual_generation.draft", "build_refinement_source"),
    ("visual_generation.draft", "draft"),
    ("visual_generation.draft", "redraft"),
    ("visual_generation.explain", "explain"),
    ("visual_generation.explain", "render_explain"),
    ("visual_generation.inspect", "get_chain"),
    ("visual_generation.inspect", "get_generation"),
    ("visual_generation.inspect", "list_pending"),
    ("visual_generation.inspect", "recall"),
    ("visual_generation.inspect", "render_chain"),
    ("visual_generation.inspect", "render_generation"),
    ("visual_generation.inspect", "render_pending"),
    ("visual_generation.inspect", "render_recall"),
    ("visual_generation.models", "DraftResult"),
    ("visual_generation.models", "VisualGeneration"),
    ("visual_generation.models", "VisualSource"),
    ("visual_generation.store", "VisualGenerationStore"),
    ("visual_generation.verify", "verify_knowledge"),
}
SPENDING_MODULES = {
    "generate", "quick", "report", "comfyui_client", "gpu_tracker", "graph_build", "assets",
    "model_sync", "slot_inference", "research", "lora_guard",
}


def tools(built: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(built.state)}


async def test_the_tool_set_is_exactly_the_expected_one(build: Callable[..., Built]) -> None:
    names = set(tools(build()))
    assert names == EXPECTED
    assert not names & ABSENT


async def test_effect_classes(build: Callable[..., Built]) -> None:
    t = tools(build())
    assert {n for n, s in t.items() if s.effect is EffectClass.READ} == READS
    assert {n for n, s in t.items() if s.effect is EffectClass.LLM_SPEND} == LLM
    assert t["propose_interpretation"].effect is EffectClass.NONE
    forbidden = {EffectClass.GPU_SPEND, EffectClass.MEMORY_WRITE, EffectClass.DESTRUCTIVE_LOCAL}
    assert not {s.effect for s in t.values()} & forbidden


def _imports_from_visual_generation() -> set[tuple[str, str]]:
    used: set[tuple[str, str]] = set()
    for path in Path(chat_pkg.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                mod = node.module or ""
                if mod.startswith("visual_generation") and not mod.startswith("visual_generation.chat"):
                    used |= {(mod, a.name) for a in node.names}
            elif isinstance(node, ast.Import):
                used |= {(a.name, "*") for a in node.names
                         if a.name.startswith("visual_generation") and not a.name.startswith("visual_generation.chat")}
    return used


async def test_chat_imports_only_allowlisted_names_from_the_library() -> None:
    used = _imports_from_visual_generation()
    assert used <= ALLOWED_IMPORTS, f"new imports to review: {sorted(used - ALLOWED_IMPORTS)}"


async def test_chat_never_imports_a_spending_or_rendering_module() -> None:
    mods = {m.split(".")[1] for m, _ in _imports_from_visual_generation() if "." in m}
    assert not mods & SPENDING_MODULES


async def test_running_every_tool_makes_no_data_write_and_no_spend(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every read tool, plus propose_interpretation, against stores that record any write; and the
    GPU/memory entry points booby-trapped so any call fails the test."""
    from unittest.mock import AsyncMock

    import visual_generation.chat.tools.reads as reads_mod
    from visual_generation.verify import VerifyReport

    def tripwire(*a: object, **k: object) -> None:
        raise AssertionError("a GPU-spending or memory-writing function was reached")

    import importlib

    # the package exports functions named generate/quick/report that shadow these submodules
    comfy, gen, quick, report = (
        importlib.import_module(f"visual_generation.{m}")
        for m in ("comfyui_client", "generate", "quick", "report")
    )
    from visual_generation.store import VisualGenerationStore

    monkeypatch.setattr(comfy.ComfyUIClient, "__init__", tripwire)
    for mod, name in ((gen, "spend_generation"), (gen, "plan_generation"), (quick, "quick_generate"), (report, "report")):
        monkeypatch.setattr(mod, name, tripwire)
    for name in ("upsert_generation", "update_generation_reaction", "upsert_lesson", "delete_lesson", "upsert_template"):
        monkeypatch.setattr(VisualGenerationStore, name, tripwire)
    monkeypatch.setattr(reads_mod, "verify_knowledge", AsyncMock(return_value=VerifyReport(
        query="q", legs=[], gaps=[], collection_counts={})))
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))

    from .conftest import make_gens  # type: ignore[import-not-found]

    b = build(gens=make_gens(3))
    t = tools(b)
    args: dict[str, dict[str, Any]] = {
        "recall": {"query": "x"}, "review_pending": {}, "chain_show": {"generation": "attempt-01"},
        "inspect_generation": {"generation": "attempt-02"}, "digest": {}, "batch_list": {},
        "model_list": {}, "workflow_list": {}, "lesson_list": {}, "canon_show": {},
        "knowledge_verify": {"query": "x"},
        "propose_interpretation": {"feedback": "f", "observations": [
            {"layer": "production_quality", "category": "prompt", "attribution": "prompt", "claim": "c", "label": "attempt-01"}]},
    }
    for name, kw in args.items():
        r = await t[name].handler(t[name].input_model(**kw))
        assert not r.is_error, (name, r.text)
    assert b.writes == []
