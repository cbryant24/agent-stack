from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_runtime.knowledge.user_knowledge import (
    COLLECTION_NAME,
    Draft,
    KnowledgeEntry,
    KnowledgeHit,
    UserKnowledgeStore,
)
from agent_runtime.memory.store import MemoryStore


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _qdrant_reachable() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:6333/healthz", timeout=1)
        return r.status_code == 200
    except Exception:
        return False


requires_qdrant = pytest.mark.skipif(
    not _qdrant_reachable(),
    reason="Qdrant not running on localhost:6333",
)


@pytest.fixture(autouse=True)
def _env(fake_env: None) -> None:
    pass


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point AGENT_DATA_DIR at a temp directory and reset the config cache."""
    from agent_runtime.config import reset_config
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "agent-data"))
    reset_config()
    yield tmp_path
    reset_config()


def _mock_store() -> MagicMock:
    store = MagicMock(spec=MemoryStore)
    store.embedding_client = MagicMock()
    store.embedding_client.embed = AsyncMock(return_value=[[0.1] * 1024])
    store.upsert_raw_points = AsyncMock()
    store.set_payload = AsyncMock()
    store.retrieve_points = AsyncMock(return_value=[])
    store.query_by_vector = AsyncMock(return_value=[])
    store.ensure_collection = AsyncMock()
    return store


def _unique_collection() -> str:
    from ulid import ULID
    return f"test_uk_{str(ULID()).lower()[:10]}"


# ── propose_entry (no Qdrant) ─────────────────────────────────────────────────


class TestProposeEntry:
    def test_creates_draft_file(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            draft = await uk.propose_entry("Suno v4 uses style field", "suno_mechanics", "user_verified")
            draft_dir = tmp_env / "agent-data" / "drafts" / "user_knowledge"
            assert (draft_dir / f"{draft.draft_id}.json").exists()

        asyncio.run(run())

    def test_returns_draft_with_correct_fields(self, tmp_env: Path) -> None:
        async def run() -> Draft:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            return await uk.propose_entry(
                "Test statement",
                "music_theory",
                "documentation",
                topic_tags=["harmony"],
                source_ref="https://example.com",
                examples=["C major → F major"],
                confidence="medium",
            )

        draft = asyncio.run(run())
        assert draft.statement == "Test statement"
        assert draft.domain == "music_theory"
        assert draft.source_type == "documentation"
        assert draft.topic_tags == ["harmony"]
        assert draft.source_ref == "https://example.com"
        assert draft.examples == ["C major → F major"]
        assert draft.confidence == "medium"
        assert isinstance(draft.created_at, datetime)
        assert draft.draft_id  # non-empty UUID string

    def test_does_not_write_to_qdrant(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            await uk.propose_entry("Test", "general", "manual")
            store.upsert_raw_points.assert_not_called()
            store.embedding_client.embed.assert_not_called()

        asyncio.run(run())


# ── reject_entry (no Qdrant) ─────────────────────────────────────────────────


class TestRejectEntry:
    def test_deletes_draft_file(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            draft = await uk.propose_entry("Statement", "general", "manual")
            draft_dir = tmp_env / "agent-data" / "drafts" / "user_knowledge"
            assert (draft_dir / f"{draft.draft_id}.json").exists()
            await uk.reject_entry(draft.draft_id)
            assert not (draft_dir / f"{draft.draft_id}.json").exists()

        asyncio.run(run())

    def test_missing_draft_raises_file_not_found(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            with pytest.raises(FileNotFoundError):
                await uk.reject_entry(str(uuid.uuid4()))

        asyncio.run(run())

    def test_no_qdrant_write_on_reject(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            draft = await uk.propose_entry("Statement", "general", "manual")
            await uk.reject_entry(draft.draft_id)
            store.upsert_raw_points.assert_not_called()

        asyncio.run(run())


# ── list_drafts (no Qdrant) ──────────────────────────────────────────────────


class TestListDrafts:
    def test_returns_active_drafts(self, tmp_env: Path) -> None:
        async def run() -> list[Draft]:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            await uk.propose_entry("First", "general", "manual")
            await uk.propose_entry("Second", "general", "manual")
            return await uk.list_drafts()

        drafts = asyncio.run(run())
        assert len(drafts) == 2

    def test_prunes_expired_drafts(self, tmp_env: Path) -> None:
        async def run() -> list[Draft]:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            draft = await uk.propose_entry("Old entry", "general", "manual")

            # Backdating the draft file's created_at to 8 days ago
            draft_path = uk._draft_path(draft.draft_id)
            data = json.loads(draft_path.read_text())
            old_time = datetime.now(UTC) - timedelta(days=8)
            data["created_at"] = old_time.isoformat()
            draft_path.write_text(json.dumps(data))

            return await uk.list_drafts()

        remaining = asyncio.run(run())
        assert remaining == []

    def test_skips_corrupt_json_without_crashing(self, tmp_env: Path) -> None:
        async def run() -> list[Draft]:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            draft_dir = uk._draft_dir()
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "corrupt.json").write_text("not valid json {{{{")
            await uk.propose_entry("Valid", "general", "manual")
            return await uk.list_drafts()

        drafts = asyncio.run(run())
        assert len(drafts) == 1
        # corrupt file is still there (preserved for inspection)
        store = _mock_store()
        uk = UserKnowledgeStore(store)
        draft_dir = uk._draft_dir()
        assert (draft_dir / "corrupt.json").exists()


# ── bulk_load_verified (no Qdrant needed for error case) ────────────────────


class TestBulkLoad:
    def test_missing_source_ref_raises(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            with pytest.raises(ValueError, match="source_ref is required"):
                await uk.bulk_load_verified([{"statement": "test"}], source_ref="")

        asyncio.run(run())

    def test_none_source_ref_raises(self, tmp_env: Path) -> None:
        async def run() -> None:
            store = _mock_store()
            uk = UserKnowledgeStore(store)
            with pytest.raises((ValueError, TypeError)):
                await uk.bulk_load_verified([{"statement": "test"}], source_ref=None)  # type: ignore[arg-type]

        asyncio.run(run())


# ── Qdrant-backed tests ───────────────────────────────────────────────────────


@requires_qdrant
class TestUserKnowledgeStoreLive:
    def _make_store(self) -> tuple[MemoryStore, UserKnowledgeStore]:
        col = _unique_collection()
        ms = MemoryStore("http://localhost:6333")
        uk = UserKnowledgeStore(ms, collection_name=col)
        return ms, uk

    def _mock_embed(self, real_store: MemoryStore, vector: list[float] | None = None):
        v = vector or [0.1] * 1024
        mock_client = MagicMock()
        mock_client.embed = AsyncMock(return_value=[v])
        return patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client)

    def test_ensure_collection_idempotent(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                with self._mock_embed(ms):
                    await uk.ensure_collection()
                    await uk.ensure_collection()  # must not raise
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_confirm_writes_to_qdrant_and_deletes_draft(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                with self._mock_embed(ms):
                    await uk.ensure_collection()
                    draft = await uk.propose_entry("Suno uses meta-tags", "suno_mechanics", "user_verified")
                    assert uk._draft_path(draft.draft_id).exists()

                    entry_id = await uk.confirm_entry(draft.draft_id)

                    assert not uk._draft_path(draft.draft_id).exists()
                    assert entry_id  # non-empty

                    records = await ms._client.retrieve(
                        collection_name=uk._collection,
                        ids=[entry_id],
                        with_payload=True,
                    )
                    assert len(records) == 1
                    assert records[0].payload["statement"] == "Suno uses meta-tags"
                    assert records[0].payload["superseded_by"] == ""
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_bulk_load_writes_all_entries(self, tmp_env: Path) -> None:
        async def run() -> list[str]:
            ms, uk = self._make_store()
            entries = [
                {"statement": f"Fact {i}", "domain": "general", "source_type": "manual"}
                for i in range(3)
            ]
            mock_client = MagicMock()
            mock_client.embed = AsyncMock(return_value=[[0.1 * (i + 1)] * 1024 for i in range(3)])
            try:
                with patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client):
                    ids = await uk.bulk_load_verified(entries, source_ref="file://seed.json")
                    assert len(ids) == 3
                    count = await ms._client.count(collection_name=uk._collection)
                    assert count.count == 3
                    return ids
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_search_current_only_excludes_superseded(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                # Two vectors: [1,0,...] = "active", [0,1,...] = "old superseded"
                v_active = [1.0] + [0.0] * 1023
                v_old = [0.0, 1.0] + [0.0] * 1022
                v_query = [1.0] + [0.0] * 1023  # matches active

                await uk.ensure_collection()

                from qdrant_client.models import PointStruct
                now_iso = datetime.now(UTC).isoformat()
                # Insert active entry
                active_id = str(uuid.uuid4())
                await ms.upsert_raw_points(uk._collection, [
                    PointStruct(id=active_id, vector=v_active, payload={
                        "statement": "Active fact",
                        "domain": "general", "topic_tags": [], "source_type": "manual",
                        "source_ref": None, "examples": [], "created_at": now_iso,
                        "updated_at": now_iso, "confidence": "high",
                        "superseded_by": "", "entry_id": active_id,
                    }),
                ])
                # Insert superseded entry
                old_id = str(uuid.uuid4())
                await ms.upsert_raw_points(uk._collection, [
                    PointStruct(id=old_id, vector=v_old, payload={
                        "statement": "Old superseded fact",
                        "domain": "general", "topic_tags": [], "source_type": "manual",
                        "source_ref": None, "examples": [], "created_at": now_iso,
                        "updated_at": now_iso, "confidence": "high",
                        "superseded_by": active_id, "entry_id": old_id,
                    }),
                ])

                mock_client = MagicMock()
                mock_client.embed = AsyncMock(return_value=[v_query])
                with patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client):
                    hits = await uk.search("query", current_only=True, limit=10)

                assert len(hits) == 1
                assert hits[0].statement == "Active fact"
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_search_domain_filter(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                now_iso = datetime.now(UTC).isoformat()
                from qdrant_client.models import PointStruct
                await uk.ensure_collection()

                for i, domain in enumerate(["suno_mechanics", "music_theory", "suno_mechanics"]):
                    eid = str(uuid.uuid4())
                    v = [float(i + 1) / 10] * 1024
                    await ms.upsert_raw_points(uk._collection, [
                        PointStruct(id=eid, vector=v, payload={
                            "statement": f"Fact {i}", "domain": domain,
                            "topic_tags": [], "source_type": "manual",
                            "source_ref": None, "examples": [], "created_at": now_iso,
                            "updated_at": now_iso, "confidence": "high",
                            "superseded_by": "", "entry_id": eid,
                        }),
                    ])

                mock_client = MagicMock()
                mock_client.embed = AsyncMock(return_value=[[0.1] * 1024])
                with patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client):
                    hits = await uk.search("query", domain="suno_mechanics", limit=10)

                assert all(h.domain == "suno_mechanics" for h in hits)
                assert len(hits) == 2
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_search_confidence_min_filter(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                now_iso = datetime.now(UTC).isoformat()
                from qdrant_client.models import PointStruct
                await uk.ensure_collection()

                for i, confidence in enumerate(["high", "medium", "low"]):
                    eid = str(uuid.uuid4())
                    v = [float(i + 1) / 10] * 1024
                    await ms.upsert_raw_points(uk._collection, [
                        PointStruct(id=eid, vector=v, payload={
                            "statement": f"Fact {confidence}", "domain": "general",
                            "topic_tags": [], "source_type": "manual",
                            "source_ref": None, "examples": [], "created_at": now_iso,
                            "updated_at": now_iso, "confidence": confidence,
                            "superseded_by": "", "entry_id": eid,
                        }),
                    ])

                mock_client = MagicMock()
                mock_client.embed = AsyncMock(return_value=[[0.1] * 1024])
                with patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client):
                    hits = await uk.search("query", confidence_min="medium", limit=10)

                confidences = {h.confidence for h in hits}
                assert "low" not in confidences
                assert confidences <= {"high", "medium"}
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_supersede_creates_new_and_links_old(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                await uk.ensure_collection()

                mock_client = MagicMock()
                mock_client.embed = AsyncMock(return_value=[[0.5] * 1024])
                with patch("agent_runtime.memory.store.get_embedding_client", return_value=mock_client):
                    draft = await uk.propose_entry("Old fact", "general", "manual", confidence="medium")
                    old_id = await uk.confirm_entry(draft.draft_id)

                    new_id = await uk.supersede(
                        old_id, "Updated fact", domain="general", source_type="manual", confidence="high"
                    )

                # Verify old entry has superseded_by = new_id
                old_entry = await uk.get_entry(old_id)
                assert old_entry is not None
                assert old_entry.superseded_by == new_id

                # Verify new entry exists and is active
                new_entry = await uk.get_entry(new_id)
                assert new_entry is not None
                assert new_entry.superseded_by is None
                assert new_entry.statement == "Updated fact"
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())

    def test_get_entry_missing_returns_none(self, tmp_env: Path) -> None:
        async def run() -> None:
            ms, uk = self._make_store()
            try:
                await uk.ensure_collection()
                result = await uk.get_entry(str(uuid.uuid4()))
                assert result is None
            finally:
                await ms._client.delete_collection(uk._collection)

        asyncio.run(run())
