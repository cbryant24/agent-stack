"""Foreign-artifact reader for the edit-brief markdown — no LLM.

feedback-iteration imports no sibling package; it treats the brief as a foreign
artifact whose *format is the contract*. This module decomposes the brief into a
`ParsedBrief` that records a char-offset `Span` for every patchable surface
(frontmatter version, timeline cells, section anchors/headings, checkbox steps,
notations, the version log). Revision is then a surgical string-splice over those
exact spans (see `patcher`) — everything untouched survives byte-for-byte, which
is how the director's hand-edits, checked boxes, and deleted steps are preserved.

The brief format is exactly what `edit_brief/brief.py::render_brief` emits. The
`_slugify` here is an independent copy of `edit_brief/parser.py::_slugify` (the
format contract), used only to cross-check anchors and resolve heading-named
feedback — anchors are taken from the `<a id="…">` tags, never re-slugified.
"""
from __future__ import annotations

import re
from pathlib import Path

from feedback_iteration.models import (
    FrontmatterField,
    NotationLine,
    ParsedBrief,
    ParsedFrontmatter,
    SectionBlock,
    Span,
    StepLine,
    TimelineRowSpan,
)


class BriefParseError(Exception):
    """The brief could not be decomposed into the expected structure."""


_FM_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
# Top-level frontmatter fields only (column 0 — nested `  inputs:` keys excluded).
_FM_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):[ \t]*(?P<val>.*?)[ \t]*$", re.MULTILINE)
_TIMELINE_HDR_RE = re.compile(r"^## Timeline[ \t]*$", re.MULTILINE)
_H2_RE = re.compile(r"^## ", re.MULTILINE)
_ROW_RE = re.compile(
    r"^\| \[(?P<heading>.+?)\]\(#(?P<sid>[^)]+)\) \| (?P<start>[^|]*?) \| "
    r"(?P<end>[^|]*?) \| (?P<vo>[^|]*?) \| (?P<timing>[^|]*?) \|[ \t]*$",
    re.MULTILINE,
)
_ANCHOR_RE = re.compile(r'^<a id="(?P<sid>[^"]+)"></a>[ \t]*$', re.MULTILINE)
_HEADING_RE = re.compile(
    r"^### (?P<title>.+?)(?P<timespan> — (?P<start>\S+) → (?P<end>\S+))?[ \t]*$",
    re.MULTILINE,
)
_STEP_RE = re.compile(
    r"^- (?P<box>\[[ xX]\]) (?:(?P<num>\d+)\.[ \t]*)?(?P<body>.*?)[ \t]*$",
    re.MULTILINE,
)
_NOTATION_RE = re.compile(r"^> (?P<body>.*?)[ \t]*$", re.MULTILINE)
_VERSION_LOG_RE = re.compile(r"^## Version log[ \t]*$", re.MULTILINE)


