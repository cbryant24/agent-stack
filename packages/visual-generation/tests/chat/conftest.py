"""Fixtures for the chat tests: stores that fail loudly on any data write, or (allow_writes=True)
record every write so confirm / reject / defer paths can be asserted by what was stored."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime.config import get_config, reset_config
from visual_generation.chat.state import ChatState
from visual_generation.models import (
    EvaluationEntry,
    TechniqueLesson,
    VisualGeneration,
    WorkflowTemplate,
)

def qdrant_reachable() -> bool:
    try:
        import httpx

        return httpx.get("http://localhost:6333/healthz", timeout=1.0).status_code == 200
    except Exception:
        return False


QDRANT_UP = qdrant_reachable()
requires_qdrant = pytest.mark.skipif(
    not QDRANT_UP, reason="Qdrant not running at localhost:6333: real-Qdrant evaluation tests skipped"
)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not QDRANT_UP:
        terminalreporter.write_line(
            "NOTE: Qdrant is not running at localhost:6333, so tests/chat/test_qdrant_counts.py was "
            "SKIPPED (confirm/reject/edit/defer point-count checks did not run). "
            "Start it with: docker compose -f infrastructure/docker-compose.yml up -d",
            yellow=True,
        )


STORE_WRITES = (
    "upsert_generation", "upsert_generations_bulk", "update_generation_reaction", "upsert_lesson",
    "upsert_lessons_bulk", "delete_lesson", "prune_templates_by_name", "upsert_template",
    "upsert_templates_bulk", "upsert_evaluation",
)
MEMORY_WRITES = (
    "upsert_raw_points", "set_payload", "upsert_points", "upsert_multimodal_points",
    "upsert_mixed", "delete_by_source",
)


class Built:
    """A ChatState plus the doubles behind it.

    `writes` lists the names of every attempted data write. With `allow_writes`, writes succeed and
    land in `gens`, `lessons`, `evals` and `templates`, so tests can assert what was stored."""

    def __init__(self, state: ChatState, store: MagicMock, memory: MagicMock, writes: list[str],
                 gens: list[VisualGeneration], lessons: list[TechniqueLesson],
                 evals: list[EvaluationEntry], templates: list[WorkflowTemplate]) -> None:
        self.state, self.store, self.memory, self.writes = state, store, memory, writes
        self.gens, self.lessons, self.evals, self.templates = gens, lessons, evals, templates
        self.projects_dir = state.projects_dir


def make_gens(n: int, project: str = "demo") -> list[VisualGeneration]:
    return [
        VisualGeneration(
            caption=f"shot {i}", prompt=f"prompt {i}", project=project,
            created_at=f"2026-01-01T00:00:{i:02d}+00:00",
        )
        for i in range(1, n + 1)
    ]


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Built]:
    monkeypatch.setenv("AGENT_PROJECTS_DIR", str(tmp_path / "projects"))
    reset_config()

    def make(
        project: str | None = "demo",
        *,
        gens: list[VisualGeneration] | None = None,
        pending: list[VisualGeneration] | None = None,
        lessons: list[TechniqueLesson] | None = None,
        templates: list[WorkflowTemplate] | None = None,
        evals: list[EvaluationEntry] | None = None,
        by_id: dict[str, VisualGeneration] | None = None,
        allow_writes: bool = False,
    ) -> Built:
        gens = gens if gens is not None else []
        lessons = lessons if lessons is not None else []
        templates = templates if templates is not None else []
        evals = evals if evals is not None else []
        by_id = by_id if by_id is not None else {g.entry_id: g for g in gens}
        writes: list[str] = []

        store = MagicMock()
        store.ensure_collection = AsyncMock()
        store.list_generations = AsyncMock(
            side_effect=lambda *, project=None: [g for g in gens if project is None or g.project == project]
        )
        store.get_generation = AsyncMock(side_effect=lambda eid: by_id.get(eid))
        store.get_chain = AsyncMock(side_effect=lambda root: [g for g in gens if g.chain_root_id == root])
        store.list_pending = AsyncMock(return_value=pending or [])
        store.list_lessons = AsyncMock(
            side_effect=lambda *, confirmed_only=True, scope=None, valence=None: [
                le for le in lessons if (le.confirmed or not confirmed_only)
                and (scope is None or le.scope == scope) and (valence is None or le.valence == valence)]
        )
        store.get_lesson = AsyncMock(side_effect=lambda eid: next((le for le in lessons if le.entry_id == eid), None))
        store.search_generations = AsyncMock(side_effect=lambda *a, **k: [(g.entry_id, 0.9, g) for g in gens])
        store.search_lessons = AsyncMock(side_effect=lambda *a, **k: [(le.entry_id, 0.8, le) for le in lessons])
        store.search_templates = AsyncMock(side_effect=lambda *a, **k: [(t.entry_id, 0.7, t) for t in templates])
        store.search_evaluations = AsyncMock(side_effect=lambda *a, **k: [(e.entry_id, 0.6, e) for e in evals])
        store.list_evaluations = AsyncMock(
            side_effect=lambda *, gen_id=None, chain_root_id=None, project=None: [
                e for e in evals if (gen_id is None or e.gen_id == gen_id)
                and (chain_root_id is None or e.chain_root_id == chain_root_id)
                and (project is None or e.project == project)]
        )
        store.get_evaluation = AsyncMock(side_effect=lambda eid: next((e for e in evals if e.entry_id == eid), None))

        memory = MagicMock()
        memory.count_points = AsyncMock(return_value=0)

        def attempted(name: str, effect: Callable[..., Any] | None = None) -> AsyncMock:
            async def call(*a: Any, **k: Any) -> None:
                writes.append(name)
                if allow_writes and effect is not None:
                    effect(*a, **k)
            return AsyncMock(side_effect=call)

        def upsert_eval(e: EvaluationEntry) -> None:
            evals[:] = [x for x in evals if x.entry_id != e.entry_id] + [e]

        def upsert_lesson(le: TechniqueLesson) -> None:
            lessons.append(le)

        def delete_lesson(eid: str) -> None:
            lessons[:] = [le for le in lessons if le.entry_id != eid]

        def react(eid: str, reaction: str, **k: Any) -> None:
            g = by_id.get(eid)
            if g is not None:
                g.reaction = reaction
                g.rating = k.get("rating")
                g.notes = k.get("notes")
                g.context = k.get("context")

        def upsert_template(t: WorkflowTemplate) -> None:
            templates.append(t)

        effects = {"upsert_evaluation": upsert_eval, "upsert_lesson": upsert_lesson,
                   "delete_lesson": delete_lesson, "update_generation_reaction": react,
                   "upsert_template": upsert_template}
        for name in STORE_WRITES:
            setattr(store, name, attempted(name, effects.get(name)))
        for name in MEMORY_WRITES:
            setattr(memory, name, attempted("memory." + name))
        state = ChatState(project=project, config=get_config(), store=store, memory_store=memory)
        return Built(state, store, memory, writes, gens, lessons, evals, templates)

    yield make
    reset_config()
