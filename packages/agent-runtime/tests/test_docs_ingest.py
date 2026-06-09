from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from agent_runtime.knowledge.docs_ingest import ingest_docs, ingest_docs_sync, parse_docs

DOMAIN = "comfyui_mechanics"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


# ── parse_docs (regex/heuristics, no LLM) ────────────────────────────────────


def test_parse_docs_hierarchy_to_topic_tags(tmp_path: Path) -> None:
    _write(tmp_path, "guide.md", (
        "# ComfyUI Guide\n\n"
        "## Nodes\n\nOverview of nodes.\n\n"
        "### KSampler\n\nKSampler denoises latents.\n\n"
        "### VAEDecode\n\nVAEDecode turns latents into pixels.\n"
    ))
    cands = parse_docs(tmp_path)
    by_heading = {c.heading: c for c in cands}

    # H2 with a body of its own is a candidate; H1 is not (page title / ancestor only).
    assert "ComfyUI Guide" not in by_heading
    assert by_heading["Nodes"].topic_tags == ["nodes"]
    assert by_heading["Nodes"].statement == "Overview of nodes."
    # H3 carries the H2 ancestor in its topic_tags.
    assert by_heading["KSampler"].topic_tags == ["nodes", "ksampler"]
    assert by_heading["KSampler"].statement == "KSampler denoises latents."
    assert by_heading["VAEDecode"].topic_tags == ["nodes", "vaedecode"]


def test_parse_docs_skips_empty_body_headings(tmp_path: Path) -> None:
    _write(tmp_path, "g.md", "## Section A\n\n### Sub\n\nReal content.\n")
    cands = parse_docs(tmp_path)
    # "Section A" has no body before its subsection → skipped; only "Sub" is a candidate.
    assert [c.heading for c in cands] == ["Sub"]
    assert cands[0].topic_tags == ["section_a", "sub"]


def test_parse_docs_source_ref_file_vs_url(tmp_path: Path) -> None:
    _write(tmp_path, "plain.md", "## A\n\nbody.\n")
    _write(tmp_path, "fronted.md", "---\nurl: https://docs.comfy.org/x\n---\n\n## B\n\nbody.\n")
    cands = {c.heading: c for c in parse_docs(tmp_path)}
    assert cands["A"].source_ref.startswith("file://")
    assert cands["A"].source_ref.endswith("plain.md")
    assert cands["B"].source_ref == "url://https://docs.comfy.org/x"


# ── ingest_docs (library) ────────────────────────────────────────────────────


def _docs_folder(tmp_path: Path) -> Path:
    _write(tmp_path, "a.md", "## Sampler\n\nKSampler denoises in latent space.\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ingest_writes_verified_schema(tmp_path: Path) -> None:
    folder = _docs_folder(tmp_path)
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e1"])
    with patch("agent_runtime.knowledge.docs_ingest._existing_keys", AsyncMock(return_value=set())):
        await ingest_docs(folder, domain=DOMAIN, auto_confirm=True, uks=uks)

    entries = uks.bulk_load_verified.call_args.args[0]
    source_ref = uks.bulk_load_verified.call_args.kwargs["source_ref"]
    entry = entries[0]
    assert entry["statement"] == "KSampler denoises in latent space."
    assert entry["domain"] == DOMAIN
    assert entry["source_type"] == "documentation"
    assert entry["confidence"] == "high"
    assert entry["topic_tags"] == ["sampler"]
    assert source_ref.startswith("file://")


@pytest.mark.asyncio
async def test_ingest_domain_flows_to_dedup_filter(tmp_path: Path) -> None:
    # The caller's domain must reach _existing_keys (the dedup query is domain-scoped).
    folder = _docs_folder(tmp_path)
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e1"])
    spy = AsyncMock(return_value=set())
    with patch("agent_runtime.knowledge.docs_ingest._existing_keys", spy):
        await ingest_docs(folder, domain=DOMAIN, auto_confirm=True, uks=uks)
    # _existing_keys(uks, domain, source_ref) — domain is the second positional arg.
    assert spy.call_args.args[1] == DOMAIN


@pytest.mark.asyncio
async def test_ingest_one_call_per_file(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "## A\n\nfact a.\n")
    _write(tmp_path, "b.md", "## B\n\nfact b.\n")
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=["e"])
    with patch("agent_runtime.knowledge.docs_ingest._existing_keys", AsyncMock(return_value=set())):
        await ingest_docs(tmp_path, domain=DOMAIN, auto_confirm=True, uks=uks)
    # One bulk_load_verified per file (per-file source_ref).
    assert uks.bulk_load_verified.await_count == 2


@pytest.mark.asyncio
async def test_ingest_no_duplicate_on_rerun(tmp_path: Path) -> None:
    # The load-bearing dedup test: a re-run where every candidate already exists writes nothing.
    folder = _docs_folder(tmp_path)
    existing = {(c.statement, tuple(c.topic_tags)) for c in parse_docs(folder)}
    uks = MagicMock()
    uks.bulk_load_verified = AsyncMock(return_value=[])
    with patch("agent_runtime.knowledge.docs_ingest._existing_keys", AsyncMock(return_value=existing)):
        await ingest_docs(folder, domain=DOMAIN, auto_confirm=True, uks=uks)
    uks.bulk_load_verified.assert_not_called()   # all deduped → no write


# ── ingest_docs orchestration via a click harness (confirm flow, dry-run, yes) ──


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--yes", is_flag=True, default=False)
def _harness(folder: str, dry_run: bool, yes: bool) -> None:
    """Throwaway CLI to drive ingest_docs_sync through CliRunner (input/output capture)."""
    ingest_docs_sync(folder, domain=DOMAIN, dry_run=dry_run, auto_confirm=yes)


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
        patch("agent_runtime.knowledge.docs_ingest.UserKnowledgeStore", return_value=uks),
        patch("agent_runtime.knowledge.docs_ingest.get_memory_store", return_value=MagicMock()),
        patch("agent_runtime.knowledge.docs_ingest._existing_keys", AsyncMock(return_value=set())),
    )


def test_ingest_docs_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    folder = _four_section_folder(tmp_path)
    uks, (p1, p2, p3) = _patch_uks()
    with p1, p2, p3:
        result = runner.invoke(_harness, [str(folder), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    uks.bulk_load_verified.assert_not_called()


def test_ingest_docs_yes_writes_all(runner: CliRunner, tmp_path: Path) -> None:
    folder = _four_section_folder(tmp_path)
    uks, (p1, p2, p3) = _patch_uks()
    with p1, p2, p3:
        result = runner.invoke(_harness, [str(folder), "--yes"])
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
        result = runner.invoke(_harness, [str(folder)], input=feed)

    assert result.exit_code == 0, result.output
    entries = uks.bulk_load_verified.call_args.args[0]
    statements = sorted(e["statement"] for e in entries)
    assert statements == ["edited three", "fact one."]   # confirmed: One + edited Three
    assert "Written:   2" in result.output
    assert "Deferred:  1" in result.output              # Four deferred, not written
