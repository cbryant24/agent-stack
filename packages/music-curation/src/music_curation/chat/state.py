from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime import MemoryStore, UserKnowledgeStore, get_memory_store
from agent_shell.proposals import Proposal

from music_curation.models import Generation
from music_curation.store import MusicCurationStore


@dataclass
class ChatState:
    """Per-session state shared by the tools.

    Stores are created once, lazily, so every tool call in a session reuses one client on the
    shell's event loop. `seen` remembers the generations tool results have shown, so the director
    can refer to one by a short id prefix."""

    store: MusicCurationStore | None = None
    memory_store: MemoryStore | None = None
    uks: UserKnowledgeStore | None = None
    session: Any = None
    seen: dict[str, str] = field(default_factory=dict)          # generation id -> title
    proposals: dict[str, Proposal] = field(default_factory=dict)
    _ready: bool = field(default=False, repr=False)

    def stores(self) -> tuple[MusicCurationStore, MemoryStore, UserKnowledgeStore]:
        if not self._ready:
            self.memory_store = self.memory_store or get_memory_store()
            self.store = self.store or MusicCurationStore(self.memory_store)
            self.uks = self.uks or UserKnowledgeStore(self.memory_store)
            self._ready = True
        assert self.store is not None and self.memory_store is not None and self.uks is not None
        return self.store, self.memory_store, self.uks

    def remember(self, gens: list[Generation]) -> None:
        for g in gens:
            self.seen[g.entry_id] = g.suggested_track_title or ""

    # ── proposals awaiting a write (offered again at /exit) ───────────────────

    def propose(self, key: str, proposal: Proposal) -> None:
        self.proposals[key] = proposal

    def written(self, key: str) -> None:
        self.proposals.pop(key, None)

    def unwritten_proposals(self) -> list[Proposal]:
        return list(self.proposals.values())


def reaction_key(gen_id: str) -> str:
    return "reaction:" + gen_id


def taste_key(statement: str) -> str:
    return "taste:" + statement.strip().lower()
