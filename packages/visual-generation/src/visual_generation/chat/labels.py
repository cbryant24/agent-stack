from __future__ import annotations

import re
from dataclasses import dataclass

from visual_generation.models import VisualGeneration

_ATTEMPT = re.compile(r"^(?:attempt[-_ ]?|#)0*(\d+)$")
MIN_PREFIX = 8


@dataclass(frozen=True)
class Resolution:
    gen_id: str | None
    reason: str = ""            # why it did not resolve (shown to the user, never guessed around)


class LabelResolver:
    """Turns "attempt-07" (and a few other spellings) into a generation id.

    Attempts are the project's generations ordered oldest first, numbered from 1. Also
    accepted: `latest`/`last`, a full entry id, and a unique entry-id prefix of 8+ characters.
    Anything else is unresolved: the caller records an open question; an id is never guessed.
    """

    def __init__(self, generations: list[VisualGeneration]) -> None:
        self._gens = sorted(generations, key=lambda g: (g.created_at, g.entry_id))

    def __len__(self) -> int:
        return len(self._gens)

    def name_of(self, gen_id: str) -> str | None:
        for i, g in enumerate(self._gens, 1):
            if g.entry_id == gen_id:
                return f"attempt-{i:02d}"
        return None

    def display(self, gen_id: str) -> str:
        """`attempt-07 (a1b2c3d4)` for a generation in this project, else the short id."""
        name = self.name_of(gen_id)
        return f"{name} ({gen_id[:8]})" if name else gen_id[:8]

    def resolve(self, label: str | None) -> Resolution:
        raw = (label or "").strip()
        if not raw:
            return Resolution(None, "empty label")
        key = raw.lower()

        if key in ("latest", "last"):
            if not self._gens:
                return Resolution(None, "no generations in this project yet")
            return Resolution(self._gens[-1].entry_id)

        m = _ATTEMPT.match(key)
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(self._gens):
                return Resolution(self._gens[n - 1].entry_id)
            return Resolution(None, f"there are {len(self._gens)} attempt(s) in this project, no {raw!r}")

        exact = [g.entry_id for g in self._gens if g.entry_id.lower() == key]
        if exact:
            return Resolution(exact[0])
        if len(key) >= MIN_PREFIX:
            hits = [g.entry_id for g in self._gens if g.entry_id.lower().startswith(key)]
            if len(hits) == 1:
                return Resolution(hits[0])
            if len(hits) > 1:
                return Resolution(None, f"{raw!r} matches {len(hits)} generations; use more characters")
        return Resolution(None, f"{raw!r} is not an attempt label or a known generation id")
