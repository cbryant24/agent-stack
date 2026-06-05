from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from voiceover_direction.cli import cli
from voiceover_direction.docs_ingest import ingest_docs, parse_docs


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


# ── parse_docs (regex/heuristics, no LLM) ────────────────────────────────────


def test_parse_docs_hierarchy_to_topic_tags(tmp_path: Path) -> None:
    _write(tmp_path, "guide.md", (
        "# ElevenLabs Guide\n\n"
        "## Track Actions\n\nOverview of track actions.\n\n"
        "### Cover\n\nCover regenerates a track in a new style.\n\n"
        "### Extend\n\nExtend adds time to the end.\n"
    ))
    cands = parse_docs(tmp_path)
    by_heading = {c.heading: c for c in cands}

    # H2 with a body of its own is a candidate; H1 is not (page title / ancestor only).
    assert "ElevenLabs Guide" not in by_heading
    assert by_heading["Track Actions"].topic_tags == ["track_actions"]
    assert by_heading["Track Actions"].statement == "Overview of track actions."
    # H3 carries the H2 ancestor in its topic_tags.
    assert by_heading["Cover"].topic_tags == ["track_actions", "cover"]
    assert by_heading["Cover"].statement == "Cover regenerates a track in a new style."
    assert by_heading["Extend"].topic_tags == ["track_actions", "extend"]


def test_parse_docs_skips_empty_body_headings(tmp_path: Path) -> None:
    _write(tmp_path, "g.md", "## Section A\n\n### Sub\n\nReal content.\n")
    cands = parse_docs(tmp_path)
    # "Section A" has no body before its subsection → skipped; only "Sub" is a candidate.
    assert [c.heading for c in cands] == ["Sub"]
    assert cands[0].topic_tags == ["section_a", "sub"]


def test_parse_docs_source_ref_file_vs_url(tmp_path: Path) -> None:
    _write(tmp_path, "plain.md", "## A\n\nbody.\n")
    _write(tmp_path, "fronted.md", "---\nurl: https://elevenlabs.io/docs/x\n---\n\n## B\n\nbody.\n")
    cands = {c.heading: c for c in parse_docs(tmp_path)}
    assert cands["A"].source_ref.startswith("file://")
    assert cands["A"].source_ref.endswith("plain.md")
    assert cands["B"].source_ref == "url://https://elevenlabs.io/docs/x"


# ── ingest_docs (library) ────────────────────────────────────────────────────


def _docs_folder(tmp_path: Path) -> Path:
    _write(tmp_path, "a.md", "## Voices\n\nv3 reads inline audio tags.\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ingest_writes_verified_schema(tmp_path: Path) -> None:
    folder = _docs_folder(tmp_path)
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e1"])
    with patch("voiceover_direction.docs_ingest._existing_keys", AsyncMock(return_value=set())):
        await ingest_docs(folder, auto_confirm=True, uks=uks)

    entries = uks.bulk_load_verified.call_args.args[0]
    source_ref = uks.bulk_load_verified.call_args.kwargs["source_ref"]
    entry = entries[0]
    assert entry["statement"] == "v3 reads inline audio tags."
    assert entry["domain"] == "elevenlabs_mechanics"
    assert entry["source_type"] == "documentation"
    assert entry["confidence"] == "high"
    assert entry["topic_tags"] == ["voices"]
    assert source_ref.startswith("file://")


@pytest.mark.asyncio
async def test_ingest_one_call_per_file(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "## A\n\nfact a.\n")
    _write(tmp_path, "b.md", "## B\n\nfact b.\n")
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e"])
    with patch("voiceover_direction.docs_ingest._existing_keys", AsyncMock(return_value=set())):
        await ingest_docs(tmp_path, auto_confirm=True, uks=uks)
    # One bulk_load_verified per file (per-file source_ref).
    assert uks.bulk_load_verified.await_count == 2


@pytest.mark.asyncio
async def test_ingest_no_duplicate_on_rerun(tmp_path: Path) -> None:
    # The load-bearing dedup test: a re-run where every candidate already exists writes nothing.
    folder = _docs_folder(tmp_path)
    existing = {(c.statement, tuple(c.topic_tags)) for c in parse_docs(folder)}
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=[])
    with patch("voiceover_direction.docs_ingest._existing_keys", AsyncMock(return_value=existing)):
        await ingest_docs(folder, auto_confirm=True, uks=uks)
    uks.bulk_load_verified.assert_not_called()   # all deduped → no write


# ── ingest-docs CLI (confirmation flow, dry-run, yes) ────────────────────────


def _four_section_folder(tmp_path: Path) -> Path:
    _write(tmp_path, "d.md", (
        "## One\n\nfact one.\n\n"
        "## Two\n\nfact two.\n\n"
        "## Three\n\nfact three.\n\n"
        "## Four\n\nfact four.\n"
    ))
    return tmp_path


def _patch_uks():
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e"])
    return uks, (
        patch("voiceover_direction.docs_ingest.UserKnowledgeStore", return_value=uks),
        patch("voiceover_direction.docs_ingest.get_memory_store", return_value=MagicMock()),
        patch("voiceover_direction.docs_ingest._existing_keys", AsyncMock(return_value=set())),
    )


def test_ingest_docs_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    folder = _four_section_folder(tmp_path)
    uks, (p1, p2, p3) = _patch_uks()
    with p1, p2, p3:
        result = runner.invoke(cli, ["knowledge", "ingest-docs", str(folder), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    uks.bulk_load_verified.assert_not_called()


def test_ingest_docs_yes_writes_all(runner: CliRunner, tmp_path: Path) -> None:
    folder = _four_section_folder(tmp_path)
    uks, (p1, p2, p3) = _patch_uks()
    with p1, p2, p3:
        result = runner.invoke(cli, ["knowledge", "ingest-docs", str(folder), "--yes"])
    assert result.exit_code == 0, result.output
    entries = uks.bulk_load_verified.call_args.args[0]
    assert len(entries) == 4   # all four sections written, no prompt
    assert "Written:   4" in result.output


def test_ingest_docs_confirm_flow_y_n_e_d(runner: CliRunner, tmp_path: Path) -> None:
    folder = _four_section_folder(tmp_path)
    uks, (p1, p2, p3) = _patch_uks()
    # One=y(confirm), Two=n(skip), Three=e+edit(confirm), Four=d(defer).
    feed = "y\nn\ne\nedited three\nd\n"
    with p1, p2, p3:
        result = runner.invoke(cli, ["knowledge", "ingest-docs", str(folder)], input=feed)

    assert result.exit_code == 0, result.output
    entries = uks.bulk_load_verified.call_args.args[0]
    statements = sorted(e["statement"] for e in entries)
    assert statements == ["edited three", "fact one."]   # confirmed: One + edited Three
    assert "Written:   2" in result.output
    assert "Deferred:  1" in result.output              # Four deferred, not written
