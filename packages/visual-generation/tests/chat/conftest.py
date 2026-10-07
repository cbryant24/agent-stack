"""Fixtures for the chat tests: stores that fail loudly on any data write."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime.config import get_config, reset_config
from visual_generation.chat.state import ChatState
from visual_generation.models import TechniqueLesson, VisualGeneration, WorkflowTemplate

STORE_WRITES = (
    "upsert_generation", "upsert_generations_bulk", "update_generation_reaction", "upsert_lesson",
    "upsert_lessons_bulk", "delete_lesson", "prune_templates_by_name", "upsert_template",
    "upsert_templates_bulk",
)
MEMORY_WRITES = (
    "upsert_raw_points", "set_payload", "upsert_points", "upsert_multimodal_points",
    "upsert_mixed", "delete_by_source",
)


class Built:
    """A ChatState plus the doubles behind it and the record of attempted data writes."""

    def __init__(self, state: ChatState, store: MagicMock, memory: MagicMock, writes: list[str]) -> None:
        self.state, self.store, self.memory, self.writes = state, store, memory, writes
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
        by_id: dict[str, VisualGeneration] | None = None,
    ) -> Built:
        gens = gens if gens is not None else []
        writes: list[str] = []
        by_id = by_id or {g.entry_id: g for g in gens}
        store = MagicMock()
        store.ensure_collection = AsyncMock()
        store.list_generations = AsyncMock(
            side_effect=lambda *, project=None: [g for g in gens if project is None or g.project == project]
        )
        store.get_generation = AsyncMock(side_effect=lambda eid: by_id.get(eid))
        store.get_chain = AsyncMock(side_effect=lambda root: [g for g in gens if g.chain_root_id == root])
        store.list_pending = AsyncMock(return_value=pending or [])
        store.list_lessons = AsyncMock(return_value=lessons or [])
        store.search_generations = AsyncMock(return_value=[(g.entry_id, 0.9, g) for g in gens])
        store.search_lessons = AsyncMock(return_value=[(le.entry_id, 0.8, le) for le in (lessons or [])])
        store.search_templates = AsyncMock(return_value=[(t.entry_id, 0.7, t) for t in (templates or [])])
        memory = MagicMock()
        memory.count_points = AsyncMock(return_value=0)
        for name in STORE_WRITES:
            setattr(store, name, AsyncMock(side_effect=lambda *a, _n=name, **k: writes.append(_n)))
        for name in MEMORY_WRITES:
            setattr(memory, name, AsyncMock(side_effect=lambda *a, _n=name, **k: writes.append(_n)))
        state = ChatState(project=project, config=get_config(), store=store, memory_store=memory)
        return Built(state, store, memory, writes)

    yield make
    reset_config()
