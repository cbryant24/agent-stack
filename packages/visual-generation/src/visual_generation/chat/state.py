from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime import MemoryStore, get_memory_store
from agent_runtime.config import RuntimeConfig, get_config, project_dir
from agent_shell.proposals import Proposal

from visual_generation.store import VisualGenerationStore

BATCH_FILENAME = "visual-batch.md"   # type-only name, docs/naming-conventions.md


@dataclass
class ChatState:
    """Per-session state shared by the tools.

    Stores are created once, lazily, so every tool call in a session reuses one client on the
    shell's event loop (the library's `*_sync` helpers call asyncio.run, which cannot run here).
    """

    project: str | None = None
    config: RuntimeConfig | None = None
    store: VisualGenerationStore | None = None
    memory_store: MemoryStore | None = None
    # The agent-shell Session this state belongs to (set by run_chat); read for the session id and
    # the current engine, which can change when the director switches provider.
    session: Any = None
    # Proposals made this session and not yet written; offered again at /exit.
    proposals: dict[str, Proposal] = field(default_factory=dict)
    _stores_ready: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = get_config()
        if self.project is not None:
            project_dir(self.project, self.config)       # validates the slug up front

    @property
    def projects_dir(self) -> Path:
        assert self.config is not None
        return self.config.agent_projects_dir

    def stores(self) -> tuple[VisualGenerationStore, MemoryStore]:
        if not self._stores_ready:
            self.memory_store = self.memory_store or get_memory_store()
            self.store = self.store or VisualGenerationStore(self.memory_store)
            self._stores_ready = True
        assert self.store is not None and self.memory_store is not None
        return self.store, self.memory_store

    def batch_path(self, project: str | None = None) -> Path:
        """`<projects>/<slug>/visual-batch.md`. Raises ValueError without a valid project."""
        slug = project or self.project
        if not slug:
            raise ValueError("no project: start the chat with --project <slug> or pass `project`")
        return project_dir(slug, self.config) / BATCH_FILENAME

    # ── session facts for evaluation records ─────────────────────────────────

    @property
    def session_id(self) -> str:
        return str(getattr(self.session, "session_id", "") or "")

    @property
    def engine_provider(self) -> str:
        return str(getattr(getattr(self.session, "engine", None), "provider", "") or "")

    @property
    def engine_model(self) -> str:
        return str(getattr(getattr(self.session, "engine", None), "model", "") or "")

    # ── proposals awaiting a write ────────────────────────────────────────────

    def propose(self, key: str, proposal: Proposal) -> None:
        self.proposals[key] = proposal

    def written(self, key: str) -> None:
        self.proposals.pop(key, None)

    def unwritten_proposals(self) -> list[Proposal]:
        return list(self.proposals.values())


def lesson_key(statement: str) -> str:
    return "lesson:" + hashlib.sha1(statement.strip().lower().encode()).hexdigest()[:16]


def evaluation_key(entry_id: str) -> str:
    return "evaluation:" + entry_id
