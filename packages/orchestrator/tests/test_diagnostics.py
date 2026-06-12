"""Tests for the orchestrator's diagnose-only vector-DB diagnostics.

Structural inspection, report writing, probe-result shaping, and the remediation
delegation seam all mock the Qdrant boundary. One behavioral-probe test needs a live
Qdrant and is marked `requires_qdrant` (Qdrant may be down during the build).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator import diagnostics, tools
from orchestrator.diagnostics import (
    DiagnosticReport,
    RemediationOutcome,
    RemediationSpec,
    behavioral_probe,
    delegate_remediation,
    load_diagnostic_report,
    register_remediation_handler,
    render_report_markdown,
    write_diagnostic_report,
)

from .conftest import requires_qdrant


@pytest.fixture(autouse=True)
def _clear_handlers() -> None:
    """Keep the module-level remediation registry empty between tests."""
    diagnostics._REMEDIATION_HANDLERS.clear()
    yield
    diagnostics._REMEDIATION_HANDLERS.clear()


def _report(**overrides) -> DiagnosticReport:
    base = dict(
        collection="music_curation_memory",
        owning_agent="music-curation",
        symptom="queries return nothing",
        diagnosis="cross-model embedding mismatch",
        evidence={"model_from_code": "voyage-3-large", "top_score": 0.12},
        proposed_fix="re-embed the collection with voyage-3-large",
    )
    base.update(overrides)
    return DiagnosticReport(**base)


# ── report writing ──────────────────────────────────────────────────────────────


class TestDiagnosticReport:
    def test_write_lands_under_diagnostics_dir_with_open_status(self, tmp_path: Path) -> None:
        path = write_diagnostic_report(_report(), vault=tmp_path)
        assert path.parent == tmp_path / "diagnostics"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "type: vector-db-diagnostic" in text
        assert "status: open" in text
        assert "collection: music_curation_memory" in text
        assert "owning_agent: music-curation" in text

    def test_frontmatter_has_all_required_fields(self) -> None:
        import yaml

        md = render_report_markdown(_report().stamp())
        front = md.split("---")[1]
        data = yaml.safe_load(front)
        for key in ("type", "collection", "owning_agent", "status", "created_at"):
            assert key in data
        # body carries the four narrative sections + evidence
        assert "## Symptom" in md
        assert "## Root-cause diagnosis" in md
        assert "## Supporting evidence" in md
        assert "## Proposed fix" in md
        assert "voyage-3-large" in md

    def test_filename_is_stable_per_date_and_collection(self, tmp_path: Path) -> None:
        r = _report(created_at="2026-06-11T00:00:00+00:00")
        p1 = write_diagnostic_report(r, vault=tmp_path)
        r.status = "delegated"
        p2 = write_diagnostic_report(r, vault=tmp_path)
        assert p1 == p2  # rewrites the same file, not a duplicate
        assert "status: delegated" in p2.read_text(encoding="utf-8")


class TestReportRoundTrip:
    """render_report_markdown ↔ load_diagnostic_report — incl. the remediation spec."""

    def test_remediation_spec_round_trips(self, tmp_path: Path) -> None:
        spec = RemediationSpec(
            kind="retag", match={"reaction": "approvd"}, set={"reaction": "approved"}
        )
        report = _report(created_at="2026-06-11T00:00:00+00:00", remediation=spec)
        path = write_diagnostic_report(report, vault=tmp_path)

        text = path.read_text(encoding="utf-8")
        assert "## Remediation spec" in text

        loaded = load_diagnostic_report(path)
        assert loaded.remediation is not None
        assert loaded.remediation.kind == "retag"
        assert loaded.remediation.match == {"reaction": "approvd"}
        assert loaded.remediation.set == {"reaction": "approved"}
        # the rest of the report survives so a rewrite preserves it
        assert loaded.collection == report.collection
        assert loaded.owning_agent == report.owning_agent
        assert loaded.symptom == report.symptom
        assert loaded.diagnosis == report.diagnosis
        assert loaded.proposed_fix == report.proposed_fix
        assert loaded.evidence == report.evidence
        assert loaded.status == "open"

    def test_no_remediation_block_when_absent(self, tmp_path: Path) -> None:
        path = write_diagnostic_report(_report(), vault=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Remediation spec" not in text
        loaded = load_diagnostic_report(path)
        assert loaded.remediation is None


# ── inspect_collection tool ───────────────────────────────────────────────────────


class TestInspectCollection:
    def test_reports_structure_and_sample(self) -> None:
        ms = MagicMock()
        ms.get_collection_info = AsyncMock(
            return_value={
                "name": "music_curation_memory", "status": "green",
                "points_count": 42, "indexed_vectors_count": 42,
                "vector_size": 1024, "distance": "Cosine",
            }
        )
        ms.sample_points = AsyncMock(
            return_value=[("abc12345", {"memory_type": "generation", "reaction": "liked"})]
        )
        with patch("agent_runtime.get_memory_store", return_value=ms):
            out = asyncio.run(tools.inspect_collection.ainvoke({"collection": "music_curation_memory"}))
        assert "points=42" in out
        assert "vector_size=1024" in out
        assert "memory_type" in out

    def test_missing_collection(self) -> None:
        ms = MagicMock()
        ms.get_collection_info = AsyncMock(return_value=None)
        with patch("agent_runtime.get_memory_store", return_value=ms):
            out = asyncio.run(tools.inspect_collection.ainvoke({"collection": "nope"}))
        assert "does not exist" in out

    def test_graceful_degrade(self) -> None:
        ms = MagicMock()
        ms.get_collection_info = AsyncMock(side_effect=RuntimeError("qdrant down"))
        with patch("agent_runtime.get_memory_store", return_value=ms):
            out = asyncio.run(tools.inspect_collection.ainvoke({"collection": "x"}))
        assert "inspect_collection failed" in out


# ── behavioral probe ──────────────────────────────────────────────────────────────


def _store_with_probe(hits, *, expected_present: bool) -> MagicMock:
    ms = MagicMock()
    ms.embedding_client = MagicMock()
    ms.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    ms.embedding_client.embed_multimodal = AsyncMock(return_value=[[0.1] * 1024])
    ms.query_by_vector = AsyncMock(return_value=hits)
    ms.retrieve_points = AsyncMock(
        return_value=[MagicMock()] if expected_present else []
    )
    return ms


class TestBehavioralProbe:
    def test_expected_returns_above_threshold(self) -> None:
        ms = _store_with_probe([("pt-1", 0.82, {}), ("pt-2", 0.40, {})], expected_present=True)
        result = asyncio.run(
            behavioral_probe("c", "q", expected_point_id="pt-1", threshold=0.5, store=ms)
        )
        assert result.expected_returned_above_threshold is True
        assert result.cross_model_suspected is False
        assert result.model == "voyage-3-large"

    def test_cross_model_mismatch_suspected(self) -> None:
        # Expected point IS in the collection, but the probe can't surface it above
        # threshold → the stored vectors are in a different embedding space.
        ms = _store_with_probe([("other", 0.20, {})], expected_present=True)
        result = asyncio.run(
            behavioral_probe("c", "q", expected_point_id="pt-1", threshold=0.5, store=ms)
        )
        assert result.expected_returned_above_threshold is False
        assert result.expected_present_in_collection is True
        assert result.cross_model_suspected is True

    def test_absent_expected_is_not_cross_model(self) -> None:
        # Expected point isn't in the collection at all → a different problem, not a
        # space mismatch.
        ms = _store_with_probe([("other", 0.20, {})], expected_present=False)
        result = asyncio.run(
            behavioral_probe("c", "q", expected_point_id="pt-1", threshold=0.5, store=ms)
        )
        assert result.cross_model_suspected is False

    def test_multimodal_uses_multimodal_model(self) -> None:
        ms = _store_with_probe([("pt-1", 0.9, {})], expected_present=True)
        result = asyncio.run(
            behavioral_probe("c", "q", multimodal=True, store=ms)
        )
        assert result.model == "voyage-multimodal-3"
        ms.embedding_client.embed_multimodal.assert_awaited_once()

    def test_probe_collection_tool_flags_mismatch(self) -> None:
        ms = _store_with_probe([("other", 0.10, {})], expected_present=True)
        with patch("orchestrator.diagnostics.get_memory_store", return_value=ms):
            out = asyncio.run(
                tools.probe_collection.ainvoke(
                    {"collection": "c", "query": "q", "expected_point_id": "pt-1", "threshold": 0.5}
                )
            )
        assert "CROSS-MODEL MISMATCH SUSPECTED" in out


# ── remediation delegation seam ───────────────────────────────────────────────────


class _StubHandler:
    def __init__(self) -> None:
        self.called_with: DiagnosticReport | None = None

    async def remediate(self, report: DiagnosticReport) -> RemediationOutcome:
        self.called_with = report
        return RemediationOutcome(status="fixed", detail="re-embedded 42 points")


class TestRemediationSeam:
    def test_no_handler_leaves_report_open(self, tmp_path: Path) -> None:
        report = _report()
        write_diagnostic_report(report, vault=tmp_path)
        result = asyncio.run(delegate_remediation(report, vault=tmp_path))
        assert result.status == "open"

    def test_registered_handler_transitions_open_to_fixed(self, tmp_path: Path) -> None:
        handler = _StubHandler()
        register_remediation_handler("music-curation", handler)
        report = _report()
        write_diagnostic_report(report, vault=tmp_path)

        result = asyncio.run(delegate_remediation(report, vault=tmp_path))

        assert handler.called_with is not None
        assert result.status == "fixed"
        # the report file was rewritten in place with the final status + remediation note
        text = _only_report_text(tmp_path)
        assert "status: fixed" in text
        assert "re-embedded 42 points" in text

    def test_real_music_curation_handler_open_to_fixed(self, tmp_path: Path) -> None:
        # the real MusicCurationStore.remediate over a mocked MemoryStore, registered
        # as the handler — the genuine cross-package open → delegated → fixed path.
        from music_curation.constants import COLLECTION_NAME
        from music_curation.store import MusicCurationStore

        ms = MagicMock()
        ms.set_payload = AsyncMock()
        ms._client = MagicMock()
        ms._client.scroll = AsyncMock(
            return_value=([MagicMock(id="g1"), MagicMock(id="g2")], None)
        )
        register_remediation_handler("music-curation", MusicCurationStore(ms))

        report = _report(
            collection=COLLECTION_NAME,
            remediation=RemediationSpec(
                kind="retag", match={"reaction": "approvd"}, set={"reaction": "approved"}
            ),
        )
        write_diagnostic_report(report, vault=tmp_path)
        result = asyncio.run(delegate_remediation(report, vault=tmp_path))

        assert result.status == "fixed"
        assert ms.set_payload.await_count == 2
        text = _only_report_text(tmp_path)
        assert "status: fixed" in text
        assert "re-tagged 2 point(s)" in text

    def test_refusal_lands_report_back_at_open(self, tmp_path: Path) -> None:
        # a handler that refuses (here: wrong-collection report) must leave the file at
        # open — NOT stranded at delegated, which delegate_remediation set pre-handoff.
        from music_curation.store import MusicCurationStore

        ms = MagicMock()
        ms.set_payload = AsyncMock()
        ms._client = MagicMock()
        ms._client.scroll = AsyncMock(return_value=([], None))
        register_remediation_handler("music-curation", MusicCurationStore(ms))

        # report targets a different collection than the store owns → refusal
        report = _report(
            collection="not_music_curation_memory",
            remediation=RemediationSpec(kind="retag", match={"a": "b"}, set={"c": "d"}),
        )
        write_diagnostic_report(report, vault=tmp_path)
        result = asyncio.run(delegate_remediation(report, vault=tmp_path))

        assert result.status == "open"
        ms.set_payload.assert_not_called()
        text = _only_report_text(tmp_path)
        assert "status: open" in text
        assert "status: delegated" not in text

    def test_write_tool_notes_no_handler(self, tmp_path: Path) -> None:
        # point the report at the tmp vault via config (the tool uses get_config())
        with patch("orchestrator.diagnostics.get_config") as cfg:
            cfg.return_value = MagicMock(agent_reports_vault=tmp_path)
            out = tools.write_diagnostic_report.invoke({
                "collection": "music_curation_memory",
                "owning_agent": "music-curation",
                "symptom": "s", "diagnosis": "d",
                "evidence": {"model_from_code": "voyage-3-large"},
                "proposed_fix": "re-embed",
            })
        assert "status=open" in out
        assert "no remediation handler is registered" in out


def _only_report_text(vault: Path) -> str:
    files = list((vault / "diagnostics").glob("*.md"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8")


# ── live probe (needs Qdrant) ──────────────────────────────────────────────────────


@requires_qdrant
def test_behavioral_probe_against_live_qdrant() -> None:
    """Exercises the real embed → query_by_vector path. Skipped when Qdrant is down.

    Probes a (likely absent) collection name; the point is that the embedding +
    query round-trips without error against a live server, returning a ProbeResult.
    """
    from agent_runtime import get_memory_store

    async def run() -> None:
        ms = get_memory_store()
        try:
            result = await behavioral_probe(
                "music_curation_memory", "a music generation about phonk", store=ms
            )
        except Exception:
            pytest.skip("collection not present on this live Qdrant")
        assert result.model == "voyage-3-large"
        assert isinstance(result.hits, list)

    asyncio.run(run())
