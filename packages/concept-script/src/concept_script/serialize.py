"""Serialize a VideoBrief to/from the editable `script.md`.

The output layout is dictated by the consumer, `voiceover-direction direct`,
whose parser (`voiceover_direction.parser.parse_script_text`):
  - splits sections at the shallowest heading level present, and
  - skips everything before the first heading (logged as a warning, not an error).

So we emit every section as an H1, and we park all non-narrated material — the
logline, the optional Music hint, and the director-note cut trailer — in the
*preamble* before the first `#`. That is what lets the same file be consumed by
`direct` unchanged, with nothing extra leaking into narration.
"""
from __future__ import annotations

import re

from concept_script.models import BriefSection, VideoBrief

_MUSIC_PREFIX = "Music:"
_CUT_OPEN = "<!-- concept-script: director note cuts applied"
_CUT_CLOSE = "-->"
_HEADING_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def to_script_md(brief: VideoBrief) -> str:
    """Render a VideoBrief as the editable script.md text."""
    parts: list[str] = []

    # ── Preamble (skipped by the voiceover parser) ──────────────────────────
    parts.append(brief.logline.strip())

    if brief.music_hint and brief.music_hint.strip():
        parts.append(f"{_MUSIC_PREFIX} {brief.music_hint.strip()}")

    if brief.cut_trailer:
        cut_lines = "\n".join(f"- {c}" for c in brief.cut_trailer)
        parts.append(f"{_CUT_OPEN}\n{cut_lines}\n{_CUT_CLOSE}")

    # ── Sections (each an H1; prose carries inline emotion tags) ────────────
    for section in brief.sections:
        parts.append(f"# {section.heading.strip()}\n{section.prose.strip()}")

    return "\n\n".join(parts) + "\n"


def from_script_md(text: str) -> VideoBrief:
    """Parse a script.md back into a VideoBrief.

    Best-effort inverse of `to_script_md`, used for round-trip tests and any
    re-read of a previously generated file. The first heading marks the end of
    the preamble; the logline is the first non-empty preamble line.
    """
    match = _HEADING_RE.search(text)
    preamble = text[: match.start()] if match else text
    body = text[match.start():] if match else ""

    logline = ""
    music_hint: str | None = None
    cut_trailer: list[str] = []

    in_cut_block = False
    for raw in preamble.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(_CUT_OPEN):
            in_cut_block = True
            continue
        if in_cut_block:
            if line == _CUT_CLOSE:
                in_cut_block = False
            elif line.startswith("- "):
                cut_trailer.append(line[2:].strip())
            continue
        if line.startswith(_MUSIC_PREFIX):
            music_hint = line[len(_MUSIC_PREFIX):].strip()
            continue
        if not logline:
            logline = line

    sections: list[BriefSection] = []
    headings = list(_HEADING_RE.finditer(body))
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        prose = body[m.end():end].strip()
        sections.append(BriefSection(heading=m.group(1).strip(), prose=prose))

    return VideoBrief(
        logline=logline,
        sections=sections,
        music_hint=music_hint,
        cut_trailer=cut_trailer,
    )
