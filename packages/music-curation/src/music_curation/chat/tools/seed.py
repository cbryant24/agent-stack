"""Seed import and the deferred taste queue, without a terminal.

`ingest_seed` asks three kinds of question (facts per file, each inferred taste lesson, each
inferred template). At the terminal the director answers as it goes. Here `seed_preview` lists
every question with a number, the director answers them in conversation, and `seed_ingest`
carries all the answers in one confirmed call. The answers reach the same `ingest_seed` through a
decision source, so parsing and writing are the terminal's code path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_shell.tools.registry import EffectClass, ToolResult, ToolSpec
from pydantic import BaseModel, Field

from music_curation.chat.state import ChatState
from music_curation.chat.tools._common import MIN_PREFIX, fail, ok
from music_curation.models import ParsedSession, ParsedTasteLesson, ParsedTemplate, TastePendingDraft
from music_curation.seed_ingestion import (
    QueueDecision,
    defer_draft,
    edited_lesson,
    ingest_seed,
    list_taste_queue,
    plan_seed,
    review_taste_queue,
)


class PathArgs(BaseModel):
    path: str = Field(description="A seed file, or a directory of them.")


class TasteChoice(BaseModel):
    n: int = Field(description="The lesson's number from seed_preview.")
    decision: Literal["confirm", "skip", "edit", "defer"] = Field(
        description="confirm: write it. skip: drop it. edit: write `text` instead. defer: queue it for later review.")
    text: str | None = Field(default=None, description="The director's wording, for 'edit'.")


class TemplateChoice(BaseModel):
    n: int = Field(description="The template's number from seed_preview.")
    accept: bool


class IngestArgs(PathArgs):
    ingest_facts: bool = Field(description="Write the files' Suno facts to user_knowledge.")
    taste: list[TasteChoice] = Field(default_factory=list, description="One decision per inferred taste lesson.")
    templates: list[TemplateChoice] = Field(default_factory=list, description="One decision per inferred template.")


class NoArgs(BaseModel):
    pass


class QueueArgs(BaseModel):
    draft: str = Field(description="The queued lesson's id, or a unique prefix of 8+ characters.")
    decision: Literal["confirm", "edit", "delete"] = Field(
        description="confirm: write it as a taste lesson. edit: write `text` instead. delete: drop it unwritten.")
    text: str | None = Field(default=None, description="The director's wording, for 'edit'.")


def inferred(sessions: list[ParsedSession]) -> tuple[list[ParsedTasteLesson], list[ParsedTemplate]]:
    """Every inferred taste lesson and template, in the order `ingest_seed` will ask about them."""
    taste = [t for s in sessions for t in s.taste_lessons if not t.is_explicit]
    templates = [t for s in sessions for t in s.templates if not t.is_explicit]
    return taste, templates


class ChatDecisions:
    """A SeedDecisions source fed by the director's numbered answers. Numbers run across files in
    parse order, the same order `seed_preview` showed."""

    def __init__(self, a: IngestArgs) -> None:
        self.facts = a.ingest_facts
        self.taste_by_n = {c.n: c for c in a.taste}
        self.template_by_n = {c.n: c.accept for c in a.templates}
        self._taste_seen = 0
        self._templates_seen = 0

    def ingest_facts(self, session: ParsedSession) -> bool:
        return self.facts

    def taste(self, lessons: list[ParsedTasteLesson]) -> tuple[list[ParsedTasteLesson], list[TastePendingDraft]]:
        confirmed: list[ParsedTasteLesson] = []
        deferred: list[TastePendingDraft] = []
        for lesson in lessons:
            self._taste_seen += 1
            choice = self.taste_by_n[self._taste_seen]
            if choice.decision == "confirm":
                confirmed.append(lesson)
            elif choice.decision == "edit":
                confirmed.append(edited_lesson(lesson, choice.text or lesson.statement))
            elif choice.decision == "defer":
                deferred.append(defer_draft(lesson))
        return confirmed, deferred

    def templates(self, templates: list[ParsedTemplate]) -> list[ParsedTemplate]:
        accepted = []
        for tmpl in templates:
            self._templates_seen += 1
            if self.template_by_n[self._templates_seen]:
                accepted.append(tmpl)
        return accepted


def _parse(path: str) -> tuple[Path, list[ParsedSession]]:
    p = Path(path).expanduser()
    if not p.exists():
        raise ValueError(f"No such file or directory: {path}")
    return p, plan_seed(p)


def _counts(sessions: list[ParsedSession]) -> dict[str, int]:
    return {
        "generations": sum(len(s.prompts) for s in sessions),
        "suno_facts": sum(len(s.suno_facts) for s in sessions),
        "explicit_taste": sum(1 for s in sessions for t in s.taste_lessons if t.is_explicit),
        "explicit_templates": sum(1 for s in sessions for t in s.templates if t.is_explicit),
    }


def missing_decisions(a: IngestArgs, sessions: list[ParsedSession]) -> list[str]:
    taste, templates = inferred(sessions)
    problems = []
    for label, given, total in (("taste lesson", [c.n for c in a.taste], len(taste)),
                                ("template", [c.n for c in a.templates], len(templates))):
        want = set(range(1, total + 1))
        missing, extra = sorted(want - set(given)), sorted(set(given) - want)
        dupes = sorted({n for n in given if given.count(n) > 1})
        if missing:
            problems.append(f"no decision for inferred {label}(s) {', '.join(map(str, missing))}")
        if extra:
            problems.append(f"there is no inferred {label} numbered {', '.join(map(str, extra))} (the file has {total})")
        if dupes:
            problems.append(f"{label} {', '.join(map(str, dupes))} has more than one decision")
    problems += [f"taste lesson {c.n}: 'edit' needs the director's text" for c in a.taste
                 if c.decision == "edit" and not (c.text or "").strip()]
    return problems


def make_seed_tools(state: ChatState) -> list[ToolSpec]:
    async def preview_tool(a: PathArgs) -> ToolResult:
        try:
            p, sessions = _parse(a.path)
        except ValueError as e:
            return fail(str(e))
        if not sessions:
            return ok("No files found to parse.", data={"sessions": 0})
        c = _counts(sessions)
        taste, templates = inferred(sessions)
        lines = [f"{len(sessions)} file(s) parsed from {p}. Nothing is written by this preview.",
                 f"  Written without a per-item question: {c['generations']} generation(s), "
                 f"{c['explicit_taste']} explicit taste lesson(s), {c['explicit_templates']} explicit template(s)",
                 f"  One yes/no for all: {c['suno_facts']} Suno fact(s), to user_knowledge"]
        if taste:
            lines.append("\nInferred taste lessons, one decision each (confirm / skip / edit / defer):")
            lines += [f"  {i}. [{t.valence}/{t.scope}] {t.statement}   (from {t.session_id})" for i, t in enumerate(taste, 1)]
        if templates:
            lines.append("\nInferred templates, yes or no each:")
            for i, t in enumerate(templates, 1):
                swaps = f"  swap: {', '.join(t.swap_variables)}" if t.swap_variables else ""
                lines.append(f"  {i}. {t.name}{swaps}\n     {t.style_pattern[:200]}")
        return ok("\n".join(lines), data={"sessions": len(sessions), **c, "inferred_taste": len(taste),
                                          "inferred_templates": len(templates)})

    async def ingest_precheck(a: IngestArgs) -> str | None:
        try:
            _, sessions = _parse(a.path)
        except ValueError as e:
            return str(e)
        if not sessions:
            return "No files found to parse."
        problems = missing_decisions(a, sessions)
        return ("Every inferred item needs the director's decision before anything is written: "
                + "; ".join(problems) + ". Run seed_preview and ask.") if problems else None

    async def ingest_preview(a: IngestArgs) -> str:
        p, sessions = _parse(a.path)
        c = _counts(sessions)
        taste, templates = inferred(sessions)
        by_n = {ch.n: ch for ch in a.taste}
        tmpl_by_n = {ch.n: ch.accept for ch in a.templates}
        lines = [f"Import seed memory from {p} ({len(sessions)} file(s)).", "",
                 "Written with no further question:",
                 f"  {c['generations']} generation(s), {c['explicit_taste']} explicit taste lesson(s), "
                 f"{c['explicit_templates']} explicit template(s)",
                 f"  Suno facts: {c['suno_facts']} " + ("WRITTEN to user_knowledge" if a.ingest_facts else "NOT written")]
        if taste:
            lines += ["", "Inferred taste lessons:"]
            for i, t in enumerate(taste, 1):
                ch = by_n[i]
                shown = f"{ch.decision.upper():<8} [{t.valence}/{t.scope}] {t.statement}"
                lines.append(f"  {i}. {shown}" + (f"\n       written as: {ch.text}" if ch.decision == "edit" else ""))
        if templates:
            lines += ["", "Inferred templates:"]
            lines += [f"  {i}. {'ADD ' if tmpl_by_n[i] else 'SKIP'} {t.name}" for i, t in enumerate(templates, 1)]
        return "\n".join(lines)

    async def ingest_tool(a: IngestArgs) -> ToolResult:
        try:
            p, sessions = _parse(a.path)
        except ValueError as e:
            return fail(str(e))
        problems = missing_decisions(a, sessions)
        if problems:
            return fail("; ".join(problems))
        store, _, uks = state.stores()
        said: list[str] = []
        report = await ingest_seed(p, decisions=ChatDecisions(a), echo=said.append, curation_store=store, uks=uks)
        t = report.totals
        return ok(f"Imported {report.sessions} file(s): {t['generations']} generation(s), {t['suno_facts']} Suno fact(s), "
                  f"{t['taste_lessons']} taste lesson(s), {t['templates']} template(s) written; "
                  f"{report.deferred_taste} taste lesson(s) deferred to the review queue.",
                  data={**t, "deferred_taste": report.deferred_taste, "sessions": report.sessions})

    # deferred taste queue ------------------------------------------------------

    def find_draft(ref: str) -> tuple[TastePendingDraft | None, str]:
        key = ref.strip().lower()
        drafts = [d for _, d in list_taste_queue()]
        exact = [d for d in drafts if d.draft_id.lower() == key]
        if exact:
            return exact[0], ""
        hits = [d for d in drafts if d.draft_id.lower().startswith(key)] if len(key) >= MIN_PREFIX else []
        if len(hits) == 1:
            return hits[0], ""
        return None, (f"{ref!r} matches {len(hits)} queued lessons; use more characters" if hits
                      else f"no queued taste lesson matches {ref!r}")

    async def queue_tool(a: NoArgs) -> ToolResult:
        drafts = [d for _, d in list_taste_queue()]
        if not drafts:
            return ok("No pending taste lessons to review.", data={"draft_ids": []})
        lines = [f"{len(drafts)} deferred taste lesson(s) awaiting review:"]
        lines += [f"  {d.draft_id}  [{d.valence}/{d.scope}] {d.statement}   (from {d.session_id})" for d in drafts]
        return ok("\n".join(lines), data={"draft_ids": [d.draft_id for d in drafts]})

    async def decide_precheck(a: QueueArgs) -> str | None:
        draft, why = find_draft(a.draft)
        if draft is None:
            return why
        if a.decision == "edit" and not (a.text or "").strip():
            return "'edit' needs the director's text"
        return None

    async def decide_preview(a: QueueArgs) -> str:
        draft, _ = find_draft(a.draft)
        assert draft is not None
        head = {"confirm": "Write this queued taste lesson", "edit": "Write this queued taste lesson, reworded",
                "delete": "Delete this queued taste lesson WITHOUT writing it"}[a.decision]
        lines = [f"{head} [{draft.valence}/{draft.scope}] (from {draft.session_id}):", f"  {draft.statement}"]
        if a.decision == "edit":
            lines.append(f"  written as: {a.text}")
        return "\n".join(lines)

    async def decide_tool(a: QueueArgs) -> ToolResult:
        draft, why = find_draft(a.draft)
        if draft is None:
            return fail(why)
        target = draft.draft_id

        class One:
            """Answer for the one draft the director decided; every other draft stays queued."""

            def decide(self, d: TastePendingDraft, i: int, n: int) -> QueueDecision:
                return QueueDecision(a.decision, a.text) if d.draft_id == target else QueueDecision("skip")

        store, _, _ = state.stores()
        written = await review_taste_queue(One(), echo=lambda line: None, curation_store=store)
        verb = "Deleted without writing" if a.decision == "delete" else "Written as a taste lesson"
        return ok(f"{verb}: {(a.text if a.decision == 'edit' else draft.statement) or ''}"[:300],
                  data={"draft_id": target, "written": written})

    R, M = EffectClass.READ, EffectClass.MEMORY_WRITE
    return [
        ToolSpec(name="seed_preview", effect=R, input_model=PathArgs, handler=preview_tool,
                 description="Parse a seed file or directory and write nothing: counts, plus a numbered list of the "
                             "inferred taste lessons and templates the director must decide on before seed_ingest."),
        ToolSpec(name="seed_ingest", effect=M, input_model=IngestArgs, handler=ingest_tool,
                 precheck=ingest_precheck, preview=ingest_preview,
                 description="Import seed files into memory. Needs the director's decision for EVERY inferred taste "
                             "lesson and template that seed_preview listed, plus yes/no on the Suno facts; it refuses "
                             "otherwise. Generations and explicit lessons and templates are written without a "
                             "per-item question. The director sees the whole import and confirms."),
        ToolSpec(name="taste_queue", effect=R, input_model=NoArgs, handler=queue_tool,
                 description="List taste lessons that were deferred during a seed import and await review."),
        ToolSpec(name="taste_queue_decide", effect=M, input_model=QueueArgs, handler=decide_tool,
                 precheck=decide_precheck, preview=decide_preview,
                 description="Decide ONE deferred taste lesson: confirm it, write it reworded, or delete it unwritten. "
                             "One at a time, on the director's word."),
    ]
