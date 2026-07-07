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

from visual_generation.models import LoraRef, RefImage


class CanonSubject(BaseModel):
    """One locked subject: the aliases that name it, the canonical descriptor that
    must appear, and phrasings that contradict canon and must be stripped.

    An alias beginning with ``@`` is a *token* that expands in place to the locked
    descriptor; a plain alias (e.g. "the narrator") triggers injection of the locked
    descriptor when it's named but the canonical text isn't already present.

    `lora` is the optional *character LoRA* that carries this subject's identity at
    the model level (a registered, usually `identity_bearing` asset). When the subject
    is present in a scene, the locked text reaches the prompt *and* this LoRA is pinned
    into the stack — so textual and model-level identity travel together, on every
    scene, regardless of LLM discretion."""

    aliases: list[str]
    locked: str
    forbid: list[str] = Field(default_factory=list)
    lora: LoraRef | None = None
    # Ordered reference sheets (paths or gen_ids: identity sheet first, outfit second)
    # that carry this subject's identity into a Qwen keyframe EDIT — the reference-set
    # analog of `lora`. When the subject is present in an edit-modality spec, these are
    # appended to `source.references` so identity travels as reference images.
    reference_sheet: list[str] = Field(default_factory=list)


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
        locked: str,
        forbid: list[str] | None = None,
        lora: LoraRef | None = None,
        reference_sheet: list[str] | None = None,
    ) -> CanonSubject:
        """Upsert a subject (keyed by its primary alias, case-insensitively)."""
        if not aliases:
            raise ValueError("a canon subject needs at least one alias")
        key = aliases[0].lower()
        subjects = [s for s in self.load() if not (s.aliases and s.aliases[0].lower() == key)]
        subject = CanonSubject(
            aliases=aliases,
            locked=locked,
            forbid=forbid or [],
            lora=lora,
            reference_sheet=reference_sheet or [],
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
        add_forbid: list[str] | None = None,
        remove_forbid: list[str] | None = None,
        locked: str | None = None,
        lora: LoraRef | None = None,
        clear_lora: bool = False,
        add_references: list[str] | None = None,
        remove_references: list[str] | None = None,
    ) -> CanonSubject:
        """Edit ONE field-set of an existing subject in place — without restating the rest.

        `selector` matches the subject by ANY of its aliases (case-insensitive). Only the
        named edits apply; everything else (the locked descriptor you don't touch, the
        LoRA, untouched aliases/forbids) is preserved. `lora` sets/replaces the pinned
        character LoRA; `clear_lora` removes it (mutually exclusive with `lora`). The
        complement to `set_subject`, which replaces a whole subject — this is the surgical
        edit. Raises ValueError if no subject matches, or if an edit would leave the subject
        with zero aliases."""
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

        forbid = list(s.forbid)
        for f in add_forbid or []:
            if f not in forbid:
                forbid.append(f)
        if remove_forbid:
            dropf = set(remove_forbid)
            forbid = [f for f in forbid if f not in dropf]

        references = list(s.reference_sheet)
        for r in add_references or []:
            if r not in references:
                references.append(r)
        if remove_references:
            dropr = set(remove_references)
            references = [r for r in references if r not in dropr]

        new_lora = None if clear_lora else (lora if lora is not None else s.lora)
        updated = CanonSubject(
            aliases=aliases,
            locked=locked if locked is not None else s.locked,
            forbid=forbid,
            lora=new_lora,
            reference_sheet=references,
        )
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


def _tidy(prompt: str) -> str:
    """Clean up doubled spaces/commas left by stripping forbidden phrases."""
    prompt = re.sub(r"\s{2,}", " ", prompt)
    prompt = re.sub(r"\s+([,.])", r"\1", prompt)
    prompt = re.sub(r"(,\s*){2,}", ", ", prompt)
    return prompt.strip().strip(",").strip()


def _alias_set(subj: CanonSubject) -> set[str]:
    """A subject's aliases lower-cased, with and without a leading ``@`` (so a selector
    like ``narrator`` matches the token alias ``@narrator``)."""
    return {a.lower() for a in subj.aliases} | {a.lower().lstrip("@") for a in subj.aliases}


def _dedupe_locked(prompt: str, locked: str) -> tuple[str, int]:
    """Collapse repeated verbatim copies of a locked descriptor down to the FIRST one.

    A subject's appearance can reach the prompt from more than one channel — the LLM
    weaving it into prose *and* restating it as a trailing identity block (despite being
    told only to place/pose), multiple ``@token`` expansions, or a ``redraft`` inheriting
    an already-injected parent prompt. Each full copy past the first is pure dilution at a
    low step count, so we keep the earliest occurrence (usually the natural in-prose one)
    and delete the rest. Case-insensitive, literal match; returns (prompt, removed_count).

    Only *verbatim* copies of the current locked text are collapsed — a paraphrase the
    LLM authored in its own words has no exact match to strip and is left for the
    composition-side guard to discourage."""
    if not locked:
        return prompt, 0
    spans = [m.span() for m in re.finditer(re.escape(locked), prompt, re.IGNORECASE)]
    if len(spans) <= 1:
        return prompt, 0
    # Delete every occurrence after the first, back-to-front so earlier spans stay valid.
    for start, end in reversed(spans[1:]):
        prompt = prompt[:start] + prompt[end:]
    return prompt, len(spans) - 1


