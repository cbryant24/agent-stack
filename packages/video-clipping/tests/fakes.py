"""Test doubles for the paid-boundary clients: LLM provider, Voyage embedder,
faster-whisper model, Qdrant memory store. Zero real network / no model downloads.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.llm import LLMCompletion


@dataclass
class FakeCompletion:
    text: str
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class FakeProvider:
    """LLMProvider double. Pops responses from a queue in call order."""

    name: str = "fake"
    responses: list[FakeCompletion] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    default_response: FakeCompletion = field(
        default_factory=lambda: FakeCompletion(text="{}", input_tokens=10, output_tokens=5)
    )

    def resolve_model(self, alias: str | None) -> str:
        return alias or "claude-sonnet-4-6"

    async def complete(
        self,
        *,
        system: str,
        user_text: str,
        image_paths: Sequence[Path] = (),
        model: str | None = None,
        max_tokens: int,
    ) -> LLMCompletion:
        self.calls.append(
            {
                "system": system,
                "user_text": user_text,
                "image_paths": list(image_paths),
                "model": self.resolve_model(model),
                "max_tokens": max_tokens,
            }
        )
        if self.responses:
            r = self.responses.pop(0)
        else:
            r = self.default_response
        return LLMCompletion(
            text=r.text,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            model=self.resolve_model(model),
        )


def _l2_norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _pseudo_vector(text: str, dim: int = 16) -> list[float]:
    """Deterministic L2-normalized pseudo-vector — identical text → identical vector."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(digest[i % len(digest)] - 128) / 128.0 for i in range(dim)]
    return _l2_norm(raw)


class FakeEmbedder:
    """Voyage EmbeddingClient double. Deterministic pseudo-vectors keyed by text."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        return [_pseudo_vector(t) for t in texts]

    async def embed_multimodal(self, *_a: Any, **_kw: Any) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class FakeWhisperSegment:
    start: float
    end: float
    text: str


class FakeWhisperInfo:
    def __init__(self, duration: float) -> None:
        self.duration = duration


class FakeWhisperModel:
    """faster-whisper WhisperModel double."""

    def __init__(
        self,
        segments: list[FakeWhisperSegment] | None = None,
        duration: float = 9.0,
        raise_on_call: Exception | None = None,
    ) -> None:
        self._segments = segments or []
        self._duration = duration
        self._raise = raise_on_call

    def transcribe(self, *_a: Any, **_kw: Any):
        if self._raise is not None:
            raise self._raise
        return (iter(self._segments), FakeWhisperInfo(self._duration))


def fake_provider_from_json(items: list[str]) -> FakeProvider:
    """Convenience: build a FakeProvider whose responses are the given JSON strings."""
    return FakeProvider(
        responses=[FakeCompletion(text=text) for text in items]
    )


# ── FakeMemoryStore (Phase 2) ────────────────────────────────────────────────


@dataclass
class _FakePoint:
    id: str
    vector: list[float]
    payload: dict[str, Any]


class _FakeInnerClient:
    """Stub for MemoryStore._client — only implements what VideoClippingStore reaches for."""

    def __init__(self, parent: FakeMemoryStore) -> None:
        self._parent = parent
        self.indexed_fields: list[tuple[str, str]] = []

    async def create_payload_index(
        self, *, collection_name: str, field_name: str, field_schema: Any
    ) -> None:
        self.indexed_fields.append((collection_name, field_name))

    async def get_collections(self) -> Any:  # pragma: no cover
        raise NotImplementedError


class FakeMemoryStore:
    """In-memory MemoryStore double.

    Supports the methods VideoClippingStore actually calls: ensure_collection,
    upsert_raw_points, query_by_vector (with must / must_not FieldCondition
    filters), retrieve_points, and the embedding_client property. All vectors
    are treated as L2-normalized; cosine == dot product.
    """

    def __init__(
        self,
        *,
        raise_on_upsert: bool = False,
        raise_on_query: bool = False,
        embedder: FakeEmbedder | None = None,
    ) -> None:
        self.collections: dict[str, dict[str, _FakePoint]] = {}
        self.embedding_client = embedder or FakeEmbedder()
        self._client = _FakeInnerClient(self)
        self.raise_on_upsert = raise_on_upsert
        self.raise_on_query = raise_on_query
        self.upsert_calls: list[tuple[str, int]] = []
        self.query_calls: list[tuple[str, int]] = []

    async def ensure_collection(self, name: str, vector_size: int = 1024) -> None:
        self.collections.setdefault(name, {})

    async def upsert_raw_points(self, collection: str, points: Iterable[Any]) -> None:
        if self.raise_on_upsert:
            raise RuntimeError("fake Qdrant upsert failure")
        bucket = self.collections.setdefault(collection, {})
        n = 0
        for p in points:
            bucket[str(p.id)] = _FakePoint(
                id=str(p.id),
                vector=list(p.vector),
                payload=dict(p.payload or {}),
            )
            n += 1
        self.upsert_calls.append((collection, n))

    async def query_by_vector(
        self,
        collection: str,
        vector: list[float],
        *,
        limit: int = 10,
        filters: Any = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        if self.raise_on_query:
            raise RuntimeError("fake Qdrant query failure")
        self.query_calls.append((collection, limit))
        bucket = self.collections.get(collection, {})
        matches: list[tuple[str, float, dict[str, Any]]] = []
        for pt in bucket.values():
            if not _matches_filter(pt.payload, filters):
                continue
            score = _cosine(vector, pt.vector)
            matches.append((pt.id, float(score), dict(pt.payload)))
        matches.sort(key=lambda m: m[1], reverse=True)
        return matches[:limit]

    async def retrieve_points(self, collection: str, ids: list[str]) -> list[Any]:
        bucket = self.collections.get(collection, {})
        results: list[Any] = []
        for i in ids:
            if i in bucket:
                pt = bucket[i]
                # Return an object with .id and .payload (qdrant Record-shaped).
                results.append(_FakeRecord(id=pt.id, payload=dict(pt.payload)))
        return results


@dataclass
class _FakeRecord:
    id: str
    payload: dict[str, Any]


def _cosine(a: list[float], b: list[float]) -> float:
    la = _length(a)
    lb = _length(b)
    if la == 0.0 or lb == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return dot / (la * lb)


def _length(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _matches_filter(payload: dict[str, Any], filters: Any) -> bool:
    if filters is None:
        return True
    must = getattr(filters, "must", None) or []
    must_not = getattr(filters, "must_not", None) or []
    for cond in must:
        if not _field_matches(payload, cond):
            return False
    for cond in must_not:
        if _field_matches(payload, cond):
            return False
    return True


def _field_matches(payload: dict[str, Any], cond: Any) -> bool:
    key = getattr(cond, "key", None)
    match = getattr(cond, "match", None)
    if key is None or match is None:
        return False
    value = getattr(match, "value", None)
    if value is None:
        return False
    return payload.get(key) == value
