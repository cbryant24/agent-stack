"""Versioning mechanics — snapshot, frontmatter bump, version-log entry.

In-place patch + snapshot archive + version log inside the brief (the model the
edit-brief design deferred to F&I). Before any patch, the live brief is snapshot
verbatim to a `versions/` subdir next to it; `version:` bumps in frontmatter; and
a `## Version log` entry — director-visible, travelling with the document —
records the feedback, its resolutions, the unresolved items, and any checked
steps the revision invalidated.
"""
from __future__ import annotations

from pathlib import Path

from feedback_iteration.models import ParsedBrief
from feedback_iteration.patcher import Replace
from feedback_iteration.models import Span


def snapshot(parsed: ParsedBrief) -> Path:
    """Copy the live brief verbatim to `versions/<stem>.v{N}.md` (N = current
    version) BEFORE any patch. Snapshots are F&I's prior-version inputs; the
    director never works in them."""
    version = parsed.frontmatter.version or 1
    versions_dir = parsed.path.parent / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    target = versions_dir / f"{parsed.path.stem}.v{version}.md"
    target.write_text(parsed.text, encoding="utf-8")
    return target


def bump_version_patch(parsed: ParsedBrief, new_version: int) -> Replace:
    field = parsed.frontmatter.fields.get("version")
    if field is None:
        raise ValueError("brief frontmatter has no `version:` field to bump")
    return Replace(field.value_span, str(new_version))


def build_log_entry(
    *,
    version: int,
    date: str,
    feedback_items: list[str],
    resolutions: list[str],
    unresolved: list[str],
    invalidated: list[str],
) -> str:
    lines: list[str] = [f"### v{version} — {date}", ""]
    lines.append("**Feedback:**")
    lines += [f"- {item}" for item in feedback_items] or ["- (none)"]
    lines.append("")
    lines.append("**Resolutions:**")
    lines += [f"- {r}" for r in resolutions] or ["- (no changes applied)"]
    if unresolved:
        lines.append("")
        lines.append("**Unresolved (unapplied):**")
        lines += [f"- {u}" for u in unresolved]
    if invalidated:
        lines.append("")
        lines.append("**Invalidated checked steps:**")
        lines += [f"- {i}" for i in invalidated]
    return "\n".join(lines)


def version_log_patch(parsed: ParsedBrief, entry_md: str) -> Replace:
    """Append `entry_md` to the brief's `## Version log` (created if absent), as a
    zero-width insert at end of file."""
    at = parsed.insert_point_for_version_log
    if parsed.version_log_span is None:
        insert = "\n## Version log\n\n" + entry_md + "\n"
    else:
        insert = "\n" + entry_md + "\n"
    return Replace(Span(at, at), insert)
