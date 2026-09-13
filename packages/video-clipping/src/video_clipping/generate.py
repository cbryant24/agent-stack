"""`clip generate` orchestrator — Stages 2–6 + Phase-2 Qdrant persistence.

Shape mirrors `visual_generation/generate.py`:
- `async with BudgetTracker(envelope, AGENT_NAME) as tracker:` — a single
  envelope covers per-item and per-cost caps.
- Inner `TracePersister` — redundant with the one BudgetTracker opens, but
  mirrored verbatim for parity with visual-generation.
- Per-segment try/except keeps the run going on individual failures; whole-run
  failures (Whisper, ffprobe) short-circuit to status="failed".
- `BudgetExhaustedError` bubbles out of the segment loop → status="partial",
  whatever's been accepted so far still gets cut.

Phase 2 adds an opt-in cross-run dedupe stage (uses vectors already computed
by intra-run dedupe), best-effort Qdrant persistence of run + accepted
segments + auto-accrued lessons, and lesson surfacing into the decide prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_runtime import (
    BudgetEnvelope,
    BudgetExhaustedError,
    BudgetTracker,
    TracePersister,
    get_memory_store,
    get_provider,
    notify_run_complete,
    render_run_report,
)
from agent_runtime.llm import LLMProvider

from video_clipping.audio.slice import slice_transcript
from video_clipping.audio.transcribe import transcribe
from video_clipping.constants import (
    AGENT_NAME,
    GENERATE_MAX_WALL_TIME_SEC,
    SIMILARITY_THRESHOLD,
    WHISPER_MODEL_DEFAULT,
)
from video_clipping.cut import cut_clip, has_audio_stream
from video_clipping.decide import decide_segment
from video_clipping.exceptions import (
    CutError,
    DecisionParseError,
    FfprobeError,
    TranscriptionError,
    VisionError,
)
from video_clipping.lesson import accrue_lessons, surface_lessons_for_spec
from video_clipping.models import ClipDecision, Run, RunStatus
from video_clipping.plan import save_run
from video_clipping.similarity import (
    CrossRunHit,
    apply_cross_run_dedupe,
    dedupe,
    embed_summaries,
    flip_to_cross_run_duplicate,
)
from video_clipping.store import VideoClippingStore
from video_clipping.vision import sample_frames, summarize_segment

logger = logging.getLogger(__name__)


def _make_error_decision(seg_id: str, start: float, end: float, exc: Exception) -> ClipDecision:
    return ClipDecision(
        segment_id=seg_id,
        action="exclude",
        refined_start=start,
        refined_end=end,
        exclude_reason="error",
        theme_match=0.0,
        confidence=0.0,
        one_line_summary=f"[error] {type(exc).__name__}: {exc}"[:200],
    )


def _dry_run_decisions(run: Run) -> list[ClipDecision]:
    """No LLM/embedding/whisper calls: include every segment as-is."""
    return [
        ClipDecision(
            segment_id=seg.segment_id,
            action="include",
            refined_start=seg.start,
            refined_end=seg.end,
            theme_match=0.5,
            confidence=0.5,
            one_line_summary=f"[dry-run] segment {seg.segment_id[:8]}",
        )
        for seg in run.segments
    ]


async def _process_segments(
    run: Run,
    tracker: BudgetTracker,
    provider: LLMProvider,
    scratch_dir: Path,
    prior_lessons: list[str],
) -> tuple[list[ClipDecision], list[ClipDecision], str | None]:
    """Return (all_decisions_in_order, accepted, halted_reason_or_None)."""
    all_decisions: list[ClipDecision] = []
    accepted: list[ClipDecision] = []
    kept_summaries: list[str] = []
    halted_reason: str | None = None

    for seg in run.segments:
        try:
            tracker.check_budget()
        except BudgetExhaustedError as exc:
            halted_reason = str(exc)
            break

        try:
            frames = sample_frames(run.spec.video, seg, scratch_dir)
            seg.visual_summary = await summarize_segment(provider, seg, frames)
            decision = await decide_segment(
                provider, run.spec, seg, kept_summaries, prior_lessons
            )
        except BudgetExhaustedError as exc:
            halted_reason = str(exc)
            break
        except (VisionError, DecisionParseError) as exc:
            decision = _make_error_decision(seg.segment_id, seg.start, seg.end, exc)

        all_decisions.append(decision)
        tracker.add_item_processed()

        if decision.action in ("include", "trim"):
            accepted.append(decision)
            kept_summaries.append(decision.one_line_summary)

    return all_decisions, accepted, halted_reason


async def _dedupe_accepted(
    all_decisions: list[ClipDecision], accepted: list[ClipDecision]
) -> tuple[list[ClipDecision], list[ClipDecision], dict[str, list[float]]]:
    """Intra-run dedupe. Returns (all_decisions_updated, kept, embeddings_by_segment_id)."""
    if not accepted:
        return all_decisions, accepted, {}
    vectors = await embed_summaries([d.one_line_summary for d in accepted])
    kept, duped = dedupe(accepted, vectors)
    if duped:
        by_id = {d.segment_id: d for d in duped}
        all_decisions = [by_id.get(d.segment_id, d) for d in all_decisions]
    embeddings = {d.segment_id: v for d, v in zip(accepted, vectors, strict=True)}
    return all_decisions, kept, embeddings


async def _apply_cross_run(
    *,
    all_decisions: list[ClipDecision],
    kept: list[ClipDecision],
    embeddings: dict[str, list[float]],
    current_run_id: str,
    store: VideoClippingStore,
    threshold: float,
) -> tuple[list[ClipDecision], list[ClipDecision], list[CrossRunHit]]:
    """Drop cross-run duplicates. Mirrors intra-run flip semantics."""
    if not kept:
        return all_decisions, kept, []
    try:
        await store.ensure_collection()
    except Exception as exc:
        logger.warning(
            "Cross-run dedupe skipped (Qdrant unreachable?): %s", exc
        )
        return all_decisions, kept, []

    outcome = await apply_cross_run_dedupe(
        decisions=kept,
        embeddings=embeddings,
        current_run_id=current_run_id,
        store=store,
        threshold=threshold,
    )
    if not outcome.hits:
        return all_decisions, outcome.kept, []

    flipped_by_id = {
        hit.segment_id: flip_to_cross_run_duplicate(
            next(d for d in kept if d.segment_id == hit.segment_id)
        )
        for hit in outcome.hits
    }
    all_decisions = [flipped_by_id.get(d.segment_id, d) for d in all_decisions]
    return all_decisions, outcome.kept, outcome.hits


def _cut_all(
    run: Run,
    accepted: list[ClipDecision],
    all_decisions: list[ClipDecision],
    clips_dir: Path,
) -> tuple[list[Path], list[ClipDecision]]:
    """Cut every accepted decision; on per-clip failure, flip that decision to
    action="exclude", exclude_reason="error" so the report tells the truth."""
    audio_cache: dict[Path, bool] = {}
    has_audio_stream(run.spec.video, cache=audio_cache)

    clip_paths: list[Path] = []
    surviving: list[ClipDecision] = []
    for i, decision in enumerate(accepted, start=1):
        try:
            path = cut_clip(run.spec.video, decision, i, clips_dir, audio_cache=audio_cache)
        except CutError as exc:
            failed = _make_error_decision(
                decision.segment_id, decision.refined_start, decision.refined_end, exc
            )
            all_decisions = [
                failed if d.segment_id == decision.segment_id else d
                for d in all_decisions
            ]
            continue
        clip_paths.append(path)
        surviving.append(decision)
    return clip_paths, surviving


async def _persist_to_qdrant(
    *,
    run: Run,
    all_decisions: list[ClipDecision],
    surviving: list[ClipDecision],
    embeddings: dict[str, list[float]],
    cross_run_hits: list[CrossRunHit],
    clip_paths_by_segment_id: dict[str, str],
    store: VideoClippingStore,
) -> tuple[list[str], bool]:
    """Persist run + accepted segments + lessons. Returns (lesson_ids, deviation).

    On any failure, sets `deviation=True` and returns whatever was persisted so
    far; never re-raises. Callers must persist the returned deviation flag on
    disk so a follow-up phase can backfill.
    """
    lesson_ids: list[str] = []
    deviation = False
    try:
        await store.ensure_collection()

        # Segments first, so a partial failure still leaves an anchor for the
        # segment vectors when the run row fails to write.
        segment_map = {seg.segment_id: seg for seg in run.segments}
        for decision in surviving:
            seg = segment_map.get(decision.segment_id)
            if seg is None:
                continue
            await store.upsert_segment(
                run=run,
                segment=seg,
                decision=decision,
                clip_path=clip_paths_by_segment_id.get(decision.segment_id),
                precomputed_vector=embeddings.get(decision.segment_id),
            )

        lessons = accrue_lessons(run, all_decisions, cross_run_hits)
        for lesson in lessons:
            try:
                await store.upsert_lesson(lesson)
                lesson_ids.append(lesson.lesson_id)
            except Exception:
                logger.exception("lesson upsert failed for %s", lesson.lesson_id)

        # Run last, with the lesson_ids captured in payload.
        run.lessons_recorded = lesson_ids
        await store.upsert_run(run)
    except Exception as exc:
        logger.warning(
            "Qdrant persistence skipped (Qdrant unreachable?): %s. "
            "Run remains successful on disk with qdrant_deviation=True. "
            "Start Qdrant with `docker compose -f infrastructure/docker-compose.yml up -d` "
            "and re-run to persist this run's memory.",
            exc,
        )
        deviation = True
    return lesson_ids, deviation


async def generate_sync(
    run: Run,
    plan_path: Path,
    max_usd: float,
    whisper_model: str = WHISPER_MODEL_DEFAULT,
    dry_run: bool = False,
    cross_run_dedupe: bool = False,
    cross_run_threshold: float = SIMILARITY_THRESHOLD,
    use_lessons: bool = True,
    store: VideoClippingStore | None = None,
) -> Run:
    envelope = BudgetEnvelope(
        max_items=len(run.segments) if run.segments else 1,
        max_cost_usd=max_usd,
        max_wall_time_sec=GENERATE_MAX_WALL_TIME_SEC,
        max_depth=0,
    )
    run_dir = plan_path.parent
    clips_dir = run_dir / "clips"
    scratch_dir = run_dir / "_frames"

    status: RunStatus = "completed"
    halted_reason: str | None = None
    all_decisions: list[ClipDecision] = []
    accepted: list[ClipDecision] = []
    clip_paths: list[Path] = []
    actual_cost_usd: float = 0.0
    embeddings: dict[str, list[float]] = {}
    cross_run_hits: list[CrossRunHit] = []

    if store is None:
        store = VideoClippingStore(get_memory_store())

    try:
        async with BudgetTracker(envelope, AGENT_NAME, run_id=run.run_id) as tracker:
            with TracePersister(agent=AGENT_NAME, run_id=run.run_id):
                prior_lessons: list[str] = []
                if not dry_run and use_lessons:
                    prior_lessons = await surface_lessons_for_spec(run, store)

                if dry_run:
                    all_decisions = _dry_run_decisions(run)
                    accepted = list(all_decisions)
                else:
                    transcript = transcribe(run.spec.video, whisper_model)
                    for seg in run.segments:
                        seg.transcript = slice_transcript(transcript, seg)

                    provider = get_provider()
                    all_decisions, accepted, seg_halt = await _process_segments(
                        run, tracker, provider, scratch_dir, prior_lessons
                    )
                    if seg_halt is not None:
                        status = "partial"
                        halted_reason = seg_halt
                    else:
                        try:
                            all_decisions, accepted, embeddings = await _dedupe_accepted(
                                all_decisions, accepted
                            )
                        except BudgetExhaustedError as exc:
                            status = "partial"
                            halted_reason = str(exc)

                        if cross_run_dedupe and accepted:
                            (
                                all_decisions,
                                accepted,
                                cross_run_hits,
                            ) = await _apply_cross_run(
                                all_decisions=all_decisions,
                                kept=accepted,
                                embeddings=embeddings,
                                current_run_id=run.run_id,
                                store=store,
                                threshold=cross_run_threshold,
                            )

                clip_paths, accepted = _cut_all(run, accepted, all_decisions, clips_dir)
                actual_cost_usd = tracker.consumption.cost_usd
    except BudgetExhaustedError as exc:
        status = "partial"
        halted_reason = str(exc)
    except (TranscriptionError, FfprobeError) as exc:
        status = "failed"
        halted_reason = str(exc)

    run.decisions = all_decisions
    run.accepted_segment_ids = [d.segment_id for d in accepted]
    run.clip_paths = clip_paths if status != "failed" else []
    run.actual_cost_usd = actual_cost_usd
    run.status = status
    run.halted_reason = halted_reason
    run.cross_run_hits = [h.to_payload() for h in cross_run_hits]
    save_run(run, run_dir)

    # Phase-2: persist to Qdrant if the run produced anything. Never fails the run.
    if not dry_run and status != "failed" and accepted:
        clip_paths_by_seg = {
            d.segment_id: str(p) for d, p in zip(accepted, clip_paths, strict=False)
        }
        lesson_ids, deviation = await _persist_to_qdrant(
            run=run,
            all_decisions=all_decisions,
            surviving=accepted,
            embeddings=embeddings,
            cross_run_hits=cross_run_hits,
            clip_paths_by_segment_id=clip_paths_by_seg,
            store=store,
        )
        run.lessons_recorded = lesson_ids
        run.qdrant_deviation = deviation
        save_run(run, run_dir)

    # Best-effort: shared cost/trace-based report.
    try:
        render_run_report(run.run_id, AGENT_NAME)
    except FileNotFoundError:
        pass
    notify_run_complete(AGENT_NAME, run.run_id, status, actual_cost_usd)
    return run
