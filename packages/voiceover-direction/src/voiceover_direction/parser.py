"""Heading-based markdown section parser — no LLM.

Each markdown heading is one section; the body is that section's prose; the
section's identity comes from its heading (a deterministic slug). Same
regex/heuristic approach as the seed/docs ingest elsewhere in the stack — there
is no semantic extraction here. Emotion tags are authored inline in the prose
and pass through untouched; structuring them is the `direct` command's job
(Step 2).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple

from voiceover_direction.models import ParsedScript, ScriptSection

logger = logging.getLogger(__name__)


class _Heading(NamedTuple):
    level: int  # number of leading '#'
    text: str
    start: int  # index of the heading line start in the source
    body_start: int  # index where the body after the heading begins


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _slugify(heading: str) -> str:
    """lowercase, non-alphanumeric runs -> single '-', trimmed."""
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug or "section"


def parse_script_text(text: str, *, source_path: str | None = None) -> ParsedScript:
    """Parse a markdown script into heading-delimited sections.

    The shallowest heading level present defines section boundaries (so a script
    using H1 headings and one using H2 headings both split correctly). Content
    before the first heading is skipped — sections require a heading — but a
    WARNING is logged so a missing heading on real narration is visible rather
    than silently dropped. Duplicate headings get `-2`, `-3` … suffixes so every
    `section_id` stays unique.
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
        return ParsedScript(source_path=source_path, sections=[])

    # Split at the shallowest heading level present; deeper headings stay in the body.
    top_level = min(h.level for h in headings)
    top = [h for h in headings if h.level == top_level]

    preamble = text[: top[0].start].strip()
    if preamble:
        logger.warning(
            "Script has %d characters of content before the first heading%s; it is "
            "skipped (sections require a heading).",
            len(preamble),
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

    return ParsedScript(source_path=source_path, sections=sections)


def parse_script(path: Path) -> ParsedScript:
    """Read a markdown script file and parse it into sections."""
    text = path.read_text(encoding="utf-8")
    return parse_script_text(text, source_path=str(path))
