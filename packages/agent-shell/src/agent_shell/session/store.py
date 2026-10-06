from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_shell_sessions (
    id TEXT PRIMARY KEY, agent TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_shell_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS agent_shell_messages_session ON agent_shell_messages(session_id);
CREATE TABLE IF NOT EXISTS agent_shell_handles (
    session_id TEXT NOT NULL, provider TEXT NOT NULL, handle TEXT NOT NULL,
    PRIMARY KEY (session_id, provider)
);
"""


class SessionInfo(BaseModel):
    id: str
    agent: str
    title: str
    provider: str
    model: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    """Neutral transcript plus per-provider native handles, in agent-stack.db.

    Only touches tables prefixed agent_shell_; LangGraph's tables are left alone.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Databases made by the first shell version lack the `meta` column."""
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(agent_shell_messages)")}
        if "meta" not in cols:
            self._db.execute("ALTER TABLE agent_shell_messages ADD COLUMN meta TEXT")

    def close(self) -> None:
        self._db.close()

    def create(self, session_id: str, agent: str, provider: str, model: str) -> None:
        now = _now()
        self._db.execute(
            "INSERT OR IGNORE INTO agent_shell_sessions VALUES (?,?,?,?,?,?,?)",
            (session_id, agent, "", provider, model, now, now),
        )
        self._db.commit()

    def touch(self, session_id: str, provider: str, model: str) -> None:
        self._db.execute(
            "UPDATE agent_shell_sessions SET provider=?, model=?, updated_at=? WHERE id=?",
            (provider, model, _now(), session_id),
        )
        self._db.commit()

    def exists(self, session_id: str) -> bool:
        r = self._db.execute("SELECT 1 FROM agent_shell_sessions WHERE id=?", (session_id,))
        return r.fetchone() is not None

    def add_message(
        self, session_id: str, role: str, content: str, meta: dict[str, Any] | None = None
    ) -> int:
        """Append a message. `meta` carries tool_calls (assistant) or tool_call_id/name/is_error (tool)."""
        cur = self._db.execute(
            "INSERT INTO agent_shell_messages (session_id, role, content, created_at, meta) "
            "VALUES (?,?,?,?,?)",
            (session_id, role, content, _now(), json.dumps(meta) if meta else None),
        )
        self._db.commit()
        return int(cur.lastrowid or 0)

    def update_meta(self, message_id: int, meta: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE agent_shell_messages SET meta=? WHERE id=?", (json.dumps(meta), message_id)
        )
        self._db.commit()

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT role, content, meta FROM agent_shell_messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            msg: dict[str, Any] = {"role": r["role"], "content": r["content"]}
            if r["meta"]:
                msg.update(json.loads(r["meta"]))
            out.append(msg)
        return out

    def set_handle(self, session_id: str, provider: str, handle: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO agent_shell_handles VALUES (?,?,?)",
            (session_id, provider, handle),
        )
        self._db.commit()

    def handle(self, session_id: str, provider: str) -> str | None:
        r = self._db.execute(
            "SELECT handle FROM agent_shell_handles WHERE session_id=? AND provider=?",
            (session_id, provider),
        ).fetchone()
        return r["handle"] if r else None

    def rename(self, session_id: str, title: str) -> None:
        self._db.execute("UPDATE agent_shell_sessions SET title=? WHERE id=?", (title, session_id))
        self._db.commit()

    def list(self, agent: str | None = None, limit: int = 20) -> list[SessionInfo]:
        q = "SELECT * FROM agent_shell_sessions"
        params: tuple[object, ...] = ()
        if agent:
            q += " WHERE agent=?"
            params = (agent,)
        q += " ORDER BY updated_at DESC LIMIT ?"
        rows = self._db.execute(q, (*params, limit)).fetchall()
        return [SessionInfo(**{k: r[k] for k in SessionInfo.model_fields}) for r in rows]
