from __future__ import annotations

import itertools

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
