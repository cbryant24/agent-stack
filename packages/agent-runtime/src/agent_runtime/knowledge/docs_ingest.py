"""Ingest local documentation into verified user_knowledge — no LLM, domain-agnostic.

Regex + section heuristics with an end-of-run y/n/edit/defer confirmation, applied to a
folder of markdown docs. Each H2+ heading becomes a candidate entry: the heading hierarchy
is the `topic_tags`, the body is the `statement`. Confirmed entries land in `user_knowledge`
via `UserKnowledgeStore.bulk_load_verified` under the caller-supplied `domain`, with
`source_type="documentation"` and `confidence="high"` by default.

The `domain` tag and the source folder are the only domain-specific inputs; everything else
is generic. voiceover-direction ingests ElevenLabs docs under `elevenlabs_mechanics`;
visual-generation will ingest ComfyUI/RunPod docs under their own domains.

Re-run safety: `bulk_load_verified` is NOT idempotent (fresh uuid per call), and the docs
folder is the durable queue (deferred/skipped sections reappear on the next run). So before
loading a file's group, we enumerate that file's existing active entries and skip any
candidate already present (keyed on source_ref + topic_tags + statement).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from qdrant_client.models import FieldCondition, Filter, MatchValue

from agent_runtime.knowledge.user_knowledge import UserKnowledgeStore
from agent_runtime.memory import get_memory_store

logger = logging.getLogger(__name__)

_SOURCE_TYPE_DOCUMENTATION = "documentation"
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_URL_RE = re.compile(r"^(?:source_url|url):\s*(\S+)\s*$", re.MULTILINE)


@dataclass
class DocCandidate:
    """One H2+ doc section proposed for ingestion."""

    statement: str
    topic_tags: list[str] = field(default_factory=list)
    source_ref: str = ""
    source_file: str = ""
    heading: str = ""

    def key(self) -> tuple[str, tuple[str, ...], str]:
        """Deterministic content key for idempotent re-ingestion."""
        return (self.source_ref, tuple(self.topic_tags), self.statement)


def _tagify(heading: str) -> str:
    """lowercase, non-alphanumeric runs -> single '_', trimmed (e.g. 'Track Actions' -> 'track_actions')."""
    tag = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    return tag or "section"


def _frontmatter_source_ref(text: str, path: Path) -> str:
    """`url://<url>` if a leading frontmatter block records a url, else `file://<abspath>`."""
    m = _FRONTMATTER_RE.match(text)
    if m:
        url_m = _URL_RE.search(m.group(1))
        if url_m:
            return f"url://{url_m.group(1)}"
    return f"file://{path.resolve()}"


def _parse_file(path: Path) -> list[DocCandidate]:
    text = path.read_text(encoding="utf-8")
    source_ref = _frontmatter_source_ref(text, path)

    headings = [
        (len(m.group(1)), m.group(2).strip(), m.start(), m.end())
        for m in _HEADING_RE.finditer(text)
    ]
    candidates: list[DocCandidate] = []
    stack: list[tuple[int, str]] = []  # (level, heading) of shallower ancestors

    for i, (level, heading, _start, body_start) in enumerate(headings):
        # Pop ancestors at this level or deeper; what remains are strictly-shallower parents.
        while stack and stack[-1][0] >= level:
            stack.pop()

        if level >= 2:  # H2+ sections are candidates; H1 is the page title / ancestor only
            end = headings[i + 1][2] if i + 1 < len(headings) else len(text)
            body = text[body_start:end].strip()
            if body:
                # Ancestors at H2+ are topics; H1 is the page title, not a topic tag.
                tag_path = [h for lvl, h in stack if lvl >= 2] + [heading]
                candidates.append(
                    DocCandidate(
                        statement=body,
                        topic_tags=[_tagify(h) for h in tag_path],
                        source_ref=source_ref,
                        source_file=str(path),
                        heading=heading,
                    )
                )

        stack.append((level, heading))

    return candidates


def parse_docs(folder: str | Path) -> list[DocCandidate]:
    """Parse every markdown file in `folder` into doc candidates (regex/heuristics, no LLM)."""
    folder = Path(folder)
    candidates: list[DocCandidate] = []
    for path in sorted(folder.glob("*.md")):
        candidates.extend(_parse_file(path))
    return candidates


def _confirm_docs(candidates: list[DocCandidate]) -> tuple[list[DocCandidate], int]:
    """Per-candidate y/n/edit/defer. Returns (confirmed, deferred_count).

    Defer just postpones — the folder is the durable queue, so deferred (and skipped) sections
    reappear on the next ingest-docs run.
    """
    confirmed: list[DocCandidate] = []
    deferred = 0

    click.echo(f"\n── {len(candidates)} candidate doc section(s) to confirm ──")
    for i, c in enumerate(candidates, 1):
        click.echo(f"\n{i}/{len(candidates)}: [{' > '.join(c.topic_tags)}]")
        click.echo(f'  "{c.statement[:200]}"')
        click.echo("  y=confirm  n=skip  e=edit  d=defer (revisit on next run)")
        while True:
            choice = click.prompt("  > ", default="n", show_default=False).strip().lower()
            if choice == "y":
                confirmed.append(c)
                break
            if choice == "n":
                break
            if choice == "d":
                deferred += 1
                break
            if choice == "e":
                c.statement = click.prompt("  Edit statement", default=c.statement)
                confirmed.append(c)
                break
            click.echo("  Enter y, n, e, or d")

    return confirmed, deferred


async def _existing_keys(
    uks: UserKnowledgeStore, domain: str, source_ref: str
) -> set[tuple[str, tuple[str, ...]]]:
    """Active (statement, topic_tags) keys already stored for this domain + source_ref.

    Filter-only scroll with offset pagination — no vector, no truncation.
    """
    filters = Filter(
        must=[
            FieldCondition(key="domain", match=MatchValue(value=domain)),
            FieldCondition(key="source_ref", match=MatchValue(value=source_ref)),
            FieldCondition(key="superseded_by", match=MatchValue(value="")),
        ]
    )
    keys: set[tuple[str, tuple[str, ...]]] = set()
    offset = None
    while True:
        records, offset = await uks._store._client.scroll(
            collection_name=uks._collection,
            scroll_filter=filters,
            limit=100,
            offset=offset,
            with_payload=True,
        )
        for r in records:
            p = r.payload or {}
            keys.add((p.get("statement", ""), tuple(p.get("topic_tags", []))))
        if offset is None:
            break
    return keys


def _entry(c: DocCandidate, *, domain: str, source_type: str, confidence: str) -> dict[str, Any]:
    return {
        "statement": c.statement,
        "domain": domain,
        "topic_tags": c.topic_tags,
        "source_type": source_type,
        "confidence": confidence,
    }


async def ingest_docs(
    folder: str | Path,
    *,
    domain: str,
    source_type: str = _SOURCE_TYPE_DOCUMENTATION,
    confidence: str = "high",
    dry_run: bool = False,
    auto_confirm: bool = False,
    uks: UserKnowledgeStore | None = None,
) -> None:
    """Parse local docs, confirm, and load verified entries into user_knowledge under `domain`."""
    candidates = parse_docs(folder)
    click.echo(f"Parsed {len(candidates)} candidate doc section(s) from {folder}.")

    if not candidates:
        return
    if dry_run:
        click.echo("(dry run — nothing written)")
        return

    if auto_confirm:
        confirmed, deferred = list(candidates), 0
    else:
        confirmed, deferred = _confirm_docs(candidates)

    uks = uks or UserKnowledgeStore(get_memory_store())

    # Group by source_ref (bulk_load_verified carries one source_ref per batch).
    by_source: dict[str, list[DocCandidate]] = {}
    for c in confirmed:
        by_source.setdefault(c.source_ref, []).append(c)

    written = 0
    skipped_dupes = 0
    for source_ref, group in by_source.items():
        existing = await _existing_keys(uks, domain, source_ref)
        fresh = [c for c in group if (c.statement, tuple(c.topic_tags)) not in existing]
        skipped_dupes += len(group) - len(fresh)
        if fresh:
            entries = [
                _entry(c, domain=domain, source_type=source_type, confidence=confidence)
                for c in fresh
            ]
            await uks.bulk_load_verified(entries, source_ref=source_ref)
            written += len(fresh)

    click.echo("\n── Ingestion summary ─────────────────────────────────────")
    click.echo(f"  Written:   {written}")
    click.echo(f"  Skipped (already present): {skipped_dupes}")
    click.echo(f"  Deferred:  {deferred}")


def ingest_docs_sync(folder: str | Path, *, domain: str, **kwargs: Any) -> None:
    """Synchronous wrapper for ingest_docs()."""
    asyncio.run(ingest_docs(folder, domain=domain, **kwargs))
