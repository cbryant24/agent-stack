from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from qdrant_client.models import PointStruct


class MemoryPoint(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    text: str
    source_id: str
    source_type: Literal[
        "youtube_tutorial", "web_page", "user_note", "agent_summary"
    ]
    source_url: str | None = None
    source_title: str | None = None
    chunk_index: int = 0
    total_chunks: int = 1
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed_by_agent: str
    processed_in_run: str
    domain_tags: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_qdrant_point(self, vector: list[float]) -> PointStruct:
        payload = self.model_dump(exclude={"id"})
        payload["processed_at"] = payload["processed_at"].isoformat()
        return PointStruct(
            id=str(self.id),
            vector=vector,
            payload=payload,
        )

    @classmethod
    def from_qdrant_payload(cls, point_id: str, payload: dict[str, Any]) -> MemoryPoint:
        payload = dict(payload)
        return cls(id=uuid.UUID(point_id), **payload)


class SearchResult(BaseModel):
    point: MemoryPoint
    score: float
