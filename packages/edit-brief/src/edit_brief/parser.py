"""Heading-based markdown script parser — no LLM.

Reuses the exact regex/slug/shallowest-level approach as
`voiceover_direction/parser.py` so the section anchors edit-brief derives match
the headings the voiceover agent split on (same `project_id`, same section ids).

Beyond the section split, this parser also captures the preamble's `Music: …`
hint line — the seed for the best-effort BPM lookup against
`music_curation_memory` (decision 1A). The preamble is otherwise skipped from
narration, exactly as the voiceover parser skips it.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_MUSIC_HINT_RE = re.compile(r"^music\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
# Inline emotion tags like [quiet] / [pause] are narration direction, not words
# the narrator speaks — stripped before the word-count estimate.
_TAG_RE = re.compile(r"\[[^\]]*\]")


class ScriptSection(NamedTuple):
    section_id: str
    heading: str
    body: str

    @property
    def word_count(self) -> int:
        """Spoken-word count for the estimate fallback: inline [tags] removed."""
        return len(_TAG_RE.sub(" ", self.body).split())


class ParsedScript(NamedTuple):
    sections: list[ScriptSection]
    music_hint: str | None
    source_path: str | None


def _slugify(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug or "section"


class _Heading(NamedTuple):
    level: int
    text: str
    start: int
    body_start: int


def parse_script_text(text: str, *, source_path: str | None = None) -> ParsedScript:
    """Parse a markdown script into heading-delimited sections + the music hint.

    The shallowest heading level present defines section boundaries. Content
    before the first heading is the preamble: skipped from sections (with a
    warning if non-trivial) but mined for the `Music:` hint line.
    """
    headings = [
        _Heading(level=len(m.group(1)), text=m.group(2).strip(), start=m.start(), body_start=m.end())
        for m in _HEADING_RE.finditer(text)
    ]

    if not headings:
        if text.strip():
            logger.warning(
                "Script has no markdown headings; nothing parsed%s. Sections require "
                "a heading (each heading is one section).",
                f" ({source_path})" if source_path else "",
            )
        return ParsedScript(sections=[], music_hint=_music_hint(text), source_path=source_path)

    top_level = min(h.level for h in headings)
    top = [h for h in headings if h.level == top_level]

    preamble = text[: top[0].start]
    if preamble.strip():
        logger.info(
            "Script has %d characters of preamble before the first heading%s; it is "
            "skipped from sections (the Music: hint is still read from it).",
            len(preamble.strip()),
            f" ({source_path})" if source_path else "",
        )

    sections: list[ScriptSection] = []
    seen: dict[str, int] = {}
    for i, h in enumerate(top):
        end = top[i + 1].start if i + 1 < len(top) else len(text)
        body = text[h.body_start : end].strip()

        section_id = _slugify(h.text)
        if section_id in seen:
            seen[section_id] += 1
            section_id = f"{section_id}-{seen[section_id]}"
        else:
            seen[section_id] = 1

        sections.append(ScriptSection(section_id=section_id, heading=h.text, body=body))

    # The music hint is a preamble convention; read it from the preamble only.
    return ParsedScript(
        sections=sections, music_hint=_music_hint(preamble), source_path=source_path
    )


def _music_hint(text: str) -> str | None:
    m = _MUSIC_HINT_RE.search(text)
    return m.group(1).strip() if m else None


def parse_script(path: Path) -> ParsedScript:
    text = Path(path).read_text(encoding="utf-8")
    return parse_script_text(text, source_path=str(path))