def _slugify(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug or "section"


def parse_timestamp(ts: str) -> float:
    """`mm:ss.mmm` (or raw seconds) → seconds, millisecond-rounded."""
    ts = ts.strip().rstrip("s")
    if ":" in ts:
        m, rest = ts.split(":", 1)
        return round(int(m) * 60 + float(rest), 3)
    return round(float(ts), 3)


def _parse_frontmatter(text: str) -> ParsedFrontmatter:
    m = _FM_RE.match(text)
    if not m:
        raise BriefParseError("no YAML frontmatter block at the top of the brief")
    body_start = m.start("body")
    block_span = Span(0, m.end())
    fields: dict[str, FrontmatterField] = {}
    for fm in _FM_FIELD_RE.finditer(m.group("body")):
        key = fm.group("key")
        if key in fields:
            continue
        val_start = body_start + fm.start("val")
        val_end = body_start + fm.end("val")
        fields[key] = FrontmatterField(
            key=key, value=fm.group("val"), value_span=Span(val_start, val_end)
        )
    version: int | None = None
    if "version" in fields:
        try:
            version = int(fields["version"].value.strip())
        except ValueError:
            version = None
    return ParsedFrontmatter(block_span=block_span, fields=fields, version=version, raw=m.group("body"))


def _parse_timeline(text: str) -> list[TimelineRowSpan]:
    hdr = _TIMELINE_HDR_RE.search(text)
    if not hdr:
        return []
    nxt = _H2_RE.search(text, hdr.end())
    region_end = nxt.start() if nxt else len(text)
    rows: list[TimelineRowSpan] = []
    for m in _ROW_RE.finditer(text, hdr.end(), region_end):
        start_text = m.group("start").strip()
        end_text = m.group("end").strip()
        rows.append(
            TimelineRowSpan(
                section_id=m.group("sid"),
                heading=m.group("heading"),
                start_text=start_text,
                end_text=end_text,
                start_sec=parse_timestamp(start_text),
                end_sec=parse_timestamp(end_text),
                row_span=Span(m.start(), m.end()),
                start_span=Span(m.start("start"), m.end("start")),
                end_span=Span(m.start("end"), m.end("end")),
            )
        )
    return rows


def _parse_section(text: str, sid: str, anchor: re.Match[str], block_end: int) -> SectionBlock:
    block_start = anchor.start()
    anchor_span = Span(anchor.start(), anchor.end())

    hm = _HEADING_RE.search(text, anchor.end(), block_end)
    if hm is None:
        raise BriefParseError(f"section '{sid}' has no '### ' heading after its anchor")
    heading_span = Span(hm.start(), hm.end())
    if hm.group("timespan"):
        heading_timespan: Span | None = Span(hm.start("timespan"), hm.end("timespan"))
        start_sec: float | None = parse_timestamp(hm.group("start"))
        end_sec: float | None = parse_timestamp(hm.group("end"))
    else:
        heading_timespan, start_sec, end_sec = None, None, None

    steps: list[StepLine] = []
    for sm in _STEP_RE.finditer(text, hm.end(), block_end):
        num = int(sm.group("num")) if sm.group("num") else None
        steps.append(
            StepLine(
                number=num,
                checked=sm.group("box").lower() == "[x]",
                text=sm.group("body"),
                line_span=Span(sm.start(), sm.end()),
                text_span=Span(sm.start("body"), sm.end("body")),
                checkbox_span=Span(sm.start("box"), sm.end("box")),
            )
        )

    step_starts = {s.line_span.start for s in steps}
    notations: list[NotationLine] = [
        NotationLine(
            text=nm.group("body"),
            line_span=Span(nm.start(), nm.end()),
            text_span=Span(nm.start("body"), nm.end("body")),
        )
        for nm in _NOTATION_RE.finditer(text, hm.end(), block_end)
        if nm.start() not in step_starts
    ]

    steps_region_end = max((s.line_span.end for s in steps), default=hm.end())

    return SectionBlock(
        section_id=sid,
        heading_text=hm.group("title").strip(),
        anchor_span=anchor_span,
        heading_span=heading_span,
        heading_timespan=heading_timespan,
        start_sec=start_sec,
        end_sec=end_sec,
        steps=steps,
        notations=notations,
        block_span=Span(block_start, block_end),
        steps_region_end=steps_region_end,
    )


def parse_brief(text: str, path: str | Path) -> ParsedBrief:
    """Decompose an edit-brief artifact into a span-indexed `ParsedBrief`."""
    frontmatter = _parse_frontmatter(text)
    timeline_rows = _parse_timeline(text)

    anchors = list(_ANCHOR_RE.finditer(text))
    vlog = _VERSION_LOG_RE.search(text)
    sections_region_end = vlog.start() if vlog else len(text)

    sections: list[SectionBlock] = []
    for i, anchor in enumerate(anchors):
        if i + 1 < len(anchors):
            block_end = anchors[i + 1].start()
        else:
            block_end = sections_region_end
        sections.append(_parse_section(text, anchor.group("sid"), anchor, block_end))

    version_log_span = Span(vlog.start(), len(text)) if vlog else None
    project_id = frontmatter.fields["project_id"].value.strip() if "project_id" in frontmatter.fields else None

    return ParsedBrief(
        text=text,
        path=Path(path),
        project_id=project_id,
        frontmatter=frontmatter,
        timeline_rows=timeline_rows,
        sections=sections,
        version_log_span=version_log_span,
        insert_point_for_version_log=len(text),
    )


def parse_brief_file(path: str | Path) -> ParsedBrief:
    return parse_brief(Path(path).read_text(encoding="utf-8"), path)
