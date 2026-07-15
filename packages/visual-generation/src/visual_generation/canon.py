"""Per-project canon — a deterministic subject registry.

A canon subject is the set of aliases that name it, an optional pinned
character LoRA (model-level identity — part of the deprecated single-LoRA
ideation path), and asset-reference fields aligned with the shared shot schema
(docs/shared-shot-schema.md): ``id``, ``reference_pack``, ``wardrobe``,
``hair``, ``region``. Canon surfaces the scene's cast into composition and
pins character LoRAs deterministically at draft/redraft; it does NOT rewrite
prompt text. (The locked-descriptor injection and forbid-stripping that once
lived here were removed per the consolidated Coraline audit §5/§11 — text
canon was a prompt macro, not an identity authority.)

The canon for a project is a plain JSON file (looked up by exact `project`
slug, never embedded or semantically searched) — the `ModelRegistry` pattern.
Legacy files carrying ``locked``/``forbid`` fields load without error and
round-trip those fields untouched; nothing reads them.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_runtime import get_config

from visual_generation.models import LoraRef


class CanonSubject(BaseModel):
    """One canon subject: the aliases that name it, an optional pinned character
    LoRA, and versioned asset references.

    `lora` is the optional *character LoRA* that carries this subject's identity at
    the model level (a registered, usually `identity_bearing` asset) — the
    deprecated single-LoRA ideation path. When the subject is present in a scene
    (named by alias), this LoRA is pinned into the stack deterministically.

    The asset-reference fields point at versioned production assets per the shared
    shot schema (`id` e.g. ``celeste_v1``, `reference_pack`, `wardrobe`, `hair`,
    `region`). They are pipeline metadata — never prompt prose.

    Legacy ``locked``/``forbid`` keys from older canon files are tolerated as
    pydantic extras and round-trip through load/save unread (``extra="allow"``)."""

    model_config = ConfigDict(extra="allow")

    aliases: list[str]
    lora: LoraRef | None = None
    id: str | None = None
    reference_pack: str | None = None
    wardrobe: str | None = None
    hair: str | None = None
    region: str | None = None


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
        self,
        aliases: list[str],
        *,
        lora: LoraRef | None = None,
        id: str | None = None,
        reference_pack: str | None = None,
        wardrobe: str | None = None,
        hair: str | None = None,
        region: str | None = None,
    ) -> CanonSubject:
        """Upsert a subject (keyed by its primary alias, case-insensitively).

        REPLACES the whole subject — legacy ``locked``/``forbid`` extras on a
        replaced subject are dropped. Use `update_subject` for surgical edits
        that preserve them."""
        if not aliases:
            raise ValueError("a canon subject needs at least one alias")
        key = aliases[0].lower()
        subjects = [s for s in self.load() if not (s.aliases and s.aliases[0].lower() == key)]
        subject = CanonSubject(
            aliases=aliases,
            lora=lora,
            id=id,
            reference_pack=reference_pack,
            wardrobe=wardrobe,
            hair=hair,
            region=region,
        )
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

    def update_subject(
        self,
        selector: str,
        *,
        add_aliases: list[str] | None = None,
        remove_aliases: list[str] | None = None,
        lora: LoraRef | None = None,
        clear_lora: bool = False,
        id: str | None = None,
        reference_pack: str | None = None,
        wardrobe: str | None = None,
        hair: str | None = None,
        region: str | None = None,
    ) -> CanonSubject:
        """Edit ONE field-set of an existing subject in place — without restating the rest.

        `selector` matches the subject by ANY of its aliases (case-insensitive). Only
        the named edits apply; everything else — including legacy ``locked``/``forbid``
        extras — is preserved (the update is a ``model_copy``). For the string asset
        fields (`id`, `reference_pack`, `wardrobe`, `hair`, `region`), ``None`` leaves
        the field untouched and an empty string clears it. `lora` sets/replaces the
        pinned character LoRA; `clear_lora` removes it (mutually exclusive with
        `lora`). The complement to `set_subject`, which replaces a whole subject —
        this is the surgical edit. Raises ValueError if no subject matches, or if an
        edit would leave the subject with zero aliases."""
        if lora is not None and clear_lora:
            raise ValueError("pass either a new lora or clear_lora, not both")
        subjects = self.load()
        sel = selector.lower()
        idx = next(
            (i for i, s in enumerate(subjects) if sel in [a.lower() for a in s.aliases]), None
        )
        if idx is None:
            known = "; ".join(", ".join(s.aliases) for s in subjects) or "(none)"
            raise ValueError(f"No canon subject matches {selector!r}. Known aliases: {known}")

        s = subjects[idx]
        aliases = list(s.aliases)
        for a in add_aliases or []:
            if a.lower() not in [x.lower() for x in aliases]:
                aliases.append(a)
        if remove_aliases:
            drop = {a.lower() for a in remove_aliases}
            aliases = [a for a in aliases if a.lower() not in drop]
        if not aliases:
            raise ValueError("a subject must keep at least one alias")

        updates: dict[str, object] = {"aliases": aliases}
        if clear_lora:
            updates["lora"] = None
        elif lora is not None:
            updates["lora"] = lora
        for field, value in (
            ("id", id),
            ("reference_pack", reference_pack),
            ("wardrobe", wardrobe),
            ("hair", hair),
            ("region", region),
        ):
            if value is not None:
                updates[field] = value or None  # empty string clears the field

        # model_copy preserves pydantic extras (legacy locked/forbid) untouched.
        updated = s.model_copy(update=updates)
        # Guard against the new primary alias colliding with a different subject's key.
        new_key = aliases[0].lower()
        for j, other in enumerate(subjects):
            if j != idx and other.aliases and other.aliases[0].lower() == new_key:
                raise ValueError(
                    f"alias {aliases[0]!r} would collide with another subject's key"
                )
        subjects[idx] = updated
        self._write(subjects)
        return updated


def _alias_set(subj: CanonSubject) -> set[str]:
    """A subject's aliases lower-cased, with and without a leading ``@`` (so a selector
    like ``narrator`` matches the legacy token alias ``@narrator``)."""
    return {a.lower() for a in subj.aliases} | {a.lower().lstrip("@") for a in subj.aliases}


def subjects_matching(
    selectors: list[str], project: str | None, *, base_dir: Path | None = None
) -> list[CanonSubject]:
    """The canon subjects any of whose aliases match one of `selectors` (the `--canon`
    force selectors, fed into the compose-time cast and forced LoRA pins). Empty for
    no project / no canon / no selectors / no match."""
    if not project or not selectors:
        return []
    wanted = {s.lower() for s in selectors}
    return [
        subj
        for subj in ProjectCanon(project, base_dir=base_dir).load()
        if wanted & _alias_set(subj)
    ]


def _subject_present(prompt: str, subj: CanonSubject) -> bool:
    """True if any of `subj`'s aliases is named in `prompt` (word-boundary,
    case-insensitive; a legacy ``@`` alias prefix is ignored)."""
    for alias in subj.aliases:
        plain = alias[1:] if alias.startswith("@") else alias
        if plain and re.search(rf"\b{re.escape(plain)}\b", prompt, re.IGNORECASE):
            return True
    return False


def scene_cast(
    scene_text: str, project: str | None, *, base_dir: Path | None = None
) -> list[CanonSubject]:
    """Canon subjects whose aliases are named in `scene_text` (e.g. a scene's narration).

    Makes canon an *input* to composition: when the director's scene text names a
    subject, the craft step is told to render that subject by name — so the character
    reaches the prompt at compose time (and `canon_loras_for` then pins its LoRA on
    the alias) instead of being silently dropped. No project / no canon file / empty
    text → []."""
    if not project or not scene_text:
        return []
    return [
        s
        for s in ProjectCanon(project, base_dir=base_dir).load()
        if _subject_present(scene_text, s)
    ]


def canon_loras_for(
    prompt: str,
    project: str | None,
    *,
    base_dir: Path | None = None,
    force: Sequence[str] = (),
) -> list[LoraRef]:
    """Return the character LoRAs canon pins for the subjects present in `prompt`.

    The one deterministic canon channel: a subject the prompt names by alias — or a
    subject FORCED via a `--canon` selector even when the prompt doesn't name it —
    brings its registered character LoRA, so model-level identity travels with the
    subject. Call after craft and merge into the spec's `lora_stack` (dedupe by
    name; canon strength wins over the LLM's guess). A project with no canon file,
    or subjects without a `lora`, yields an empty list."""
    if not project:
        return []
    forced = {f.lower() for f in force}
    loras: list[LoraRef] = []
    for subj in ProjectCanon(project, base_dir=base_dir).load():
        if subj.lora is None:
            continue
        if _subject_present(prompt, subj) or (forced & _alias_set(subj)):
            loras.append(subj.lora)
    return loras
