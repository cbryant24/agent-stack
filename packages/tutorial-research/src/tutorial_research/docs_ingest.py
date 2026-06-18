"""Bulk-ingest local course markdown into the `tutorial_research` Qdrant collection.

This is the document analogue of `yt_intelligence_pipeline.agent_output.ingest_to_qdrant`:
where that path chunks a video transcript into `MemoryPoint`s, this one turns each kept H2
section of a course markdown note into one `MemoryPoint` (content_type="text",
source_type="course_doc") and upserts it via the shared memory store (Voyage embeds inside
`upsert_points`).

Scope: the Diffusion Mastery course docs. A file is ingested only if its frontmatter `course`
matches `DIFFUSION_MASTERY_COURSE`; everything else (e.g. the Prompt Engineering Bootcamp) is
skipped. Within a file, only the keep-set H2 sections are kept (Quick Review / Key Concepts /
Practical Applications / Important Details); "Related Concepts" and any other section is dropped.
The corpus is uniform lecture-summary notes — there are no intro/recap-only pages to filter, so
there is no filename-based page drop.

Provenance is synthesized from the file (these notes carry no `url:`):
  source_id    = "course:diffusion-mastery/<filename-stem-slug>"   (unique per file)
  source_title = "Diffusion Mastery — <lecture>"
  source_url   = None

Re-run safety: `upsert_points` mints a fresh uuid per call, so before writing a file's group we
scroll the collection for that file's existing chunks and skip any already present (keyed on
topic_tags + text). Re-running the same folder therefore writes zero new points.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import click
from qdrant_client.models import FieldCondition, Filter, MatchValue
from ulid import ULID

from agent_runtime.memory import MemoryPoint, MemoryStore, get_memory_store

from tutorial_research.constants import (
    COURSE_DOC_SOURCE_TYPE,
    DEFAULT_KEEP_SECTIONS,
    DIFFUSION_MASTERY_COURSE,
    TUTORIAL_RESEARCH_COLLECTION,
)

logger = logging.getLogger(__name__)

_PROCESSED_BY_AGENT = "tutorial-research"

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter_field(text: str, name: str) -> str | None:
    """Value of a single-line scalar frontmatter field (quotes stripped), or None."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = re.search(rf"^{re.escape(name)}:\s*(.+?)\s*$", m.group(1), re.MULTILINE)
    if not fm:
        return None
    return fm.group(1).strip().strip('"').strip("'") or None


def _tagify(heading: str) -> str:
    """lowercase, non-alphanumeric runs -> single '_', trimmed ('Quick Review' -> 'quick_review')."""
    tag = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    return tag or "section"


