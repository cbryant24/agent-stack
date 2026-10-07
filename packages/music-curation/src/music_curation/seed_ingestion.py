"""Seed ingestion with inline confirmation for taste lessons and inferred templates.

Flow:
1. Parse file(s) via parser.py
2. Display parse summary
3. Suno facts → bulk confirm (all written to user_knowledge)
4. Explicit taste lessons and templates → auto-write
5. Inferred taste lessons → individual yes/no/edit/defer
6. Inferred templates → single yes/no per template
7. Generation entries → auto-write (facts, not interpretations)

Who answers the confirmations in steps 3, 5 and 6 is a *decision source* (`SeedDecisions`). The
terminal prompts are one source, `--yes` is another, and a chat's confirmation gate is a third;
the parsing and every write below are the same code whichever one answers
(docs/decisions-mode-spec.md).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import click

from agent_runtime import UserKnowledgeStore, get_config, get_memory_store
from music_curation.models import (
    Generation,
    ParsedPrompt,
    ParsedSession,
    ParsedSunoFact,
    ParsedTasteLesson,
    ParsedTemplate,
    TasteLesson,
    TastePendingDraft,
    Template,
)
from music_curation.parser import parse_directory, parse_file
from music_curation.store import MusicCurationStore

logger = logging.getLogger(__name__)

Echo = Callable[[str], None]

_TASTE_PENDING_DIR_NAME = Path("drafts") / "music-curation" / "taste-pending"


def _taste_pending_dir() -> Path:
    d = get_config().agent_data_dir / _TASTE_PENDING_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Display helpers ────────────────────────────────────────────────────────────

def _print_session_summary(session: ParsedSession, echo: Echo = click.echo) -> None:
    echo(f"\n── Parsed: {session.session_id} ─────────────────────────────────────")

    reactions: dict[str, int] = {}
    for p in session.prompts:
        reactions[p.reaction] = reactions.get(p.reaction, 0) + 1
    reaction_summary = ", ".join(f"{v} {k}" for k, v in sorted(reactions.items(), key=lambda x: -x[1]))

    explicit_taste = sum(1 for t in session.taste_lessons if t.is_explicit)
    inferred_taste = len(session.taste_lessons) - explicit_taste
    explicit_tmpls = sum(1 for t in session.templates if t.is_explicit)
    inferred_tmpls = len(session.templates) - explicit_tmpls

    echo(f"  Generations:     {len(session.prompts)}  ({reaction_summary})")
    echo(f"  Suno facts:      {len(session.suno_facts)}")
    echo(f"  Taste lessons:   {len(session.taste_lessons)}  ({explicit_taste} explicit, {inferred_taste} inferred)")
    echo(f"  Templates:       {len(session.templates)}  ({explicit_tmpls} explicit, {inferred_tmpls} inferred)")


# ── Confirmation logic ─────────────────────────────────────────────────────────

def _confirm_taste_inline(
    lessons: list[ParsedTasteLesson],
) -> tuple[list[ParsedTasteLesson], list[TastePendingDraft]]:
    """Present each inferred taste lesson for yes/no/edit/defer confirmation.

    Returns (confirmed_lessons, deferred_drafts).
    """
    confirmed: list[ParsedTasteLesson] = []
    deferred: list[TastePendingDraft] = []

    inferred = [l for l in lessons if not l.is_explicit]
    if not inferred:
        return [], []

    click.echo(f"\n── Inferred taste lessons requiring confirmation ({len(inferred)}) ──")

    for i, lesson in enumerate(inferred, 1):
        click.echo(f"\n{i}/{len(inferred)}: [{lesson.valence}/{lesson.scope}]")
        click.echo(f"  \"{lesson.statement}\"")
        click.echo("  y=confirm  n=skip  e=edit  d=defer to review-taste queue")

        while True:
            choice = click.prompt("  > ", default="n", show_default=False).strip().lower()
            if choice == "y":
                confirmed.append(lesson)
                break
            elif choice == "n":
                break
            elif choice == "d":
                deferred.append(defer_draft(lesson))
                break
            elif choice == "e":
                new_text = click.prompt("  Edit statement", default=lesson.statement)
                confirmed.append(edited_lesson(lesson, new_text))
                break
            else:
                click.echo("  Enter y, n, e, or d")

    return confirmed, deferred


def _confirm_templates_inline(
    templates: list[ParsedTemplate],
) -> list[ParsedTemplate]:
    """Present each inferred template for single yes/no confirmation.

    Explicit templates bypass this entirely.
    """
    confirmed: list[ParsedTemplate] = []
    inferred = [t for t in templates if not t.is_explicit]

    if not inferred:
        return []

    click.echo(f"\n── Inferred templates requiring confirmation ({len(inferred)}) ──")

    for i, tmpl in enumerate(inferred, 1):
        click.echo(f"\n{i}/{len(inferred)}: {tmpl.name}")
        if tmpl.swap_variables:
            click.echo(f"  Swap variables: {', '.join(tmpl.swap_variables)}")
        click.echo(f"  Pattern (first 200 chars): {tmpl.style_pattern[:200]}")
        if click.confirm("  Add as template?", default=False):
            confirmed.append(tmpl)

    return confirmed


# ── Writing helpers ────────────────────────────────────────────────────────────

async def _write_generations(
    prompts: list[ParsedPrompt],
    curation_store: MusicCurationStore,
    session_id: str,
) -> int:
    """Convert ParsedPrompt → Generation and bulk-upsert. Returns count written."""
    if not prompts:
        return 0

    # Build ID map for parent chain resolution (position → entry_id)
    id_map: dict[int, str] = {}
    gens: list[Generation] = []

    for i, p in enumerate(prompts):
        parent_entry_id = id_map.get(p.parent_index) if p.parent_index is not None else None
        chain_root_id = id_map.get(0, "") if p.parent_index is not None else ""

        gen = Generation(
            session_id=session_id,
            style_field=p.style_field,
            lyrics_field=p.lyrics_field,
            reaction=p.reaction,
            status="complete" if p.reaction not in ("pending", "lost_track") else "complete",
            bpm=p.bpm,
            language=p.language,
            suggested_track_title=p.suggested_track_title,
            change_summary=p.change_summary,
            parent_id=parent_entry_id,
            chain_root_id=chain_root_id or "",
            goal=f"Seed from {session_id}",
        )
        # Fix chain_root_id: if no parent, it's self; if has parent, walk to root
        if not gen.parent_id:
            gen.chain_root_id = gen.entry_id
        else:
            # Use the first entry's ID as the chain root
            root_idx = 0
            while True:
                root_prompt = prompts[root_idx]
                if root_prompt.parent_index is None:
                    gen.chain_root_id = id_map.get(root_idx, gen.entry_id)
                    break
                root_idx = root_prompt.parent_index

        id_map[i] = gen.entry_id
        gens.append(gen)

    await curation_store.upsert_generations_bulk(gens)
    return len(gens)


async def _write_taste_lessons(
    confirmed_lessons: list[ParsedTasteLesson],
    explicit_lessons: list[ParsedTasteLesson],
    curation_store: MusicCurationStore,
) -> int:
    all_lessons = [
        TasteLesson(
            statement=l.statement,
            valence=l.valence,
            scope=l.scope,
            derived_from_session_ids=[l.session_id],
            confirmed=True,
        )
        for l in (explicit_lessons + confirmed_lessons)
    ]
    if all_lessons:
        await curation_store.upsert_taste_bulk(all_lessons)
    return len(all_lessons)


async def _write_templates(
    confirmed_templates: list[ParsedTemplate],
    explicit_templates: list[ParsedTemplate],
    curation_store: MusicCurationStore,
) -> int:
    all_templates = [
        Template(
            name=t.name,
            descriptor=t.descriptor,
            style_pattern=t.style_pattern,
            lyrics_pattern=t.lyrics_pattern,
            swap_variables=t.swap_variables,
            domain_tags=t.domain_tags,
            source_session_id=t.source_session_id,
        )
        for t in (explicit_templates + confirmed_templates)
    ]
    if all_templates:
        await curation_store.upsert_templates_bulk(all_templates)
    return len(all_templates)


async def _write_suno_facts(
    facts: list[ParsedSunoFact],
    uks: UserKnowledgeStore,
    source_ref: str,
) -> int:
    if not facts:
        return 0
    entries = [
        {
            "statement": f.statement,
            "domain": "suno_mechanics",
            "topic_tags": f.topic_tags,
            "source_type": "user_verified",
            "confidence": f.confidence,
            "examples": f.examples,
        }
        for f in facts
    ]
    await uks.bulk_load_verified(entries, source_ref=source_ref)
    return len(entries)


def _save_deferred_drafts(drafts: list[TastePendingDraft], echo: Echo = click.echo) -> None:
    taste_dir = _taste_pending_dir()
    for draft in drafts:
        draft_path = taste_dir / f"{draft.draft_id}.json"
        draft_path.write_text(json.dumps(draft.to_dict()), encoding="utf-8")
    if drafts:
        echo(f"  Deferred {len(drafts)} taste lesson(s) to {taste_dir}")


# ── Decision sources ───────────────────────────────────────────────────────────

class SeedDecisions(Protocol):
    """Answers the confirmations of a seed ingest. Only the answers differ between sources."""

    def ingest_facts(self, session: ParsedSession) -> bool: ...

    def taste(
        self, inferred: list[ParsedTasteLesson]
    ) -> tuple[list[ParsedTasteLesson], list[TastePendingDraft]]:
        """(lessons to write, lessons to defer to the review-taste queue)."""
        ...

    def templates(self, inferred: list[ParsedTemplate]) -> list[ParsedTemplate]: ...


class TerminalDecisions:
    """Ask at the terminal (the interactive default)."""

    def ingest_facts(self, session: ParsedSession) -> bool:
        return click.confirm(
            f"  Ingest {len(session.suno_facts)} suno_facts to user_knowledge?",
            default=True,
        )

    def taste(
        self, inferred: list[ParsedTasteLesson]
    ) -> tuple[list[ParsedTasteLesson], list[TastePendingDraft]]:
        return _confirm_taste_inline(inferred)

    def templates(self, inferred: list[ParsedTemplate]) -> list[ParsedTemplate]:
        return _confirm_templates_inline(inferred)


class AutoDecisions:
    """`--yes`: write everything, defer nothing."""

    def ingest_facts(self, session: ParsedSession) -> bool:
        return True

    def taste(
        self, inferred: list[ParsedTasteLesson]
    ) -> tuple[list[ParsedTasteLesson], list[TastePendingDraft]]:
        return list(inferred), []

    def templates(self, inferred: list[ParsedTemplate]) -> list[ParsedTemplate]:
        return list(inferred)


def defer_draft(lesson: ParsedTasteLesson) -> TastePendingDraft:
    return TastePendingDraft(
        statement=lesson.statement,
        valence=lesson.valence,
        scope=lesson.scope,
        session_id=lesson.session_id,
        source_path=lesson.session_id,
    )


def edited_lesson(lesson: ParsedTasteLesson, statement: str) -> ParsedTasteLesson:
    return ParsedTasteLesson(
        statement=statement,
        valence=lesson.valence,
        scope=lesson.scope,
        session_id=lesson.session_id,
        is_explicit=True,
    )


@dataclass
class IngestReport:
    """What an ingest wrote (or, on a dry run, would consider)."""

    dry_run: bool = False
    sessions: int = 0
    totals: dict[str, int] = field(
        default_factory=lambda: {"generations": 0, "suno_facts": 0, "taste_lessons": 0, "templates": 0}
    )
    deferred_taste: int = 0


def plan_seed(path: Path) -> list[ParsedSession]:
    """Parse `path` (a file or a directory) and write nothing: what an ingest would ask about."""
    return parse_directory(path) if path.is_dir() else [parse_file(path)]


# ── Main ingest entry point ────────────────────────────────────────────────────

async def ingest_seed(
    path: Path,
    *,
    dry_run: bool = False,
    auto_confirm: bool = False,
    decisions: SeedDecisions | None = None,
    echo: Echo = click.echo,
    curation_store: MusicCurationStore | None = None,
    uks: UserKnowledgeStore | None = None,
) -> IngestReport:
    """Parse and ingest seed files from path (file or directory).

    `decisions` answers the confirmations; it defaults to the terminal, or to accept-everything
    when `auto_confirm` is set. `echo` receives the progress lines.
    """
    if decisions is None:
        decisions = AutoDecisions() if auto_confirm else TerminalDecisions()
    if curation_store is None or uks is None:
        ms = get_memory_store()
        curation_store = curation_store or MusicCurationStore(ms)
        uks = uks or UserKnowledgeStore(ms)

    if not dry_run:
        await curation_store.ensure_collection()
        await uks.ensure_collection()

    sessions = plan_seed(path)
    report = IngestReport(dry_run=dry_run, sessions=len(sessions))

    if not sessions:
        echo("No files found to parse.")
        return report

    totals = report.totals

    for session in sessions:
        _print_session_summary(session, echo)

        if dry_run:
            totals["generations"] += len(session.prompts)
            totals["suno_facts"] += len(session.suno_facts)
            totals["taste_lessons"] += len(session.taste_lessons)
            totals["templates"] += len(session.templates)
            continue

        # Suno facts — bulk confirm (all to user_knowledge)
        if session.suno_facts:
            if decisions.ingest_facts(session):
                source_ref = f"file://{session.source_path}"
                n = await _write_suno_facts(session.suno_facts, uks, source_ref)
                echo(f"  → {n} suno facts written to user_knowledge")
                totals["suno_facts"] += n

        # Explicit taste and templates — auto-write
        explicit_taste = [l for l in session.taste_lessons if l.is_explicit]
        explicit_tmpls = [t for t in session.templates if t.is_explicit]

        # Inferred taste — one decision each
        inferred_taste = [l for l in session.taste_lessons if not l.is_explicit]
        confirmed_taste, deferred_taste = decisions.taste(inferred_taste)
        _save_deferred_drafts(deferred_taste, echo)
        report.deferred_taste += len(deferred_taste)

        n_taste = await _write_taste_lessons(confirmed_taste, explicit_taste, curation_store)
        if n_taste:
            echo(f"  → {n_taste} taste lessons written")
            totals["taste_lessons"] += n_taste

        # Inferred templates — single yes/no
        inferred_tmpls = [t for t in session.templates if not t.is_explicit]
        confirmed_tmpls = decisions.templates(inferred_tmpls)

        n_tmpls = await _write_templates(confirmed_tmpls, explicit_tmpls, curation_store)
        if n_tmpls:
            echo(f"  → {n_tmpls} templates written")
            totals["templates"] += n_tmpls

        # Generation entries — auto-write (facts, not interpretations)
        n_gens = await _write_generations(session.prompts, curation_store, session.session_id)
        if n_gens:
            echo(f"  → {n_gens} generation entries written")
            totals["generations"] += n_gens

    echo("\n── Ingestion summary ─────────────────────────────────────")
    if dry_run:
        echo("(dry run — nothing written)")
    echo(f"  Generations:     {totals['generations']}")
    echo(f"  Suno facts:      {totals['suno_facts']}")
    echo(f"  Taste lessons:   {totals['taste_lessons']}")
    echo(f"  Templates:       {totals['templates']}")
    return report


# ── Taste pending review ───────────────────────────────────────────────────────

QueueChoice = Literal["confirm", "skip", "edit", "delete"]


@dataclass
class QueueDecision:
    kind: QueueChoice
    text: str | None = None          # the replacement statement, for "edit"


class QueueDecisions(Protocol):
    """Answers the review of one deferred taste lesson (position i of n)."""

    def decide(self, draft: TastePendingDraft, i: int, n: int) -> QueueDecision: ...


class TerminalQueueDecisions:
    def decide(self, draft: TastePendingDraft, i: int, n: int) -> QueueDecision:
        click.echo(f"{i}/{n}: [{draft.valence}/{draft.scope}]")
        click.echo(f"  From: {draft.session_id}")
        click.echo(f"  \"{draft.statement}\"")
        click.echo("  y=confirm  n=skip  e=edit  x=delete without confirming")

        while True:
            choice = click.prompt("  > ", default="n", show_default=False).strip().lower()
            if choice == "y":
                return QueueDecision("confirm")
            elif choice == "n":
                return QueueDecision("skip")
            elif choice == "x":
                return QueueDecision("delete")
            elif choice == "e":
                return QueueDecision("edit", click.prompt("  Edit statement", default=draft.statement))
            else:
                click.echo("  Enter y, n, e, or x")


def list_taste_queue() -> list[tuple[Path, TastePendingDraft]]:
    """The deferred taste lessons awaiting review, oldest file name first. Unreadable files are left out."""
    queue: list[tuple[Path, TastePendingDraft]] = []
    for draft_file in sorted(_taste_pending_dir().glob("*.json")):
        try:
            queue.append((draft_file, TastePendingDraft.from_dict(json.loads(draft_file.read_text(encoding="utf-8")))))
        except Exception:
            continue
    return queue


async def review_taste_queue(
    decisions: QueueDecisions | None = None,
    *,
    echo: Echo = click.echo,
    curation_store: MusicCurationStore | None = None,
) -> int:
    """Review the deferred taste lessons in the queue. Returns how many were confirmed and written.

    `decisions` answers each one; it defaults to the terminal.
    """
    decisions = decisions or TerminalQueueDecisions()
    taste_dir = _taste_pending_dir()
    draft_files = sorted(taste_dir.glob("*.json"))

    if not draft_files:
        echo("No pending taste lessons to review.")
        return 0

    curation_store = curation_store or MusicCurationStore(get_memory_store())
    await curation_store.ensure_collection()

    echo(f"{len(draft_files)} pending taste lesson(s):\n")
    confirmed_lessons: list[ParsedTasteLesson] = []

    for i, draft_file in enumerate(draft_files, 1):
        try:
            data = json.loads(draft_file.read_text(encoding="utf-8"))
            draft = TastePendingDraft.from_dict(data)
        except Exception as exc:
            echo(f"  Skipping unreadable draft {draft_file.name}: {exc}")
            continue

        decision = decisions.decide(draft, i, len(draft_files))
        if decision.kind == "skip":
            continue
        if decision.kind in ("confirm", "edit"):
            confirmed_lessons.append(ParsedTasteLesson(
                statement=decision.text if decision.kind == "edit" and decision.text else draft.statement,
                valence=draft.valence,
                scope=draft.scope,
                session_id=draft.session_id,
                is_explicit=True,
            ))
        draft_file.unlink()

    if confirmed_lessons:
        n = await _write_taste_lessons(confirmed_lessons, [], curation_store)
        echo(f"\n{n} taste lesson(s) confirmed and written.")
        return n
    echo("\nNo lessons confirmed.")
    return 0
