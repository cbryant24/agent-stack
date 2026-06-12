"""TechniqueResearchStore — the owner-writes layer over `technique_research_outputs`.

Findings are text-embedded (`voyage-3-large`, the same space as `tutorial_research`
and `user_knowledge`), so the orchestrator's `search_knowledge` reads this collection
with no cross-space mismatch. The agent's own `check` step is the retrieval consumer
that earns the collection.
"""
from __future__ import annotations

from agent_runtime import MemoryStore

from technique_research.constants import TECHNIQUE_OUTPUTS_COLLECTION
from technique_research.models import TechniqueFinding


class TechniqueResearchStore:
    def __init__(
        self,
        memory_store: MemoryStore,
        collection_name: str = TECHNIQUE_OUTPUTS_COLLECTION,
    ) -> None:
        self._store = memory_store
        self._collection = collection_name

    async def ensure_collection(self) -> None:
        await self._store.ensure_collection(self._collection, vector_size=1024)

    async def upsert_findings(
        self, findings: list[TechniqueFinding], run_id: str
    ) -> list[str]:
        """Embed and write findings. Returns the point ids written."""
        if not findings:
            return []
        await self.ensure_collection()
        points = [f.to_memory_point(run_id) for f in findings]
        await self._store.upsert_points(self._collection, points)
        return [str(p.id) for p in points]

    async def search_findings(
        self, query: str, *, limit: int = 6
    ) -> list[tuple[float, TechniqueFinding]]:
        """Return (score, finding) pairs ordered by similarity. Degrades to []
        if the collection does not exist yet (first run)."""
        try:
            results = await self._store.search(self._collection, query_text=query, limit=limit)
        except Exception:
            return []
        return [
            (r.score, TechniqueFinding.from_payload(r.point.metadata))
            for r in results
            if r.point.metadata
        ]