def enforce_canon(
    prompt: str,
    project: str | None,
    *,
    base_dir: Path | None = None,
    force: tuple[str, ...] | list[str] = (),
) -> tuple[str, list[str]]:
    """Rewrite `prompt` to honor the project's locked canon. Returns (prompt, applied).

    Deterministic, no LLM. For each subject named in the prompt: expand any ``@alias``
    token to the locked descriptor, inject the locked descriptor when a plain alias is
    named but the canonical text is absent, and strip any forbidden phrasing.

    `force` is a list of subject **selectors** (aliases) to apply **even if the prompt
    never names them** — the escape hatch for when the LLM refers to a subject by other
    words (e.g. writes "sports-bar" but the alias is "the sports bar"), so canon would
    otherwise miss. A forced subject is injected + its forbids stripped regardless.

    `applied` is a human-readable list of what was changed (empty = no-op). A project with
    no canon file is a no-op."""
    if not project:
        return prompt, []
    subjects = ProjectCanon(project, base_dir=base_dir).load()
    if not subjects:
        return prompt, []

    forced = {f.lower() for f in force}
    applied: list[str] = []
    for subj in subjects:
        locked = subj.locked
        is_forced = bool(forced & _alias_set(subj))
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

        if (plain_match or is_forced) and not present:
            prompt = f"{prompt.rstrip().rstrip(',.')}, {locked}"
            verb = "injected" if plain_match else "forced"
            applied.append(f"{verb} canon for '{plain_match or subj.aliases[0]}'")
            present = True

        if present:
            # Idempotency: guarantee exactly one verbatim copy of the locked descriptor,
            # regardless of how many channels put it there (LLM prose + trailing block,
            # repeated @token expansions, redraft re-injection). Collapse before stripping
            # forbids so the dedupe matches the intact locked text.
            prompt, removed = _dedupe_locked(prompt, locked)
            if removed:
                copies = "copy" if removed == 1 else "copies"
                applied.append(
                    f"deduplicated {removed} redundant {copies} of canon "
                    f"for '{plain_match or subj.aliases[0]}'"
                )
            for bad in subj.forbid:
                bad_re = re.compile(re.escape(bad), re.IGNORECASE)
                if bad_re.search(prompt):
                    prompt = bad_re.sub("", prompt)
                    applied.append(f"removed forbidden phrasing '{bad}'")

    if applied:
        prompt = _tidy(prompt)
    return prompt, applied


def subjects_matching(
    selectors: list[str], project: str | None, *, base_dir: Path | None = None
) -> list[CanonSubject]:
    """The canon subjects any of whose aliases match one of `selectors` (the `--canon`
    force targets). Lets the caller also feed forced subjects into composition. Empty for
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
    """True if `subj` appears in `prompt` — its locked descriptor is present, or any
    of its aliases is named (``@`` tokens expand to the locked text, so they reduce to
    the same check). Run *after* `enforce_canon`, where a present subject's locked text
    has already been injected."""
    lower = prompt.lower()
    if subj.locked and subj.locked.lower() in lower:
        return True
    for alias in subj.aliases:
        plain = alias[1:] if alias.startswith("@") else alias
        if plain and re.search(rf"\b{re.escape(plain)}\b", prompt, re.IGNORECASE):
            return True
    return False


def scene_cast(
    scene_text: str, project: str | None, *, base_dir: Path | None = None
) -> list[CanonSubject]:
    """Canon subjects whose aliases are named in `scene_text` (e.g. a scene's narration).

    Makes canon an *input* to composition, not just a post-hoc filter: when the
    director's scene text names a locked subject, the craft step is told to render that
    subject by name with their canonical appearance — so identity reaches the prompt at
    compose time (and `enforce_canon`/`canon_loras_for` then fire deterministically on
    the alias) instead of the character being silently dropped. Same alias/locked match
    as `_subject_present`. No project / no canon file / empty text → []."""
    if not project or not scene_text:
        return []
    return [
        s
        for s in ProjectCanon(project, base_dir=base_dir).load()
        if _subject_present(scene_text, s)
    ]


def canon_loras_for(
    prompt: str, project: str | None, *, base_dir: Path | None = None
) -> list[LoraRef]:
    """Return the character LoRAs that canon pins for every subject present in `prompt`.

    The model-level counterpart to `enforce_canon`: a subject the scene names (so its
    locked descriptor is in the prompt) also brings its registered character LoRA, so
    identity holds across scenes at the model level — not just the text. Call after
    `enforce_canon` and merge the result into the spec's `lora_stack` (dedupe by name).
    A project with no canon file, or subjects without a `lora`, yields an empty list."""
    if not project:
        return []
    loras: list[LoraRef] = []
    for subj in ProjectCanon(project, base_dir=base_dir).load():
        if subj.lora is not None and _subject_present(prompt, subj):
            loras.append(subj.lora)
    return loras


def ref_image_from_str(value: str) -> RefImage:
    """Interpret a reference entry as a path (has a separator or an image suffix) or else
    a generation id (a bare token) — so a canon sheet or a `--ref` CLI value can ride
    `source.references`. Shared by canon pinning and the draft CLI."""
    looks_pathy = (
        "/" in value
        or "\\" in value
        or value.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    )
    return RefImage(image_path=value) if looks_pathy else RefImage(from_generation=value)


def canon_references_for(
    prompt: str, project: str | None, *, base_dir: Path | None = None
) -> list[RefImage]:
    """The canon reference sheets for every subject present in `prompt`, as ordered
    RefImages — the reference-set analog of `canon_loras_for`. Append these to a Qwen
    edit spec's `source.references` so a subject's identity/outfit travel as reference
    images at edit time (identity sheet first, outfit second). Empty for no project /
    no canon / subjects without reference sheets."""
    if not project:
        return []
    refs: list[RefImage] = []
    for subj in ProjectCanon(project, base_dir=base_dir).load():
        if subj.reference_sheet and _subject_present(prompt, subj):
            refs.extend(ref_image_from_str(s) for s in subj.reference_sheet)
    return refs