def _slugify(value: str) -> str:
    """lowercase kebab-case ('1-What-Is-Stable-Diffusion' -> '1-what-is-stable-diffusion')."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


@dataclass
class DocCandidate:
    """One kept H2 section of a course note, proposed for ingestion."""

    text: str
    topic_tags: list[str] = field(default_factory=list)
    source_id: str = ""
    source_title: str | None = None
    source_file: str = ""
    heading: str = ""
    chunk_index: int = 0
    total_chunks: int = 1

    def key(self) -> tuple[str, tuple[str, ...], str]:
        """Deterministic content key for idempotent re-ingestion."""
        return (self.source_id, tuple(self.topic_tags), self.text)


def _parse_file(
    path: Path,
    *,
    course: str = DIFFUSION_MASTERY_COURSE,
    keep_sections: frozenset[str] = DEFAULT_KEEP_SECTIONS,
) -> list[DocCandidate]:
    """Parse one markdown file into kept-section candidates.

    Returns [] for files whose frontmatter `course` does not match `course` (the only
    page-level skip), or files with no H1 / no kept sections.
    """
    text = path.read_text(encoding="utf-8")

    if _frontmatter_field(text, "course") != course:
        return []

    headings = [
        (len(m.group(1)), m.group(2).strip(), m.start(), m.end())
        for m in _HEADING_RE.finditer(text)
    ]

    h1_title = next((h for lvl, h, _s, _e in headings if lvl == 1), path.stem)
    lecture = _frontmatter_field(text, "lecture") or path.stem
    source_id = f"course:diffusion-mastery/{_slugify(path.stem)}"
    source_title = f"Diffusion Mastery — {lecture}"

    candidates: list[DocCandidate] = []
    for i, (level, heading, _start, body_start) in enumerate(headings):
        if level != 2 or heading.lower() not in keep_sections:
            continue
        end = headings[i + 1][2] if i + 1 < len(headings) else len(text)
        body = text[body_start:end].strip()
        if not body:
            continue
        candidates.append(
            DocCandidate(
                text=f"{h1_title} — {heading}\n\n{body}",
                topic_tags=[_tagify(h1_title), _tagify(heading)],
                source_id=source_id,
                source_title=source_title,
                source_file=str(path),
                heading=heading,
            )
        )

    total = len(candidates)
    for idx, c in enumerate(candidates):
        c.chunk_index = idx
        c.total_chunks = total
    return candidates


def parse_docs(
    folder: str | Path,
    *,
    course: str = DIFFUSION_MASTERY_COURSE,
    keep_sections: frozenset[str] = DEFAULT_KEEP_SECTIONS,
) -> list[DocCandidate]:
    """Parse every markdown file in `folder` into course-doc candidates (regex/heuristics, no LLM)."""
    folder = Path(folder).expanduser()
    candidates: list[DocCandidate] = []
    for path in sorted(folder.glob("*.md")):
        candidates.extend(_parse_file(path, course=course, keep_sections=keep_sections))
    return candidates


async def _existing_keys(
    store: MemoryStore, source_id: str
) -> set[tuple[tuple[str, ...], str]]:
    """(topic_tags, text) keys already stored in tutorial_research for this source_id.

    Filter-only scroll with offset pagination — no vector, no truncation.
    """
    filters = Filter(
        must=[
            FieldCondition(key="source_id", match=MatchValue(value=source_id)),
            FieldCondition(key="content_type", match=MatchValue(value="text")),
        ]
    )
    keys: set[tuple[tuple[str, ...], str]] = set()
    offset = None
    while True:
        records, offset = await store._client.scroll(
            collection_name=TUTORIAL_RESEARCH_COLLECTION,
            scroll_filter=filters,
            limit=100,
            offset=offset,
            with_payload=True,
        )
        for r in records:
            p = r.payload or {}
            keys.add((tuple(p.get("topic_tags", [])), p.get("text", "")))
        if offset is None:
            break
    return keys


def _print_breakdown(candidates: list[DocCandidate]) -> None:
    by_file = Counter(c.source_file for c in candidates)
    by_section = Counter(c.heading for c in candidates)
    click.echo(
        f"\nParsed {len(candidates)} candidate section(s) from {len(by_file)} file(s)."
    )
    click.echo("\nBy section:")
    for heading, n in by_section.most_common():
        click.echo(f"  {n:4d}  {heading}")
    click.echo("\nBy file:")
    for src_file, n in sorted(by_file.items()):
        click.echo(f"  {n:2d}  {Path(src_file).name}")


async def ingest_docs(
    folder: str | Path,
    *,
    course: str = DIFFUSION_MASTERY_COURSE,
    keep_sections: frozenset[str] = DEFAULT_KEEP_SECTIONS,
    dry_run: bool = False,
    auto_confirm: bool = False,
    store: MemoryStore | None = None,
) -> None:
    """Parse `folder`'s course markdown and upsert kept sections into tutorial_research."""
    candidates = parse_docs(folder, course=course, keep_sections=keep_sections)
    _print_breakdown(candidates)

    if not candidates:
        return
    if dry_run:
        click.echo("\n(dry run — nothing embedded or written)")
        return
    if not auto_confirm and not click.confirm(
        f"\nEmbed and upsert {len(candidates)} section(s) into "
        f"'{TUTORIAL_RESEARCH_COLLECTION}'?",
        default=False,
    ):
        click.echo("Aborted.")
        return

    store = store or get_memory_store()
    await store.ensure_collection(TUTORIAL_RESEARCH_COLLECTION, vector_size=1024)
    run_id = str(ULID())

    # Group by source_id (one file per id) so dedup scrolls exactly that file's chunks.
    by_source: dict[str, list[DocCandidate]] = {}
    for c in candidates:
        by_source.setdefault(c.source_id, []).append(c)

    written = 0
    skipped_dupes = 0
    for source_id, group in by_source.items():
        existing = await _existing_keys(store, source_id)
        fresh = [c for c in group if (tuple(c.topic_tags), c.text) not in existing]
        skipped_dupes += len(group) - len(fresh)
        if not fresh:
            continue
        points = [
            MemoryPoint(
                text=c.text,
                source_id=c.source_id,
                source_type=COURSE_DOC_SOURCE_TYPE,
                source_url=None,
                source_title=c.source_title,
                chunk_index=c.chunk_index,
                total_chunks=c.total_chunks,
                processed_by_agent=_PROCESSED_BY_AGENT,
                processed_in_run=run_id,
                content_type="text",
                topic_tags=c.topic_tags,
            )
            for c in fresh
        ]
        await store.upsert_points(TUTORIAL_RESEARCH_COLLECTION, points)
        written += len(points)

    click.echo("\n── Ingestion summary ─────────────────────────────────────")
    click.echo(f"  Written:                   {written}")
    click.echo(f"  Skipped (already present): {skipped_dupes}")


def ingest_docs_sync(folder: str | Path, **kwargs: object) -> None:
    """Synchronous wrapper for ingest_docs()."""
    asyncio.run(ingest_docs(folder, **kwargs))  # type: ignore[arg-type]
