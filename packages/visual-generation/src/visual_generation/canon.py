"""Deterministic per-project canon — the one place advisory isn't enough.

Locked identity descriptors (e.g. the narrator's hair) must reach the rendered
prompt regardless of LLM discretion. Retrieval surfaces canon as *advisory* context
(`[PROJECT CANON]`); this module *guarantees* it: `enforce_canon` rewrites the
crafted prompt in code — expanding `@alias` tokens, injecting the locked descriptor
wherever a subject is named, and stripping phrasings the canon forbids.

The canon for a project is a plain JSON file (looked up by exact `project` slug,
never embedded or semantically searched) — the `ModelRegistry` pattern. Enforcement
is always advisory in spirit (it shapes the prompt text; it never blocks a render)
and a no-op when a project has no canon file.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field

from agent_runtime import get_config


class CanonSubject(BaseModel):
    """One locked subject: the aliases that name it, the canonical descriptor that
    must appear, and phrasings that contradict canon and must be stripped.

    An alias beginning with ``@`` is a *token* that expands in place to the locked
    descriptor; a plain alias (e.g. "the narrator") triggers injection of the locked
    descriptor when it's named but the canonical text isn't already present."""

    aliases: list[str]
    locked: str
    forbid: list[str] = Field(default_factory=list)


def _default_canon_dir() -> Path:
    return get_config().agent_data_dir / "visual-generation" / "canon"


class ProjectCanon:
    """JSON-backed canon store for one project slug.

    File: ``<canon_dir>/<project>.json`` = ``{"subjects": [CanonSubject, ...]}``.
    Subjects are keyed by their primary alias (``aliases[0]``) for upsert/remove.
    """

    def __init__(self, project: str, base_dir: Path | None = None) -> None:
        self._project = project
        self._dir = base_dir or _default_canon_dir()
        self._path = self._dir / f"{project}.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[CanonSubject]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [CanonSubject(**s) for s in raw.get("subjects", [])]

    def _write(self, subjects: list[CanonSubject]) -> None:
        """Atomically rewrite (temp file then rename) — a crash can't truncate it."""
        self._dir.mkdir(parents=True, exist_ok=True)
        data = {"subjects": [s.model_dump() for s in subjects]}
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def set_subject(
        self, aliases: list[str], locked: str, forbid: list[str] | None = None
    ) -> CanonSubject:
        """Upsert a subject (keyed by its primary alias, case-insensitively)."""
        if not aliases:
            raise ValueError("a canon subject needs at least one alias")
        key = aliases[0].lower()
        subjects = [s for s in self.load() if not (s.aliases and s.aliases[0].lower() == key)]
        subject = CanonSubject(aliases=aliases, locked=locked, forbid=forbid or [])
        subjects.append(subject)
        self._write(subjects)
        return subject

    def remove(self, alias: str) -> bool:
        """Remove the subject any of whose aliases match `alias`. Returns whether one went."""
        subjects = self.load()
        target = alias.lower()
        kept = [s for s in subjects if target not in [a.lower() for a in s.aliases]]
        if len(kept) == len(subjects):
            return False
        self._write(kept)
        return True


def _tidy(prompt: str) -> str:
    """Clean up doubled spaces/commas left by stripping forbidden phrases."""
    prompt = re.sub(r"\s{2,}", " ", prompt)
    prompt = re.sub(r"\s+([,.])", r"\1", prompt)
    prompt = re.sub(r"(,\s*){2,}", ", ", prompt)
    return prompt.strip().strip(",").strip()


def enforce_canon(
    prompt: str, project: str | None, *, base_dir: Path | None = None
) -> tuple[str, list[str]]:
    """Rewrite `prompt` to honor the project's locked canon. Returns (prompt, applied).

    Deterministic, no LLM. For each subject named in the prompt: expand any ``@alias``
    token to the locked descriptor, inject the locked descriptor when a plain alias is
    named but the canonical text is absent, and strip any forbidden phrasing. `applied`
    is a human-readable list of what was changed (empty = no-op). A project with no
    canon file is a no-op."""
    if not project:
        return prompt, []
    subjects = ProjectCanon(project, base_dir=base_dir).load()
    if not subjects:
        return prompt, []

    applied: list[str] = []
    for subj in subjects:
        locked = subj.locked
        present = locked.lower() in prompt.lower()
        plain_match: str | None = None

        for alias in subj.aliases:
            if alias.startswith("@"):
                token = re.compile(re.escape(alias), re.IGNORECASE)
                if token.search(prompt):
                    prompt = token.sub(locked, prompt)
                    applied.append(f"expanded '{alias}' → canonical descriptor")
                    present = True
            elif re.search(rf"\b{re.escape(alias)}\b", prompt, re.IGNORECASE):
                plain_match = plain_match or alias

        if plain_match and not present:
            prompt = f"{prompt.rstrip().rstrip(',.')}, {locked}"
            applied.append(f"injected canon for '{plain_match}'")
            present = True

        if present:
            for bad in subj.forbid:
                bad_re = re.compile(re.escape(bad), re.IGNORECASE)
                if bad_re.search(prompt):
                    prompt = bad_re.sub("", prompt)
                    applied.append(f"removed forbidden phrasing '{bad}'")

    if applied:
        prompt = _tidy(prompt)
    return prompt, applied
