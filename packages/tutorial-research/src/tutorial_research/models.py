from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class CandidateEntry(BaseModel):
    url: str
    title: str
    channel: str
    description: str
    duration_seconds: int
    view_count: int
    upload_date: str
    has_captions: bool


class ScoredCandidate(BaseModel):
    url: str
    title: str
    channel: str
    duration_seconds: int
    view_count: int
    has_captions: bool
    score: int
    rationale: str


class IngestionPlan(BaseModel):
    candidates: list[ScoredCandidate]
    selected: list[ScoredCandidate]
    estimated_cost_usd: float
    estimated_items: int


class IngestedVideo(BaseModel):
    video_id: str
    source_id: str


class RetrievedChunk(BaseModel):
    score: float
    source_id: str
    content: str
    source_title: str | None = None
    source_url: str | None = None
    chunk_index: int | None = None
    collection_name: str | None = None


class ResearchResult(BaseModel):
    request_type: Literal["research", "ingest", "retrieve"]
    run_id: str
    status: Literal["completed", "partial", "failed"]
    ingested: list[IngestedVideo]
    retrieved: list[RetrievedChunk]
    synthesis: str | None = None
    plan: IngestionPlan | None = None
    cost_usd: float
    items_processed: int
    wall_time_sec: float
    report_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}
