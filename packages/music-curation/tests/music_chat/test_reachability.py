"""The chat tool pack: its exact tool set and effect classes, every write a gated tool with a
preview, and no store-write or Qdrant code inside chat/."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_shell.tools.registry import EffectClass

import music_curation.chat as chat_pkg
from music_curation.chat.tools import tool_pack

from .conftest import Built  # type: ignore[import-not-found]

READS = {"recall", "review_pending", "chain_show", "seed_preview", "taste_queue", "knowledge_drafts", "knowledge_search"}
LLM = {"generate"}
MEMORY = {"report", "taste_add", "fact_add", "seed_ingest", "taste_queue_decide", "knowledge_confirm", "knowledge_reject"}
EXPECTED = READS | LLM | MEMORY | {"propose_reaction"}

# Every name chat/ may import from the rest of music_curation. Adding to this list is the review
# point: memory writes appear only as the library's own functions, never as store calls.
ALLOWED_IMPORTS = {
    ("music_curation.agent", "curate"),
    ("music_curation.constants", "POSITIVE_REACTIONS"),
    *{("music_curation.curation", n) for n in ("add_fact", "add_taste", "record_reaction")},
    *{("music_curation.models", n) for n in (
        "Generation", "ParsedSession", "ParsedTasteLesson", "ParsedTemplate", "TastePendingDraft")},
    *{("music_curation.reads", n) for n in ("render_chain", "render_pending", "render_recall", "render_result")},
    ("music_curation.retrieval", "retrieve_context"),
    *{("music_curation.seed_ingestion", n) for n in (
        "QueueDecision", "defer_draft", "edited_lesson", "ingest_seed", "list_taste_queue", "plan_seed",
        "review_taste_queue")},
    ("music_curation.store", "MusicCurationStore"),
}
STORE_WRITE_METHODS = {"update_generation_reaction", "upsert_taste", "upsert_taste_bulk", "upsert_templates_bulk",
                       "upsert_generations_bulk", "upsert_generation", "upsert_template", "upsert_sound_ref",
                       "bulk_load_verified", "confirm_entry", "reject_entry", "remediate", "migrate_approved_to_liked"}
QDRANT_TOKENS = ("qdrant", "upsert_raw_points", "set_payload", "._client", "query_by_vector", "retrieve_points")


def tools(b: Built) -> dict[str, Any]:
    return {t.name: t for t in tool_pack(b.state)}


def test_the_tool_set_is_exactly_the_expected_one(build: Callable[..., Built]) -> None:
    assert set(tools(build())) == EXPECTED


def test_effect_classes(build: Callable[..., Built]) -> None:
    t = tools(build())
    by = lambda eff: {n for n, sp in t.items() if sp.effect is eff}  # noqa: E731
    assert by(EffectClass.READ) == READS and by(EffectClass.LLM_SPEND) == LLM
    assert by(EffectClass.MEMORY_WRITE) == MEMORY and by(EffectClass.NONE) == {"propose_reaction"}
    assert not by(EffectClass.GPU_SPEND) and not by(EffectClass.DESTRUCTIVE_LOCAL)   # Suno has no API to spend on


def test_every_gated_tool_shows_what_it_will_do(build: Callable[..., Built]) -> None:
    for name, sp in tools(build()).items():
        if sp.effect in (EffectClass.MEMORY_WRITE, EffectClass.LLM_SPEND):
            assert sp.preview is not None, f"{name} has no confirm preview"


def _sources() -> list[Path]:
    return list(Path(chat_pkg.__file__).parent.rglob("*.py"))


def test_chat_imports_only_allowlisted_names_from_the_library() -> None:
    used: set[tuple[str, str]] = set()
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                mod = node.module or ""
                if mod.startswith("music_curation") and not mod.startswith("music_curation.chat"):
                    used |= {(mod, a.name) for a in node.names}
            elif isinstance(node, ast.Import):
                used |= {(a.name, "*") for a in node.names
                         if a.name.startswith("music_curation") and not a.name.startswith("music_curation.chat")}
    assert used <= ALLOWED_IMPORTS, f"new imports to review: {sorted(used - ALLOWED_IMPORTS)}"


def test_chat_never_calls_a_store_write_method_directly() -> None:
    called = set()
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in STORE_WRITE_METHODS:
                called.add((path.name, node.attr))
    assert called == set(), called


def test_chat_contains_no_qdrant_client_code() -> None:
    offenders = {p.name: [t for t in QDRANT_TOKENS if t in p.read_text().lower()] for p in _sources()}
    assert {k: v for k, v in offenders.items() if v} == {}
