#!/usr/bin/env python3
"""Summarize agent-stack run costs from the persisted trace files.

Each agent run (one conversational turn) writes a trace at:
    $AGENT_DATA_DIR/runs/<YYYY-MM-DD>/<agent>/<run_id>/trace.jsonl
containing one `llm_call` event per LLM call (model + input/output tokens + cost)
and a `run_end` summary (status + consumption). This reads them and reports
per-turn and aggregate cost. Standard library only — no deps.

NOTE ON GRANULARITY: one trace = one run_id = one conversational *turn*
(run_turn creates a fresh BudgetTracker per turn). Traces don't record the
chat thread id, so this reports per-turn, not per-chat-session. To roll up by
session you'd add thread_id to the run_end metadata in agent.py first.

Usage:
    python3 agent_costs.py                         # orchestrator, all dates, per-turn table
    python3 agent_costs.py --agent orchestrator
    python3 agent_costs.py --since 2026-06-01
    python3 agent_costs.py --by-day                # daily rollup instead of per-turn
    python3 agent_costs.py --all-agents            # every agent, grouped
    python3 agent_costs.py --data-dir ~/agent-data # override $AGENT_DATA_DIR
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


def resolve_runs_dir(data_dir: str | None) -> Path:
    base = Path(data_dir).expanduser() if data_dir else Path(
        os.environ.get("AGENT_DATA_DIR", "~/agent-data")
    ).expanduser()
    return base / "runs"


def parse_run(trace_path: Path) -> dict | None:
    """Summarize one run (turn) trace. Returns None if empty/unreadable."""
    rec = {
        "run_id": trace_path.parent.name,
        "agent": trace_path.parent.parent.name,
        "date": trace_path.parent.parent.parent.name,
        "ts": None,
        "session_id": None,
        "status": "?",
        "model": "",
        "llm_calls": 0,
        "tool_calls": 0,
        "in_tok": 0,
        "out_tok": 0,
        "cost_events": 0.0,   # summed from llm_call events
        "cost_summary": None,  # authoritative, from run_end
    }
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    saw_any = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        saw_any = True
        md = ev.get("metadata", {}) or {}
        if rec["ts"] is None and ev.get("timestamp"):
            rec["ts"] = ev["timestamp"]
        et = ev.get("event_type")
        if et == "llm_call":
            rec["llm_calls"] += 1
            rec["in_tok"] += int(md.get("llm.input_tokens", 0) or 0)
            rec["out_tok"] += int(md.get("llm.output_tokens", 0) or 0)
            rec["cost_events"] += float(md.get("llm.cost_usd", 0.0) or 0.0)
            if md.get("llm.model"):
                rec["model"] = md["llm.model"]
        elif et == "tool_call":
            rec["tool_calls"] += 1
        elif et == "info" and md.get("event") == "run_end":
            rec["status"] = md.get("status", "?")
            env = md.get("envelope") or {}
            if env.get("session_id"):
                rec["session_id"] = env["session_id"]
            summ = md.get("summary") or {}
            if "cost_usd" in summ:
                rec["cost_summary"] = float(summ["cost_usd"])
            if summ.get("tool_calls") is not None:
                rec["tool_calls"] = int(summ["tool_calls"])
            if summ.get("llm_calls") is not None:
                rec["llm_calls"] = int(summ["llm_calls"])

    if not saw_any:
        return None
    rec["cost"] = rec["cost_summary"] if rec["cost_summary"] is not None else rec["cost_events"]
    return rec


def collect(runs_dir: Path, agent: str | None, since: str | None) -> list[dict]:
    if not runs_dir.exists():
        return []
    runs: list[dict] = []
    for trace in runs_dir.glob("*/*/*/trace.jsonl"):
        rec = parse_run(trace)
        if rec is None:
            continue
        if agent and rec["agent"] != agent:
            continue
        if since and rec["date"] < since:
            continue
        runs.append(rec)
    runs.sort(key=lambda r: (r["ts"] or "", r["run_id"]))
    return runs


def _fmt(n: int) -> str:
    return f"{n:,}"


def print_per_turn(runs: list[dict]) -> None:
    if not runs:
        print("No runs found.")
        return
    hdr = f"{'WHEN':<17}{'STATUS':<10}{'LLM':>4}{'TOOLS':>7}{'IN_TOK':>11}{'OUT_TOK':>10}{'COST':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r in runs:
        when = (r["ts"] or r["date"])[:16].replace("T", " ")
        print(
            f"{when:<17}{r['status']:<10}{r['llm_calls']:>4}{r['tool_calls']:>7}"
            f"{_fmt(r['in_tok']):>11}{_fmt(r['out_tok']):>10}{'$'+format(r['cost'],'.4f'):>10}"
        )
    print("-" * len(hdr))
    _print_totals(runs)


def print_by_day(runs: list[dict]) -> None:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_day[r["date"]].append(r)
    hdr = f"{'DATE':<12}{'TURNS':>6}{'PARTIAL':>9}{'LLM':>6}{'TOOLS':>7}{'IN_TOK':>12}{'OUT_TOK':>11}{'COST':>11}"
    print(hdr)
    print("-" * len(hdr))
    for date in sorted(by_day):
        rs = by_day[date]
        print(
            f"{date:<12}{len(rs):>6}{sum(r['status']=='partial' for r in rs):>9}"
            f"{sum(r['llm_calls'] for r in rs):>6}{sum(r['tool_calls'] for r in rs):>7}"
            f"{_fmt(sum(r['in_tok'] for r in rs)):>12}{_fmt(sum(r['out_tok'] for r in rs)):>11}"
            f"{'$'+format(sum(r['cost'] for r in rs),'.4f'):>11}"
        )
    print("-" * len(hdr))
    _print_totals(runs)


def print_by_session(runs: list[dict]) -> None:
    by_sess: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_sess[r["session_id"] or "(unknown)"].append(r)
    hdr = f"{'SESSION':<28}{'TURNS':>6}{'PARTIAL':>9}{'LLM':>6}{'TOOLS':>7}{'IN_TOK':>12}{'OUT_TOK':>11}{'COST':>11}"
    print(hdr)
    print("-" * len(hdr))
    # Sort sessions by their earliest turn.
    for sess in sorted(by_sess, key=lambda s: min(r["ts"] or "" for r in by_sess[s])):
        rs = by_sess[sess]
        print(
            f"{sess[:26]:<28}{len(rs):>6}{sum(r['status']=='partial' for r in rs):>9}"
            f"{sum(r['llm_calls'] for r in rs):>6}{sum(r['tool_calls'] for r in rs):>7}"
            f"{_fmt(sum(r['in_tok'] for r in rs)):>12}{_fmt(sum(r['out_tok'] for r in rs)):>11}"
            f"{'$'+format(sum(r['cost'] for r in rs),'.4f'):>11}"
        )
    print("-" * len(hdr))
    print(f"{len(by_sess)} sessions")
    _print_totals(runs)


def _print_totals(runs: list[dict]) -> None:
    n = len(runs)
    total = sum(r["cost"] for r in runs)
    partials = sum(r["status"] == "partial" for r in runs)
    in_tok = sum(r["in_tok"] for r in runs)
    out_tok = sum(r["out_tok"] for r in runs)
    print(
        f"{n} turns | ${total:.4f} total | ${total/n:.4f}/turn avg | "
        f"{partials} partial ({partials/n*100:.0f}%) | "
        f"in {_fmt(in_tok)} / out {_fmt(out_tok)} tokens"
    )
    # Input dominance: how much of spend is input vs output (Sonnet 3:15 pricing).
    in_cost = in_tok * 3.0 / 1_000_000
    out_cost = out_tok * 15.0 / 1_000_000
    denom = in_cost + out_cost
    if denom > 0:
        print(
            f"  token-cost split (Sonnet pricing): "
            f"input ${in_cost:.4f} ({in_cost/denom*100:.0f}%) / "
            f"output ${out_cost:.4f} ({out_cost/denom*100:.0f}%)"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize agent run costs from trace files.")
    ap.add_argument("--agent", default="orchestrator", help="Agent name (default: orchestrator).")
    ap.add_argument("--all-agents", action="store_true", help="Report every agent, not just one.")
    ap.add_argument("--since", default=None, help="Only runs on/after this date (YYYY-MM-DD).")
    ap.add_argument("--by-day", action="store_true", help="Daily rollup instead of per-turn.")
    ap.add_argument("--by-session", action="store_true", help="Group by chat session (thread) instead of per-turn.")
    ap.add_argument("--data-dir", default=None, help="Override $AGENT_DATA_DIR (default ~/agent-data).")
    args = ap.parse_args()

    runs_dir = resolve_runs_dir(args.data_dir)
    agent = None if args.all_agents else args.agent
    runs = collect(runs_dir, agent, args.since)
    view = print_by_session if args.by_session else print_by_day if args.by_day else print_per_turn

    label = "all agents" if args.all_agents else args.agent
    scope = f" since {args.since}" if args.since else ""
    print(f"\nAgent run costs — {label}{scope}  ({runs_dir})\n")

    if args.all_agents:
        by_agent: dict[str, list[dict]] = defaultdict(list)
        for r in runs:
            by_agent[r["agent"]].append(r)
        for ag in sorted(by_agent):
            print(f"=== {ag} ===")
            view(by_agent[ag])
            print()
    else:
        view(runs)
        print()


if __name__ == "__main__":
    main()
