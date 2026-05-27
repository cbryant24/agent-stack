from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from anthropic import AsyncAnthropic

from agent_runtime import BudgetEnvelope, BudgetExhaustedError, TraceEvent
from agent_runtime.budget import BudgetTracker
from agent_runtime.config import get_config
from agent_runtime.reporting import notify_run_complete, render_run_report
from agent_runtime.tracing import get_current_persister

from tutorial_research.classify import classify_request
from tutorial_research.constants import (
    COVERAGE_SPARSE_THRESHOLD,
    COVERAGE_THIN_SOURCE_COUNT,
    DEFAULT_BUDGET,
)
from tutorial_research.metadata_filter import fetch_video_metadata
from tutorial_research.models import (
    IngestionPlan,
    IngestedVideo,
    ResearchResult,
    RetrievedChunk,
    ScoredCandidate,
)
from tutorial_research.retrieval import retrieve_chunks
from tutorial_research.scoring import score_candidates
from tutorial_research.search import search_for_tutorials
from tutorial_research.synthesis import synthesize as _synthesize

logger = logging.getLogger(__name__)


def _estimate_cost(n_items: int) -> float:
    return round(n_items * 0.05, 4)


def _emit_coverage_assessment(
    retrieved: list,
    ingested: list,
) -> None:
    retrieved_count = len(retrieved)
    max_score: float | None = max((c.score for c in retrieved), default=None)
    distinct_sources = len({c.source_id for c in retrieved})

    if retrieved_count == 0:
        assessment = "empty"
    elif max_score is not None and max_score < COVERAGE_SPARSE_THRESHOLD:
        assessment = "sparse"
    elif distinct_sources <= COVERAGE_THIN_SOURCE_COUNT:
        assessment = "thin"
    else:
        assessment = "adequate"

    persister = get_current_persister()
    if persister:
        persister.record(
            TraceEvent(
                event_type="info",
                metadata={
                    "event_subtype": "coverage_assessment",
                    "assessment": assessment,
                    "retrieved_count": retrieved_count,
                    "max_score": max_score,
                    "distinct_sources": distinct_sources,
                    "ingested_in_this_run": len(ingested),
                },
            )
        )


def _append_coverage_to_report(run_id: str, agent_name: str, report_path: Path) -> None:
    from agent_runtime.tracing import load_trace

    events = load_trace(run_id, agent_name)
    coverage_events = [
        e for e in events
        if e.event_type == "info"
        and e.metadata.get("event_subtype") == "coverage_assessment"
    ]
    if not coverage_events:
        return

    lines = ["\n\n## Coverage Assessment\n"]
    for e in coverage_events:
        m = e.metadata
        score_str = f"{m['max_score']:.3f}" if m.get("max_score") is not None else "N/A"
        lines.append(f"- **Assessment**: `{m.get('assessment', 'unknown')}`")
        lines.append(f"- **Retrieved chunks**: {m.get('retrieved_count', 0)}")
        lines.append(f"- **Distinct sources**: {m.get('distinct_sources', 0)}")
        lines.append(f"- **Max similarity score**: {score_str}")
        lines.append(f"- **Ingested in this run**: {m.get('ingested_in_this_run', 0)}")

    with report_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


async def _run_research(
    request: str,
    tracker: BudgetTracker,
    do_synthesize: bool,
    dry_run: bool,
    collection: str,
    max_items: int,
    client: AsyncAnthropic,
) -> tuple[IngestionPlan, list[IngestedVideo], list[RetrievedChunk], str | None]:
    from yt_intelligence_pipeline import process_video

    urls: list[str] = []
    tavily_failed = False
    try:
        urls = await search_for_tutorials(request, max_results=20)
    except Exception as exc:
        tavily_failed = True
        logger.warning("Tavily search failed, falling back to retrieve mode: %s", exc)
        persister = get_current_persister()
        if persister:
            persister.record(
                TraceEvent(
                    event_type="info",
                    metadata={"event_subtype": "tavily_degradation", "error": str(exc)},
                )
            )
        retrieved = await retrieve_chunks(collection, request)
        synthesis_text = None
        if do_synthesize:
            synthesis_text = await _synthesize(request, retrieved, tracker, client)
        empty_plan = IngestionPlan(
            candidates=[], selected=[], estimated_cost_usd=0.0, estimated_items=0
        )
        return empty_plan, [], retrieved, synthesis_text

    candidates = []
    for url in urls:
        entry = await fetch_video_metadata(url)
        if entry is not None:
            candidates.append(entry)

    scored = await score_candidates(request, candidates, tracker, client)
    scored.sort(key=lambda s: s.score, reverse=True)
    selected = scored[:max_items]

    plan = IngestionPlan(
        candidates=scored,
        selected=selected,
        estimated_cost_usd=_estimate_cost(len(selected)),
        estimated_items=len(selected),
    )

    persister = get_current_persister()
    if persister:
        persister.record(
            TraceEvent(
                event_type="info",
                metadata={
                    "event_subtype": "ingestion_plan",
                    "plan": plan.model_dump(),
                },
            )
        )

    if dry_run:
        return plan, [], [], None

    ingested: list[IngestedVideo] = []
    for candidate in selected:
        try:
            result = await process_video(
                candidate.url,
                human_output=False,
                agent_output=True,
                collection_name=collection,
            )
            tracker.add_item_processed()
            if result.agent_output:
                video_id = result.agent_output.source_id.removeprefix("youtube:")
                ingested.append(
                    IngestedVideo(
                        video_id=video_id,
                        source_id=result.agent_output.source_id,
                    )
                )
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            logger.warning("Failed to process %s: %s — continuing", candidate.url, exc)

        tracker.check_budget()

    retrieved = await retrieve_chunks(collection, request)
    _emit_coverage_assessment(retrieved, ingested)
    synthesis_text = None
    if do_synthesize:
        synthesis_text = await _synthesize(request, retrieved, tracker, client)

    return plan, ingested, retrieved, synthesis_text


