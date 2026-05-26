"""Agent-mode output: chunk + embed + upsert to Qdrant via agent-runtime memory layer."""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent_runtime.memory import (
    MemoryPoint,
    MultimodalInput,
    chunk_document,
    get_memory_store,
)

from yt_intelligence_pipeline.models import AgentModeResult, PipelineResult
from yt_intelligence_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be",):
        return parsed.path.lstrip("/").split("?")[0]
    qs = parse_qs(parsed.query)
    ids = qs.get("v", [])
    if ids:
        return ids[0]
    # Handle /shorts/ and /embed/ URLs
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[-2] in ("shorts", "embed", "v"):
        return parts[-1]
    raise ValueError(f"Could not extract video ID from URL: {url}")


def _agent_data_dir() -> Path:
    from agent_runtime.config import get_config
    return get_config().agent_data_dir


def _source_dir(source_id: str) -> Path:
    video_id = source_id.removeprefix("youtube:")
    return _agent_data_dir() / "sources" / "youtube-tutorials" / video_id


async def ingest_to_qdrant(
    result: PipelineResult,
    *,
    collection_name: str = "tutorial_research",
    processed_by_agent: str = "yt-intelligence-pipeline",
    processed_in_run: str | None = None,
) -> AgentModeResult:
    """Chunk, embed, and upsert a PipelineResult into Qdrant.

    Returns an AgentModeResult with upsert counts.
    """
    video_id = _extract_video_id(result.video_url)
    source_id = f"youtube:{video_id}"
    source_dir = _source_dir(source_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    store = get_memory_store()

    await store.ensure_collection(collection_name, vector_size=1024)

    # ── Persist transcript + metadata to agent-data ────────────────────────────
    (source_dir / "transcript.txt").write_text(result.cleaned_transcript, encoding="utf-8")
    meta = {
        "title": result.video_metadata.get("title", ""),
        "channel": result.video_metadata.get("channel", ""),
        "url": result.video_url,
        "source_id": source_id,
        "tags": result.tags,
        "processed_at": datetime.now(UTC).isoformat(),
    }
    (source_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── Text chunks ───────────────────────────────────────────────────────────
    chunks = chunk_document(result.cleaned_transcript, target_tokens=512, overlap_tokens=64)
    total_chunks = len(chunks)

    run_id = processed_in_run or _current_run_id()

    text_points = [
        MemoryPoint(
            text=chunk.text,
            source_id=source_id,
            source_type="youtube_tutorial",
            source_url=result.video_url,
            source_title=result.video_metadata.get("title"),
            chunk_index=chunk.chunk_index,
            total_chunks=total_chunks,
            processed_by_agent=processed_by_agent,
            processed_in_run=run_id,
            content_type="text",
            domain_tags=result.tags,
            topic_tags=result.tags,
        )
        for chunk in chunks
    ]

    logger.info(f"Upserting {len(text_points)} text chunks to '{collection_name}'...")
    await store.upsert_points(collection_name, text_points)
    text_count = len(text_points)

    # ── Multimodal points (screenshots) ──────────────────────────────────────
    mm_count = 0
    screenshot_entries = [
        ts for ts in result.timestamp_entries
        if ts.get("extracted_image_path")
    ]

    if screenshot_entries:
        screenshots_agent_dir = source_dir / "screenshots"
        screenshots_agent_dir.mkdir(parents=True, exist_ok=True)

        mm_inputs: list[MultimodalInput] = []
        mm_agent_paths: list[Path] = []
        mm_labels: list[str] = []

        for i, ts in enumerate(screenshot_entries, 1):
            src_path = Path(ts["extracted_image_path"])
            if not src_path.exists():
                logger.warning(f"Screenshot not found, skipping: {src_path}")
                continue

            dest_path = screenshots_agent_dir / f"screenshot_{i:03d}.png"
            shutil.copy2(src_path, dest_path)

            mm_inputs.append(MultimodalInput(text=ts["label"], image_path=dest_path))
            mm_agent_paths.append(dest_path)
            mm_labels.append(ts["label"])

        if mm_inputs:
            mm_points = [
                MemoryPoint(
                    text=label,
                    source_id=source_id,
                    source_type="youtube_tutorial",
                    source_url=result.video_url,
                    source_title=result.video_metadata.get("title"),
                    chunk_index=i,
                    total_chunks=len(mm_inputs),
                    processed_by_agent=processed_by_agent,
                    processed_in_run=run_id,
                    content_type="image_with_caption",
                    image_path=str(path),
                    caption=label,
                    domain_tags=result.tags,
                    topic_tags=result.tags,
                )
                for i, (label, path) in enumerate(zip(mm_labels, mm_agent_paths))
            ]

            logger.info(f"Embedding {len(mm_inputs)} multimodal points...")
            try:
                await store.upsert_multimodal_points(collection_name, mm_points, mm_inputs)
                mm_count = len(mm_points)
                logger.info(f"Upserted {mm_count} multimodal points")
            except Exception as exc:
                logger.warning(
                    f"Multimodal embedding failed ({type(exc).__name__}: {exc}). "
                    "Screenshots copied to agent-data but not embedded. "
                    "Re-run with agent mode once the rate limit / billing issue is resolved."
                )

    return AgentModeResult(
        collection_name=collection_name,
        text_points_upserted=text_count,
        multimodal_points_upserted=mm_count,
        source_id=source_id,
    )


def _current_run_id() -> str:
    """Return the current BudgetTracker run_id if one is active, else a ULID."""
    try:
        from agent_runtime.budget import _current_tracker  # type: ignore[attr-defined]
        tracker = _current_tracker.get()
        if tracker is not None:
            return tracker._run_id
    except Exception:
        pass
    from ulid import ULID
    return str(ULID())
