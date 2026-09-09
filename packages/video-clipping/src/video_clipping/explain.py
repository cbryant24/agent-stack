"""`clip explain <question>` — grounded semantic search across video_clipping_memory.

Single Sonnet call. Retrieval fans out per-memory-type (segment / run / lesson),
top-K each, merged and reranked by score. Cost is capped upfront by a projection
from question length + top-K + typical output — refusal before any provider call.

Traces via the ambient BudgetTracker if one exists (opened by the CLI). The
`_record_llm` bridge routes usage to the tracker or a bare trace, matching the
vision/decide stages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime import (
    BudgetEnvelope,
    BudgetTracker,
    TracePersister,
    get_memory_store,
    get_provider,
)
from agent_runtime.budget import _PRICING

from video_clipping.constants import (
    AGENT_NAME,
    EXPLAIN_INCLUDE_TYPES_DEFAULT,
    EXPLAIN_MAX_TOKENS,
    EXPLAIN_MAX_USD_DEFAULT,
    EXPLAIN_SYSTEM_PROMPT_TOKENS,
    EXPLAIN_TOKENS_PER_SNIPPET,
    EXPLAIN_TOP_K_DEFAULT,
    EXPLAIN_TYPICAL_OUTPUT_TOKENS,
    GENERATE_MAX_WALL_TIME_SEC,
    PHASE1_MODEL_ID,
)
from video_clipping.store import VideoClippingStore
from video_clipping.vision.summarize import _record_llm

logger = logging.getLogger(__name__)


EXPLAIN_SYSTEM_PROMPT = (
    "You are the video-clipping agent's tutor. Answer the user's question "
    "grounded in the retrieved memories below. Cite specific runs and segments "
    "by their IDs (e.g., \"run 4a8b… segment 6f2c…\"). If the memories don't "
    "cover the question, say so plainly rather than speculating."
)


@dataclass
class ExplainHit:
    """One retrieved memory point rendered for LLM context + user Sources block."""

    memory_type: str
    point_id: str
    score: float
    payload: dict[str, Any]

    def snippet(self) -> str:
        run_id = str(self.payload.get("run_id", ""))
        if self.memory_type == "segment":
            decision = self.payload.get("decision") or {}
            summary = decision.get("one_line_summary") or "(no summary)"
            theme = decision.get("theme_match")
            clip = self.payload.get("clip_path") or ""
            clip_name = clip.rsplit("/", 1)[-1] if clip else ""
            theme_str = f"theme={theme:.2f} " if isinstance(theme, (int, float)) else ""
            seg_id = str(self.payload.get("segment_id", ""))
            return (
                f"[segment score={self.score:.2f} run={run_id[:8]} seg={seg_id[:8]}] "
                f"{summary} — {theme_str}{clip_name}"
            )
        if self.memory_type == "run":
            spec = self.payload.get("spec") or {}
            event = spec.get("event_type") or self.payload.get("event_type") or "?"
            accepted = len(self.payload.get("accepted_segment_ids") or [])
            location = self.payload.get("location") or spec.get("location", "?")
            return (
                f"[run score={self.score:.2f} run={run_id[:8]} event={event} "
                f"accepted={accepted}] {location}"
            )
        if self.memory_type == "lesson":
            source_run = str(self.payload.get("source_run_id") or "")
            pattern = self.payload.get("pattern_type") or "manual"
            text = (
                self.payload.get("human_summary")
                or self.payload.get("statement")
                or "(empty lesson)"
            )
            return (
                f"[lesson score={self.score:.2f} pattern={pattern} "
                f"source_run={source_run[:8]}] {text}"
            )
        return f"[{self.memory_type} score={self.score:.2f}] {self.payload}"

    def source_line(self) -> str:
        run_id = str(self.payload.get("run_id", ""))[:8]
        seg_id = str(self.payload.get("segment_id", ""))[:8] if self.memory_type == "segment" else ""
        tail = f"segment={seg_id}" if seg_id else ""
        return f"- [{self.memory_type}] score={self.score:.3f} run={run_id or '—'} {tail}".rstrip()


@dataclass
class ExplainResult:
    question: str
    answer: str
    hits: list[ExplainHit] = field(default_factory=list)
    projected_usd: float = 0.0
    actual_usd: float = 0.0
    model: str = PHASE1_MODEL_ID


def _price_call(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def _project_cost(question: str, top_k: int, model: str) -> tuple[float, int, int]:
    question_tokens = max(1, len(question) // 4)
    input_tokens = (
        EXPLAIN_SYSTEM_PROMPT_TOKENS
        + question_tokens
        + top_k * EXPLAIN_TOKENS_PER_SNIPPET
    )
    output_tokens = EXPLAIN_TYPICAL_OUTPUT_TOKENS
    return _price_call(model, input_tokens, output_tokens), input_tokens, output_tokens


def _parse_include_types(raw: str) -> list[str]:
    valid = {"segment", "run", "lesson"}
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [p for p in parts if p not in valid]
    if unknown:
        raise ValueError(
            f"unknown --include-types entries {unknown}; valid: {sorted(valid)}"
        )
    if not parts:
        raise ValueError("--include-types is empty")
    return parts


async def _retrieve_hits(
    *,
    store: VideoClippingStore,
    query_vector: list[float],
    include_types: list[str],
    top_k: int,
) -> list[ExplainHit]:
    hits: list[ExplainHit] = []
    for t in include_types:
        raw = await store.query_nearest(query_vector, top_k=top_k, filter_by_type=t)
        for point_id, score, payload in raw:
            hits.append(
                ExplainHit(
                    memory_type=t, point_id=point_id, score=float(score), payload=payload
                )
            )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


async def explain_sync(
    question: str,
    *,
    max_usd: float = EXPLAIN_MAX_USD_DEFAULT,
    top_k: int = EXPLAIN_TOP_K_DEFAULT,
    include_types: str = EXPLAIN_INCLUDE_TYPES_DEFAULT,
    store: VideoClippingStore | None = None,
) -> ExplainResult:
    types = _parse_include_types(include_types)
    model = PHASE1_MODEL_ID

    projected, projected_input, projected_output = _project_cost(question, top_k, model)
    if projected > max_usd:
        raise PreflightCostRefusal(
            f"projected cost ${projected:.4f} exceeds --max-usd ${max_usd:.4f} "
            f"(≈{projected_input} in, {projected_output} out tokens on {model}). "
            f"Raise --max-usd or lower --top-k."
        )

    if store is None:
        store = VideoClippingStore(get_memory_store())
    try:
        await store.ensure_collection()
    except Exception as exc:
        raise QdrantUnavailable(
            "Qdrant is unreachable. Start it via `infrastructure/docker-compose.yml` "
            "(see agent-stack README → Qdrant Collections)."
        ) from exc

    envelope = BudgetEnvelope(
        max_items=1,
        max_cost_usd=max_usd,
        max_wall_time_sec=GENERATE_MAX_WALL_TIME_SEC,
        max_depth=0,
    )
    async with BudgetTracker(envelope, AGENT_NAME) as tracker:
        with TracePersister(agent=AGENT_NAME, run_id=tracker.run_id):
            try:
                embedder = store._store.embedding_client
                [qv] = await embedder.embed([question], input_type="query")
                hits = await _retrieve_hits(
                    store=store,
                    query_vector=qv,
                    include_types=types,
                    top_k=top_k,
                )
            except Exception as exc:
                raise QdrantUnavailable(
                    "Qdrant query failed mid-explain; check the Qdrant server."
                ) from exc

            context = _assemble_context(hits)
            provider = get_provider()
            comp = await provider.complete(
                system=EXPLAIN_SYSTEM_PROMPT,
                user_text=f"{question}\n\n{context}",
                model=model,
                max_tokens=EXPLAIN_MAX_TOKENS,
            )
            _record_llm(comp.model, comp.input_tokens, comp.output_tokens)
            actual = _price_call(comp.model, comp.input_tokens, comp.output_tokens)

    return ExplainResult(
        question=question,
        answer=comp.text.strip(),
        hits=hits,
        projected_usd=projected,
        actual_usd=actual,
        model=comp.model,
    )


def _assemble_context(hits: list[ExplainHit]) -> str:
    if not hits:
        return "RETRIEVED MEMORIES\n------------------\n(none)"
    lines = ["RETRIEVED MEMORIES", "------------------"]
    lines.extend(h.snippet() for h in hits)
    return "\n".join(lines)


def render_explain(result: ExplainResult) -> str:
    parts = [result.answer or "(empty answer)", "", "── Sources ──"]
    if not result.hits:
        parts.append("(no memories retrieved)")
    else:
        parts.extend(h.source_line() for h in result.hits)
    parts.append("")
    parts.append(
        f"cost: projected ${result.projected_usd:.4f}, "
        f"actual ${result.actual_usd:.4f} (model {result.model})"
    )
    return "\n".join(parts)


class PreflightCostRefusal(Exception):
    """Raised when the projected cost exceeds --max-usd; no provider call happens."""


class QdrantUnavailable(Exception):
    """Raised when Qdrant cannot serve the explain request."""
