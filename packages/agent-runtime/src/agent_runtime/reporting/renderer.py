from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from agent_runtime.models import TraceEvent
from agent_runtime.tracing.persistence import load_trace

_env = Environment(
    loader=PackageLoader("agent_runtime", "reporting/templates"),
    autoescape=select_autoescape([]),
)


def _extract_context(events: list[TraceEvent]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    llm_events: list[TraceEvent] = []
    tool_events: list[TraceEvent] = []
    delegation_events: list[TraceEvent] = []
    memory_query_events: list[TraceEvent] = []
    memory_write_events: list[TraceEvent] = []
    error_events: list[TraceEvent] = []

    for event in events:
        if event.event_type == "info" and event.metadata.get("event") == "run_end":
            summary = event.metadata.get("summary", {})
        elif event.event_type == "llm_call":
            llm_events.append(event)
        elif event.event_type == "tool_call":
            tool_events.append(event)
        elif event.event_type == "delegation":
            delegation_events.append(event)
        elif event.event_type == "memory_query":
            memory_query_events.append(event)
        elif event.event_type == "memory_write":
            memory_write_events.append(event)
        elif event.event_type == "error":
            error_events.append(event)

    # Build LLM summary grouped by model
    llm_by_model: dict[str, dict[str, Any]] = {}
    for e in llm_events:
        m = e.metadata
        model = m.get("llm.model", "unknown")
        if model not in llm_by_model:
            llm_by_model[model] = {"model": model, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        llm_by_model[model]["calls"] += 1
        llm_by_model[model]["input_tokens"] += m.get("llm.input_tokens", 0)
        llm_by_model[model]["output_tokens"] += m.get("llm.output_tokens", 0)
        llm_by_model[model]["cost_usd"] += m.get("llm.cost_usd", 0.0)

    # Tool summary
    tool_summary: dict[str, int] = {}
    for e in tool_events:
        name = e.metadata.get("tool.name", "unknown")
        tool_summary[name] = tool_summary.get(name, 0) + 1

    # Collections touched
    collections: set[str] = set()
    for e in memory_query_events + memory_write_events:
        col = e.metadata.get("memory.collection")
        if col:
            collections.add(col)

    return {
        "summary": summary,
        "llm_summary": list(llm_by_model.values()),
        "tool_summary": tool_summary,
        "delegation_events": delegation_events,
        "memory_queries": len(memory_query_events),
        "memory_writes": len(memory_write_events),
        "collections": sorted(collections),
        "notable_events": error_events,
    }


def _derive_title(events: list[TraceEvent], run_id: str) -> str:
    for event in events:
        if event.event_type == "info" and event.metadata.get("event") == "run_start":
            payload = event.metadata.get("request_payload", {})
            for key in ("query", "topic", "title", "subject"):
                if val := payload.get(key):
                    slug = re.sub(r"[^\w\s-]", "", str(val))[:50].strip()
                    return slug
    return run_id[:12]


def render_run_report(
    run_id: str,
    agent_name: str,
    date: str | None = None,
) -> Path:
    from agent_runtime.config import get_config

    config = get_config()
    events = load_trace(run_id, agent_name, date)

    if not events:
        runs_dir = config.agent_data_dir / "runs"
        raise FileNotFoundError(
            f"No trace found for run_id={run_id!r} agent={agent_name!r}. "
            f"Expected trace.jsonl under {runs_dir}/<date>/{agent_name}/{run_id}/"
        )

    ctx = _extract_context(events)
    summary = ctx["summary"]

    title = _derive_title(events, run_id)
    report_date = date or datetime.now(UTC).strftime("%Y-%m-%d")

    session_id = ""
    status = "unknown"
    duration_sec = 0.0
    cost_usd = 0.0

    for event in events:
        if event.event_type == "info" and event.metadata.get("event") == "run_end":
            m = event.metadata
            session_id = m.get("envelope", {}).get("session_id", "")
            status = m.get("status", "unknown")
            s = m.get("summary", {})
            duration_sec = s.get("wall_time_sec", 0.0)
            cost_usd = s.get("cost_usd", 0.0)
            break

    template = _env.get_template("run_report.md.j2")
    content = template.render(
        title=title,
        agent_name=agent_name,
        run_id=run_id,
        session_id=session_id,
        date=report_date,
        duration_sec=duration_sec,
        status=status,
        cost_usd=cost_usd,
        tags=[agent_name, status],
        llm_calls=summary.get("llm_calls", 0),
        tool_calls=summary.get("tool_calls", 0),
        delegations=summary.get("delegations", 0),
        llm_summary=ctx["llm_summary"],
        tool_summary=ctx["tool_summary"],
        delegation_events=ctx["delegation_events"],
        memory_queries=ctx["memory_queries"],
        memory_writes=ctx["memory_writes"],
        collections=ctx["collections"],
        notable_events=ctx["notable_events"],
        outputs=[],
    )

    out_dir = config.agent_reports_vault / agent_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report_date} {title}.md"
    out_path.write_text(content, encoding="utf-8")

    return out_path
