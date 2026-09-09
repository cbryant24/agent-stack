"""video-clipping run report.

Wraps agent-runtime's `render_run_report` (which produces the standard
cost/LLM/tool report from trace.jsonl) and appends video-clipping-specific
sections: per-segment decisions table, output clips list, cost delta.

Phase 2 adds three Qdrant-backed sections after the per-segment table:
- Cross-run dedupe (from run.cross_run_hits captured at generate time)
- Related prior clips (top-3 neighbours from other runs, queried at report time)
- Lessons recorded this run (retrieved from Qdrant by run.lessons_recorded)

Each Phase-2 section wraps its Qdrant work in try/except and degrades to a
"(Qdrant unavailable)" header so a Qdrant outage never breaks the report.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_runtime import get_memory_store, render_run_report as _shared_render

from video_clipping.constants import AGENT_NAME
from video_clipping.models import ClipDecision, Run
from video_clipping.store import VideoClippingStore

logger = logging.getLogger(__name__)


def _fmt(x: float | None, spec: str = ".4f") -> str:
    if x is None:
        return "—"
    return format(x, spec)


def _segments_table(run: Run) -> str:
    if not run.decisions:
        return "_no decisions recorded_"
    header = (
        "| # | segment_id | start → end | refined_start → refined_end | action | "
        "exclude_reason | theme | conf | summary |\n"
        "|---:|---|---|---|---|---|---:|---:|---|"
    )
    by_id = {seg.segment_id: seg for seg in run.segments}
    rows = []
    for i, d in enumerate(run.decisions, start=1):
        seg = by_id.get(d.segment_id)
        seg_win = f"{seg.start:.2f}→{seg.end:.2f}s" if seg else "?"
        cell_summary = d.one_line_summary.replace("|", "\\|")
        rows.append(
            f"| {i} | `{d.segment_id[:8]}` | {seg_win} | "
            f"{d.refined_start:.2f}→{d.refined_end:.2f}s | **{d.action}** | "
            f"{d.exclude_reason or '—'} | {d.theme_match:.2f} | "
            f"{d.confidence:.2f} | {cell_summary} |"
        )
    return "\n".join([header, *rows])


def _clips_section(run: Run) -> str:
    if not run.clip_paths:
        return "_no clips produced_"
    return "\n".join(f"- `{p}`" for p in run.clip_paths)


def _cost_section(run: Run) -> str:
    projected = run.cost_estimate.projected_usd
    actual = run.actual_cost_usd
    lines = [
        f"- projected_usd: **${_fmt(projected)}**",
        f"- actual_cost_usd: **${_fmt(actual)}**",
        f"- status: **{run.status or 'unknown'}**",
    ]
    if run.halted_reason:
        lines.append(f"- halted_reason: {run.halted_reason}")
    accepted_count = sum(1 for d in run.decisions if d.action in ("include", "trim"))
    excluded_count = sum(1 for d in run.decisions if d.action == "exclude")
    lines.append(
        f"- decisions: {len(run.decisions)} total "
        f"({accepted_count} accepted, {excluded_count} excluded, "
        f"{len(run.clip_paths)} cut)"
    )
    if run.qdrant_deviation:
        lines.append("- **qdrant_deviation**: memory writes failed for this run")
    return "\n".join(lines)


def _cross_run_section(run: Run) -> str:
    if not run.cross_run_hits:
        return ""
    lines = ["", "## Cross-run dedupe", ""]
    for hit in run.cross_run_hits:
        lines.append(
            f"- dropped `{hit.get('segment_id', '?')[:8]}` "
            f"({hit.get('one_line_summary', '')}) → matched prior run "
            f"`{str(hit.get('prior_run_id', '?'))[:8]}` "
            f"segment `{str(hit.get('prior_segment_id', '?'))[:8]}` "
            f"({hit.get('prior_one_line', '')}) — score {float(hit.get('score', 0.0)):.3f}"
        )
    return "\n".join(lines)


async def _related_prior_clips_lines(
    run: Run, accepted: list[ClipDecision], store: VideoClippingStore
) -> list[str]:
    if not accepted:
        return ["_no accepted clips_"]
    embedder = store._store.embedding_client
    vectors = await embedder.embed(
        [d.one_line_summary for d in accepted], input_type="query"
    )
    lines: list[str] = []
    for decision, vector in zip(accepted, vectors, strict=True):
        hits = await store.query_nearest(
            vector, top_k=3, filter_by_type="segment", exclude_run_ids=[run.run_id]
        )
        if not hits:
            lines.append(
                f"- `{decision.segment_id[:8]}` ({decision.one_line_summary}): "
                f"no prior clips"
            )
            continue
        lines.append(
            f"- `{decision.segment_id[:8]}` ({decision.one_line_summary}):"
        )
        for point_id, score, payload in hits:
            prior_run = str(payload.get("run_id", ""))[:8]
            prior_seg = str(payload.get("segment_id", ""))[:8]
            summary = (payload.get("decision") or {}).get("one_line_summary") or ""
            lines.append(
                f"    - prior `{prior_run}/{prior_seg}` score={score:.3f} — {summary}"
            )
    return lines


async def _related_prior_clips_section(run: Run, store: VideoClippingStore) -> str:
    accepted = [
        d for d in run.decisions if d.action in ("include", "trim") and d.exclude_reason is None
    ]
    try:
        lines = await _related_prior_clips_lines(run, accepted, store)
    except Exception:
        logger.exception("related-prior-clips section: Qdrant query failed")
        return "\n## Related prior clips\n\n_(Qdrant unavailable)_"
    return "\n".join(["", "## Related prior clips", "", *lines])


async def _lessons_section(run: Run, store: VideoClippingStore) -> str:
    if not run.lessons_recorded:
        return ""
    try:
        payloads = await store.retrieve_lessons(run.lessons_recorded)
    except Exception:
        logger.exception("lessons section: Qdrant query failed")
        return "\n## Lessons recorded this run\n\n_(Qdrant unavailable)_"
    if not payloads:
        return ""
    lines = ["", "## Lessons recorded this run", ""]
    for payload in payloads:
        pattern = payload.get("pattern_type", "?")
        summary = payload.get("human_summary") or payload.get("statement") or ""
        lines.append(f"- **{pattern}** — {summary}")
    return "\n".join(lines)


async def render_run_report_rich(
    run: Run, store: VideoClippingStore | None = None
) -> Path:
    """Render the run report (shared + per-segment + Phase-2 memory sections)."""
    path = _shared_render(run.run_id, AGENT_NAME)
    body = path.read_text(encoding="utf-8")

    if store is None:
        store = VideoClippingStore(get_memory_store())

    extra_parts = [
        "\n\n## Cost\n\n",
        _cost_section(run),
        "\n\n## Segments\n\n",
        _segments_table(run),
        "\n\n## Clips\n\n",
        _clips_section(run),
    ]
    cross_run = _cross_run_section(run)
    if cross_run:
        extra_parts.append("\n" + cross_run)

    related = await _related_prior_clips_section(run, store)
    if related.strip():
        extra_parts.append("\n" + related)

    lessons = await _lessons_section(run, store)
    if lessons.strip():
        extra_parts.append("\n" + lessons)

    extra_parts.append("\n")
    path.write_text(body + "".join(extra_parts), encoding="utf-8")
    return path


async def render_run_report_from_dir(
    run_dir: Path, store: VideoClippingStore | None = None
) -> Path:
    """Convenience wrapper — load run.json, then render."""
    from video_clipping.plan import RUN_FILENAME, load_run

    return await render_run_report_rich(load_run(run_dir / RUN_FILENAME), store=store)