async def _run_ingest(
    request: str,
    tracker: BudgetTracker,
    dry_run: bool,
    collection: str,
    max_items: int,
    client: AsyncAnthropic,
) -> tuple[IngestionPlan, list[IngestedVideo]]:
    from yt_intelligence_pipeline import process_video

    import re

    urls = re.findall(r"https?://\S+", request)

    candidates = []
    for url in urls:
        entry = await fetch_video_metadata(url)
        if entry is not None:
            candidates.append(entry)

    scored = await score_candidates(request, candidates, tracker, client)
    scored.sort(key=lambda s: s.score, reverse=True)
    selected = scored[:max_items]

    plan = IngestionPlan(
        candidates=scored,
        selected=selected,
        estimated_cost_usd=_estimate_cost(len(selected)),
        estimated_items=len(selected),
    )

    persister = get_current_persister()
    if persister:
        persister.record(
            TraceEvent(
                event_type="info",
                metadata={
                    "event_subtype": "ingestion_plan",
                    "plan": plan.model_dump(),
                },
            )
        )

    if dry_run:
        return plan, []

    ingested: list[IngestedVideo] = []
    for candidate in selected:
        try:
            result = await process_video(
                candidate.url,
                human_output=False,
                agent_output=True,
                collection_name=collection,
            )
            tracker.add_item_processed()
            if result.agent_output:
                video_id = result.agent_output.source_id.removeprefix("youtube:")
                ingested.append(
                    IngestedVideo(
                        video_id=video_id,
                        source_id=result.agent_output.source_id,
                    )
                )
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            logger.warning("Failed to process %s: %s — continuing", candidate.url, exc)

        tracker.check_budget()

    return plan, ingested


async def research(
    request: str,
    *,
    budget: BudgetEnvelope | None = None,
    request_type: Literal["research", "ingest", "retrieve"] | None = None,
    synthesize: bool | None = None,
    dry_run: bool = False,
    collection: str = "tutorial_research",
) -> ResearchResult:
    effective_type = classify_request(request, request_type)
    effective_budget = budget or DEFAULT_BUDGET
    do_synthesize = synthesize if synthesize is not None else (effective_type == "research")
    max_items = effective_budget.max_items if effective_budget.max_items is not None else 5

    run_id: str | None = None
    status: Literal["completed", "partial", "failed"] = "completed"
    ingested: list[IngestedVideo] = []
    retrieved: list[RetrievedChunk] = []
    synthesis_text: str | None = None
    plan: IngestionPlan | None = None
    tracker_ref: BudgetTracker | None = None

    client = AsyncAnthropic(api_key=get_config().anthropic_api_key)

    try:
        async with BudgetTracker(effective_budget, "tutorial-research") as tracker:
            tracker_ref = tracker
            run_id = tracker.run_id

            if effective_type == "research":
                plan, ingested, retrieved, synthesis_text = await _run_research(
                    request, tracker, do_synthesize, dry_run, collection, max_items, client
                )
            elif effective_type == "ingest":
                plan, ingested = await _run_ingest(
                    request, tracker, dry_run, collection, max_items, client
                )
                if do_synthesize and not dry_run:
                    retrieved = await retrieve_chunks(collection, request)
                    synthesis_text = await _synthesize(request, retrieved, tracker, client)
            else:
                retrieved = await retrieve_chunks(collection, request)
                if do_synthesize:
                    synthesis_text = await _synthesize(request, retrieved, tracker, client)

    except BudgetExhaustedError:
        status = "partial"

    # Capture consumption stats after context exits — works for both completed and partial runs
    snap = tracker_ref._consumption if tracker_ref is not None else None
    cost_usd = snap.cost_usd if snap is not None else 0.0
    items_processed = snap.items_processed if snap is not None else 0
    wall_time_sec = snap.wall_time_sec if snap is not None else 0.0

    report_path = None
    if run_id:
        try:
            report_path = render_run_report(run_id, "tutorial-research")
            if report_path:
                _append_coverage_to_report(run_id, "tutorial-research", report_path)
        except Exception as exc:
            logger.warning("Failed to render run report: %s", exc)
        notify_run_complete("tutorial-research", run_id, status, cost_usd)

    return ResearchResult(
        request_type=effective_type,
        run_id=run_id or "",
        status=status,
        ingested=ingested,
        retrieved=retrieved,
        synthesis=synthesis_text,
        plan=plan,
        cost_usd=cost_usd,
        items_processed=items_processed,
        wall_time_sec=wall_time_sec,
        report_path=report_path,
    )


def research_sync(
    request: str,
    *,
    budget: BudgetEnvelope | None = None,
    request_type: Literal["research", "ingest", "retrieve"] | None = None,
    synthesize: bool | None = None,
    dry_run: bool = False,
    collection: str = "tutorial_research",
) -> ResearchResult:
    return asyncio.run(
        research(
            request,
            budget=budget,
            request_type=request_type,
            synthesize=synthesize,
            dry_run=dry_run,
            collection=collection,
        )
    )
