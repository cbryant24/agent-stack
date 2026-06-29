"""Compile the project's own upstream documents into the draft input.

The director should not hand-craft prompts in Claude chat. By the time they reach
the visual step, the project folder (`~/agent-projects/<slug>/`) already holds the
context — `directed.md` (narration + scene structure), `brief.md`, `story.md`,
`techniques.md`. This module reads those by slug and composes a creative brief from
**a small list of key points + the discovered docs**, which the LLM turns into the
image prompt. It also extracts a single scene from the narrative doc.

Reader discipline (mirrors edit-brief): every absence is a visible "missing input",
never a failure — a project with no folder simply yields the key points alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Narrative doc is the scene-structured one; directed.md (post-voiceover) is preferred
# over script.md. The rest are whole-doc context.
NARRATIVE_DOCS = ("directed.md", "script.md")
CONTEXT_DOCS = ("brief.md", "story.md", "techniques.md")
# Per-doc excerpt cap so a long script can't blow up the craft prompt.
MAX_DOC_CHARS = 4000


def default_projects_dir() -> Path:
    return Path("~/agent-projects").expanduser()


@dataclass
class CompiledContext:
    """The composed creative input for the craft chain.

    `text` is the brief handed to the LLM; `query` is a short string for the
    knowledge-retrieval legs (key points only — the full docs would dilute the
    embedding); `sources` is the human-readable provenance (→ DraftResult.compiled_from).
    """

    text: str
    query: str
    sources: list[str] = field(default_factory=list)
    # The narrative scene body alone (the chosen `##` section, or the whole narrative doc
    # when no scene is named) — the "who/what is in THIS shot" text. Canon-cast detection
    # scans this, not `text`, so a lead named only in whole-doc context (story.md) isn't
    # mistaken for being present in an establishing shot.
    focus: str = ""


def _read_doc(folder: Path, name: str) -> str | None:
    path = folder / name
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_DOC_CHARS else text[:MAX_DOC_CHARS].rstrip() + "\n…(truncated)"


def list_scenes(text: str) -> list[str]:
    """Return the `##` heading titles of a markdown narrative doc, in order."""
    return [m.group(1).strip() for m in re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, re.MULTILINE)]


def extract_scene(text: str, scene: str) -> str | None:
    """Return the body of the `##` section whose heading contains `scene`
    (case-insensitive), through to the next `##` heading — or None if not found."""
    headings = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, re.MULTILINE))
    target = scene.strip().lower()
    for i, m in enumerate(headings):
        if target in m.group(1).strip().lower():
            start = m.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return text[start:end].strip()
    return None


def discover_scenes(project: str, *, projects_dir: Path | None = None) -> list[str]:
    """The narrative doc's scene headings for a project (directed.md preferred), or []."""
    folder = (projects_dir or default_projects_dir()) / project
    for name in NARRATIVE_DOCS:
        text = _read_doc(folder, name)
        if text:
            return list_scenes(text)
    return []


def compile_creative_input(
    intent: str | None,
    points: list[str] | None,
    project: str | None,
    scene: str | None,
    *,
    projects_dir: Path | None = None,
) -> CompiledContext:
    """Compose the creative brief from key points + the project's discovered docs.

    Precedence of the narrative doc: directed.md, else script.md. When `scene` is
    given, only that section of the narrative doc is included (falling back to the
    whole doc if the heading isn't found). brief/story/techniques are whole-doc
    context (capped). With no project/folder, the key points stand alone."""
    key_points: list[str] = []
    if intent and intent.strip():
        key_points.append(intent.strip())
    key_points.extend(p.strip() for p in (points or []) if p.strip())

    parts: list[str] = []
    sources: list[str] = []
    focus = ""
    if key_points:
        parts.append("Key points from the director:\n" + "\n".join(f"- {p}" for p in key_points))

    if project:
        folder = (projects_dir or default_projects_dir()) / project

        # Narrative doc (scene-aware), first one that exists.
        for name in NARRATIVE_DOCS:
            text = _read_doc(folder, name)
            if not text:
                continue
            label = name
            body = text
            if scene:
                section = extract_scene(text, scene)
                if section is not None:
                    body, label = section, f"{name} (scene: {scene})"
            parts.append(f"[from {label}]:\n{_excerpt(body)}")
            sources.append(label)
            focus = body  # the scene body (or whole narrative doc) — for canon-cast detection
            break

        # Whole-doc context.
        for name in CONTEXT_DOCS:
            text = _read_doc(folder, name)
            if not text:
                continue
            parts.append(f"[from {name}]:\n{_excerpt(text)}")
            sources.append(name)

    # Retrieval query: key points (+ scene) only — short, to keep embeddings focused.
    query = "; ".join(key_points)
    if scene:
        query = f"{query}; {scene}" if query else scene

    return CompiledContext(text="\n\n".join(parts), query=query, sources=sources, focus=focus)
