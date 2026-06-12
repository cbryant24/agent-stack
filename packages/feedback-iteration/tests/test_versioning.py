from __future__ import annotations

from pathlib import Path

from feedback_iteration.parser import parse_brief
from feedback_iteration.patcher import apply_patches
from feedback_iteration.versioning import (
    build_log_entry,
    bump_version_patch,
    snapshot,
    version_log_patch,
)


def _write_brief(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "script-draft.edit-brief.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_snapshot_copies_verbatim_before_patch(tmp_path, real_brief_text):
    p = _write_brief(tmp_path, real_brief_text)
    pb = parse_brief(real_brief_text, p)
    snap = snapshot(pb)
    assert snap == tmp_path / "versions" / "script-draft.edit-brief.v1.md"
    assert snap.read_text(encoding="utf-8") == real_brief_text


def test_bump_version_patch_changes_only_version(tmp_path, real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    out = apply_patches(real_brief_text, [bump_version_patch(pb, 2)])
    assert "version: 2" in out
    assert "version: 1" not in out
    assert len(out) == len(real_brief_text)  # "1" → "2" same length


def test_version_log_created_when_absent(real_brief_text):
    pb = parse_brief(real_brief_text, "x")
    assert pb.version_log_span is None
    entry = build_log_entry(
        version=2,
        date="2026-06-12",
        feedback_items=["tighten the calm section by 2s"],
        resolutions=["#the-calm-underneath adjust_duration shorter 2.000s"],
        unresolved=['"the drop feels too slow" — no drop in this brief'],
        invalidated=[],
    )
    out = apply_patches(real_brief_text, [version_log_patch(pb, entry)])
    assert "## Version log" in out
    assert "### v2 — 2026-06-12" in out
    assert "Unresolved (unapplied)" in out


def test_version_log_extended_when_present(real_brief_text):
    text = real_brief_text + "\n## Version log\n\n### v2 — 2026-06-12\n\nold entry\n"
    pb = parse_brief(text, "x")
    assert pb.version_log_span is not None
    entry = build_log_entry(
        version=3, date="2026-06-13", feedback_items=["x"], resolutions=["y"], unresolved=[], invalidated=[]
    )
    out = apply_patches(text, [version_log_patch(pb, entry)])
    assert out.count("## Version log") == 1  # header not duplicated
    assert "### v2 — 2026-06-12" in out and "### v3 — 2026-06-13" in out
