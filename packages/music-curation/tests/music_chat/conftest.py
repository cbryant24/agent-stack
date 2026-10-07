"""Fixtures for the chat tests: store doubles that record every attempted write, so confirm /
reject / defer paths are judged by what was (or was not) stored."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from music_curation.chat.state import ChatState
from music_curation.models import (
    Generation,
    ParsedPrompt,
    ParsedSession,
    ParsedSunoFact,
    ParsedTasteLesson,
    ParsedTemplate,
)

STORE_WRITES = ("update_generation_reaction", "upsert_taste", "upsert_taste_bulk", "upsert_templates_bulk",
                "upsert_generations_bulk", "upsert_generation", "upsert_template", "upsert_sound_ref")


class Built:
    def __init__(self, state: ChatState, store: MagicMock, uks: MagicMock, writes: list[tuple[str, Any]],
                 gens: list[Generation]) -> None:
        self.state, self.store, self.uks, self.writes, self.gens = state, store, uks, writes, gens

    def wrote(self, name: str) -> list[Any]:
        return [args for n, args in self.writes if n == name]

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.writes]


def make_gens(n: int, **over: Any) -> list[Generation]:
    return [Generation(entry_id=f"{i:08d}-aaaa-4bbb-8ccc-000000000000", session_id="s", style_field=f"style {i}",
                       suggested_track_title=f"Track {i}", created_at=f"2026-01-01T00:00:{i:02d}+00:00", **over)
            for i in range(1, n + 1)]


def seed_session() -> ParsedSession:
    """One parsed seed file: 2 generations, 3 facts, 1 explicit + 3 inferred taste lessons,
    1 explicit + 2 inferred templates."""
    def taste(text: str, explicit: bool = False) -> ParsedTasteLesson:
        return ParsedTasteLesson(statement=text, valence="positive", scope="production", session_id="cali-chill",
                                 is_explicit=explicit)

    def tmpl(name: str, explicit: bool = False) -> ParsedTemplate:
        return ParsedTemplate(name=name, descriptor=name, style_pattern=f"{name} pattern, 90 BPM",
                              swap_variables=["mood"], is_explicit=explicit)

    return ParsedSession(
        session_id="cali-chill", source_path="/seeds/cali-chill.md",
        prompts=[ParsedPrompt(session_id="cali-chill", name="p1", style_field="lo-fi, 80 BPM", reaction="loved"),
                 ParsedPrompt(session_id="cali-chill", name="p2", style_field="lo-fi, 84 BPM", reaction="disliked")],
        suno_facts=[ParsedSunoFact(statement=f"fact {i}") for i in range(3)],
        taste_lessons=[taste("explicit: no trap hats", True), taste("warm tape saturation"),
                       taste("avoid bright cymbals"), taste("slow intros")],
        templates=[tmpl("explicit-base", True), tmpl("beach-night"), tmpl("rain-drive")],
    )


@pytest.fixture
def build() -> Callable[..., Built]:
    def make(*, gens: list[Generation] | None = None, pending: list[Generation] | None = None) -> Built:
        gens = gens if gens is not None else []
        by_id = {g.entry_id: g for g in gens}
        writes: list[tuple[str, Any]] = []

        store = MagicMock()
        store.ensure_collection = AsyncMock()
        store.get_generation = AsyncMock(side_effect=lambda eid: by_id.get(eid))
        store.list_pending = AsyncMock(side_effect=lambda: list(pending if pending is not None
                                                               else [g for g in gens if g.status == "pending"]))
        store.get_chain = AsyncMock(side_effect=lambda root: [g for g in gens if (g.chain_root_id or g.entry_id) == root])

        def record(name: str) -> AsyncMock:
            async def call(*a: Any, **k: Any) -> None:
                writes.append((name, (a, k)))
                if name == "update_generation_reaction" and a[0] in by_id:
                    by_id[a[0]].reaction, by_id[a[0]].status = a[1], "complete"
            return AsyncMock(side_effect=call)

        for name in STORE_WRITES:
            setattr(store, name, record(name))

        uks = MagicMock()
        uks.ensure_collection = AsyncMock()
        uks.list_drafts = AsyncMock(return_value=[])
        uks.search = AsyncMock(return_value=[])

        async def bulk(entries: list[dict[str, Any]], *, source_ref: str) -> list[str]:
            writes.append(("bulk_load_verified", (entries, source_ref)))
            return [f"entry-{i}" for i in range(len(entries))]

        uks.bulk_load_verified = AsyncMock(side_effect=bulk)
        state = ChatState(store=store, memory_store=MagicMock(), uks=uks)
        return Built(state, store, uks, writes, gens)

    return make
