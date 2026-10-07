from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from visual_generation.constants import DEFAULT_PER_RUN_MINUTES
from visual_generation.gpu_tracker import GpuLedger, SessionMeter, estimate_per_run_cost


# ── estimate_per_run_cost ────────────────────────────────────────────────────


def test_estimate_cold_start_uses_default() -> None:
    usd, source = estimate_per_run_cost([], rate=3.0)
    assert source == "default"
    assert usd == pytest.approx(DEFAULT_PER_RUN_MINUTES / 60.0 * 3.0)


def test_estimate_learned_from_prior_costs() -> None:
    usd, source = estimate_per_run_cost([0.10, 0.20, 0.30], rate=3.0)
    assert source == "learned"
    assert usd == pytest.approx(0.20)  # mean


def test_estimate_ignores_zero_costs() -> None:
    usd, source = estimate_per_run_cost([0.0, 0.0], rate=2.0)
    assert source == "default"  # no non-zero history → cold-start default


# ── GpuLedger ────────────────────────────────────────────────────────────────


def test_ledger_starts_empty() -> None:
    ledger = GpuLedger()
    assert ledger.cumulative() == 0.0
    assert ledger.declared_budget() is None
    assert ledger.remaining() is None


def test_ledger_records_and_accumulates() -> None:
    ledger = GpuLedger()
    ledger.record_session(0.50)
    ledger.record_session(0.25)
    assert ledger.cumulative() == pytest.approx(0.75)


def test_ledger_remaining_against_declared_budget() -> None:
    ledger = GpuLedger()
    ledger.set_budget(2.0)
    ledger.record_session(0.5)
    assert ledger.remaining() == pytest.approx(1.5)


# ── SessionMeter (injected clock — deterministic, no sleeping) ───────────────


def test_session_meter_uptime_and_costs() -> None:
    clock = itertools.count(0, 60).__next__  # 0, 60, 120, ... seconds
    meter = SessionMeter(rate_usd_per_hr=3.0, clock=clock)
    meter.begin()       # start = 0
    # one "run" of 60s
    _ = meter.per_run_cost(60)
    meter.add_run(60)
    meter.end()         # end = 60
    assert meter.uptime_seconds() == pytest.approx(60)
    # 60s at $3/hr = $0.05
    assert meter.session_cost() == pytest.approx(0.05)
    assert meter.per_run_cost(120) == pytest.approx(0.10)


# ── pod uptime: its own entry type, apart from inference estimates ───────────


def test_pod_uptime_is_recorded_apart_from_inference_estimates(tmp_path: Path) -> None:
    ledger = GpuLedger(tmp_path / "ledger.json")
    ledger.record_session(0.10)                                   # an inference estimate

    ledger.open_pod_uptime("pod-1", 0.60, session_id="s1", started_at="2026-10-07T17:00:00+00:00")
    assert ledger.open_pod_entry()["pod_id"] == "pod-1"
    closed = ledger.close_pod_uptime("pod-1", ended_at="2026-10-07T17:30:00+00:00")

    assert closed is not None and closed["type"] == "pod_uptime"
    assert closed["seconds"] == 1800 and closed["cost_usd"] == pytest.approx(0.30)
    assert ledger.open_pod_entry() is None
    assert ledger.pod_uptime_total() == pytest.approx(0.30)
    assert ledger.cumulative() == pytest.approx(0.10)             # uptime never folds into the estimates


def test_pod_uptime_marks_what_was_not_observed(tmp_path: Path) -> None:
    ledger = GpuLedger(tmp_path / "ledger.json")
    ledger.open_pod_uptime("pod-2", 0.69, start_observed=False)
    closed = ledger.close_pod_uptime("pod-2", end_observed=False)
    assert closed is not None and closed["start_observed"] is False and closed["end_observed"] is False
    assert ledger.close_pod_uptime("pod-2") is None                # nothing left open


def test_a_ledger_written_before_pod_entries_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    path.write_text('{"cumulative_usd": 1.5, "declared_budget_usd": 10.0}', encoding="utf-8")
    ledger = GpuLedger(path)
    assert ledger.cumulative() == 1.5 and ledger.entries() == [] and ledger.pod_uptime_total() == 0.0
    ledger.open_pod_uptime("pod-3", 0.69)
    assert ledger.cumulative() == 1.5 and ledger.remaining() == 8.5
