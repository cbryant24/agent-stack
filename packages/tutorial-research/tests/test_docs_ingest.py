from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tutorial_research import docs_ingest
from tutorial_research.constants import DIFFUSION_MASTERY_COURSE

BOOTCAMP_COURSE = "[[The Complete Prompt Engineering for AI Bootcamp (2026)]]"

# Body shared by every fixture: the uniform 5-section course-note template.
_SECTIONS = """# ControlNet Basics

## Quick Review
ControlNet conditions generation on structure.

## Key Concepts
- Canny edges
- Depth maps

## Practical Applications
Use it for pose control in portraits.

## Important Details
Requires a matching preprocessor.

## Related Concepts
- [[Some Other Note]]
- [[Yet Another Note]]
"""


def _write(folder: Path, name: str, course: str, *, lecture: str = "3. ControlNet Basics") -> Path:
    front = (
        "---\n"
        f'course: "{course}"\n'
        'section: "Section 5: Conditioning"\n'
        f'lecture: "{lecture}"\n'
        "---\n"
    )
    path = folder / name
    path.write_text(front + _SECTIONS, encoding="utf-8")
    return path


def _mock_store(existing_records: list | None = None) -> MagicMock:
    store = MagicMock()
    store.ensure_collection = AsyncMock()
    store.upsert_points = AsyncMock()
    store._client = MagicMock()
    store._client.scroll = AsyncMock(return_value=(existing_records or [], None))
    return store


def test_parse_excludes_bootcamp(tmp_path: Path) -> None:
    _write(tmp_path, "1-what-is-stable-diffusion.md", BOOTCAMP_COURSE)
    assert docs_ingest.parse_docs(tmp_path) == []


def test_parse_drops_related_concepts(tmp_path: Path) -> None:
    _write(tmp_path, "5-controlnet-basics.md", DIFFUSION_MASTERY_COURSE)
    cands = docs_ingest.parse_docs(tmp_path)

    headings = {c.heading for c in cands}
    assert headings == {
        "Quick Review",
        "Key Concepts",
        "Practical Applications",
        "Important Details",
    }
    assert "Related Concepts" not in headings

    first = next(c for c in cands if c.heading == "Quick Review")
    assert first.text.startswith("ControlNet Basics — Quick Review\n\n")
    assert first.source_id == "course:diffusion-mastery/5-controlnet-basics"
    assert first.source_title == "Diffusion Mastery — 3. ControlNet Basics"
    assert all(c.total_chunks == 4 for c in cands)
    assert sorted(c.chunk_index for c in cands) == [0, 1, 2, 3]


def test_recap_named_file_still_parsed(tmp_path: Path) -> None:
    # A file named like a "recap" is still a full lecture note — must not be dropped.
    _write(tmp_path, "13-recap-what-you-should-remember.md", DIFFUSION_MASTERY_COURSE)
    cands = docs_ingest.parse_docs(tmp_path)
    assert len(cands) == 4
    assert all(
        c.source_id == "course:diffusion-mastery/13-recap-what-you-should-remember"
        for c in cands
    )


def test_write_stamps_course_provenance(tmp_path: Path) -> None:
    _write(tmp_path, "5-controlnet-basics.md", DIFFUSION_MASTERY_COURSE)
    store = _mock_store()

    docs_ingest.ingest_docs_sync(str(tmp_path), auto_confirm=True, store=store)

    store.ensure_collection.assert_awaited_once()
    store.upsert_points.assert_awaited_once()
    _collection, points = store.upsert_points.await_args.args
    assert len(points) == 4
    assert all(p.source_type == "course_doc" for p in points)
    assert all(p.source_url is None for p in points)
    assert all(p.content_type == "text" for p in points)
    assert all(p.processed_by_agent == "tutorial-research" for p in points)


def test_dedup_rerun_writes_zero(tmp_path: Path) -> None:
    _write(tmp_path, "5-controlnet-basics.md", DIFFUSION_MASTERY_COURSE)
    cands = docs_ingest.parse_docs(tmp_path)
    # Simulate the collection already holding exactly this file's chunks.
    existing = [
        SimpleNamespace(payload={"topic_tags": c.topic_tags, "text": c.text})
        for c in cands
    ]
    store = _mock_store(existing_records=existing)

    docs_ingest.ingest_docs_sync(str(tmp_path), auto_confirm=True, store=store)

    store.upsert_points.assert_not_awaited()


def test_dry_run_no_write(tmp_path: Path) -> None:
    _write(tmp_path, "5-controlnet-basics.md", DIFFUSION_MASTERY_COURSE)
    store = _mock_store()

    docs_ingest.ingest_docs_sync(str(tmp_path), dry_run=True, store=store)

    store.ensure_collection.assert_not_awaited()
    store.upsert_points.assert_not_awaited()
