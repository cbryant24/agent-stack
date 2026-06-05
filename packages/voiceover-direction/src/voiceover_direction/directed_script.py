"""Read/write the editable directed-script markdown artifact.

Format (handoff #7): headings preserved (section identity), audio tags literal inline
in the prose, per-section metadata in an HTML comment carrying JSON so the arbitrary
model-agnostic `settings` dict round-trips losslessly and the comments stay invisible
when the markdown renders.

    <!-- vo-script: {"project_id": "...", "domain": null, "source_path": "...", "created_at": "..."} -->

    ## Intro
    <!-- vo-meta: {"section_id": "intro", "voice_id": "voice-1", "model": "eleven_v3", "settings": {...}, "notes": "..."} -->

    [whispers] Welcome back to the channel. [excited] Let's dive in.

The `section_id` is carried in the per-section metadata (so the round-trip is exact even
for duplicate headings); it aligns with the parser's `_slugify(heading)` scheme.

Load-bearing invariant: `read_directed_script(write_directed_script(s)) == s`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from voiceover_direction.models import DirectedScript, DirectedSection, _now_iso
from voiceover_direction.parser import _slugify

# `-->` cannot appear inside the JSON, so a non-greedy capture up to it is exact even
# with nested braces in `settings`.
_SCRIPT_META_RE = re.compile(r"<!-- vo-script:\s*(.*?)\s*-->", re.DOTALL)
_SECTION_META_RE = re.compile(r"<!-- vo-meta:\s*(.*?)\s*-->", re.DOTALL)
_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def write_directed_script(script: DirectedScript, path: Path) -> None:
    """Write a DirectedScript to a directed-script markdown file."""
    header = {
        "project_id": script.project_id,
        "domain": script.domain,
        "source_path": script.source_path,
        "created_at": script.created_at,
    }
    lines: list[str] = [f"<!-- vo-script: {json.dumps(header, ensure_ascii=False)} -->", ""]
    for s in script.sections:
        meta = {
            "section_id": s.section_id,
            "voice_id": s.voice_id,
            "model": s.model,
            "settings": s.settings,
            "notes": s.notes,
        }
        lines.append(f"## {s.heading}")
        lines.append(f"<!-- vo-meta: {json.dumps(meta, ensure_ascii=False)} -->")
        lines.append("")
        lines.append(s.text)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_directed_script(path: Path) -> DirectedScript:
    """Read a directed-script markdown file back into a DirectedScript."""
    text = path.read_text(encoding="utf-8")

    header_m = _SCRIPT_META_RE.search(text)
    doc = json.loads(header_m.group(1)) if header_m else {}

    sections: list[DirectedSection] = []
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        meta_m = _SECTION_META_RE.search(block)
        meta = json.loads(meta_m.group(1)) if meta_m else {}
        prose = block[meta_m.end():].strip() if meta_m else block.strip()

        sections.append(
            DirectedSection(
                section_id=meta.get("section_id") or _slugify(heading),
                heading=heading,
                text=prose,
                voice_id=meta.get("voice_id"),
                model=meta.get("model"),
                settings=meta.get("settings") or {},
                notes=meta.get("notes"),
            )
        )

    return DirectedScript(
        project_id=doc.get("project_id", ""),
        domain=doc.get("domain"),
        sections=sections,
        source_path=doc.get("source_path"),
        created_at=doc.get("created_at") or _now_iso(),
    )
