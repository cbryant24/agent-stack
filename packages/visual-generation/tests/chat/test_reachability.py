"""The chat tool pack has no GPU path, no direct Qdrant code, and every write is a gated tool."""

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


READS = {"recall", "review_pending", "chain_show", "inspect_generation", "digest", "batch_list",
         "model_list", "workflow_list", "lesson_list", "canon_show", "knowledge_verify", "list_evaluations"}
LLM = {"explain", "draft", "redraft", "batch_build"}
MEMORY = {"report", "record_evaluation", "add_lesson", "add_fact", "canon_set", "canon_edit", "workflow_register"}
DESTRUCTIVE = {"lesson_rm", "batch_rm", "model_rm", "canon_rm"}
EXPECTED = READS | LLM | MEMORY | DESTRUCTIVE | {"propose_interpretation"}
# Not exposed in this phase: anything that renders or needs a pod, and delegation that ingests.
ABSENT = {"generate", "quick", "fact_ingest_docs", "model_sync", "batch_rebuild", "research", "lesson_add",
          "fact_add", "sync_models"}

# Every name chat/ may import from the rest of visual_generation. Adding to this list is the
# review point: anything that renders on a GPU must never appear here, and Qdrant writes appear
# only as the library's own functions (evaluation / curation / report), never as store calls.
ALLOWED_IMPORTS = {
    ("visual_generation", "reads"),
    ("visual_generation.batch_file", "read_batch_diagnosed"),
    ("visual_generation.constants", "POSITIVE_REACTIONS"),
    *{("visual_generation.curation", n) for n in (
        "CanonEdit", "LessonRuleError", "add_fact", "add_lesson", "commit_workflow", "edit_canon_subject",
        "find_batch_spec", "find_canon_subject", "lesson_rule_violations", "load_graph_file", "lookup_lesson",
        "lookup_model", "parse_lora", "plan_canon_edit", "plan_canon_set", "plan_workflow", "remove_batch_spec",
        "remove_canon_subject", "remove_lesson", "remove_model", "render_canon_change", "render_workflow_plan",
        "resolve_lesson_id", "set_canon_subject")},
    ("visual_generation.discovery", "discover_scenes"),
    ("visual_generation.draft", "RefinementSourceError"),
    ("visual_generation.draft", "build_refinement_source"),
    ("visual_generation.draft", "draft"),
    ("visual_generation.draft", "redraft"),
    *{("visual_generation.evaluation", n) for n in (
        "EvaluationPartialWrite", "StrikeStatus", "apply_execution_truth", "evaluation_id",
        "execution_truth_verified_since", "list_evaluations", "record_evaluation", "render_evaluations",
        "strike_status", "ungrounded_numbers")},
    ("visual_generation.explain", "explain"),
    ("visual_generation.explain", "render_explain"),
    *{("visual_generation.inspect", n) for n in (
        "get_chain", "get_generation", "list_pending", "recall_all", "render_chain", "render_generation",
        "render_pending", "render_recall_all")},
    *{("visual_generation.models", n) for n in (
        "ArchitectureQuestion", "DraftResult", "EvaluationEntry", "Finding", "KeepConstraint", "Layer",
        "VisualGeneration", "VisualSource")},
    ("visual_generation.reads", "render_subject"),
    ("visual_generation.report", "report"),
    ("visual_generation.store", "VisualGenerationStore"),
    ("visual_generation.verify", "verify_knowledge"),
}
SPENDING_MODULES = {
    "generate", "quick", "comfyui_client", "gpu_tracker", "graph_build", "assets",
    "model_sync", "slot_inference", "research", "lora_guard",
}


def tools(built: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(built.state)}


@pytest.mark.asyncio
async def test_the_tool_set_is_exactly_the_expected_one(build: Callable[..., Built]) -> None:
    names = set(tools(build()))
    assert names == EXPECTED
    assert not names & ABSENT


@pytest.mark.asyncio
async def test_effect_classes(build: Callable[..., Built]) -> None:
    t = tools(build())
    by = lambda eff: {n for n, sp in t.items() if sp.effect is eff}  # noqa: E731
    assert by(EffectClass.READ) == READS and by(EffectClass.LLM_SPEND) == LLM
    assert by(EffectClass.MEMORY_WRITE) == MEMORY and by(EffectClass.DESTRUCTIVE_LOCAL) == DESTRUCTIVE
    assert by(EffectClass.NONE) == {"propose_interpretation"}
    assert not by(EffectClass.GPU_SPEND)                       # nothing in the chat can spend on a GPU


@pytest.mark.asyncio
async def test_every_gated_tool_shows_what_it_will_do(build: Callable[..., Built]) -> None:
    for name, sp in tools(build()).items():
        if sp.effect in (EffectClass.MEMORY_WRITE, EffectClass.DESTRUCTIVE_LOCAL, EffectClass.LLM_SPEND):
            assert sp.preview is not None, f"{name} has no confirm preview"


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


def test_chat_imports_only_allowlisted_names_from_the_library() -> None:
    used = _imports_from_visual_generation()
    assert used <= ALLOWED_IMPORTS, f"new imports to review: {sorted(used - ALLOWED_IMPORTS)}"


def test_chat_never_imports_a_spending_or_rendering_module() -> None:
    mods = {m.split(".")[1] for m, _ in _imports_from_visual_generation() if "." in m}
    assert not mods & SPENDING_MODULES


@pytest.mark.asyncio
async def test_running_every_non_write_tool_makes_no_data_write_and_no_spend(
    build: Callable[..., Built], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every read tool, plus propose_interpretation, against stores that record any write; and the
    GPU entry points booby-trapped so any call fails the test. (Write tools are exercised, with
    their gate, in test_tools_writes.py and test_session_offline.py.)"""
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
        "list_evaluations": {},
        "propose_interpretation": {"generation": "attempt-01", "raw_feedback": "f", "reaction": "disliked"},
    }
    for name, kw in args.items():
        r = await t[name].handler(t[name].input_model(**kw))
        assert not r.is_error, (name, r.text)
    assert b.writes == []


QDRANT_TOKENS = ("qdrant", "upsert_raw_points", "set_payload", "._client", "query_by_vector", "retrieve_points",
                 "upsert_points", "delete_by_source")


def test_chat_contains_no_qdrant_client_code() -> None:
    """Owner rule: only visual_generation's own store functions write to its collection."""
    offenders = {}
    for path in Path(chat_pkg.__file__).parent.rglob("*.py"):
        hits = [t for t in QDRANT_TOKENS if t in path.read_text().lower()]
        if hits:
            offenders[path.name] = hits
    assert offenders == {}, offenders


def test_chat_never_calls_a_store_write_method_directly() -> None:
    writes = {"upsert_generation", "upsert_lesson", "upsert_template", "upsert_evaluation", "delete_lesson",
              "update_generation_reaction", "prune_templates_by_name", "upsert_lessons_bulk"}
    called = set()
    for path in Path(chat_pkg.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in writes:
                called.add((path.name, node.attr))
    assert called == set(), called
