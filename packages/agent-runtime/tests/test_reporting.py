from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from agent_runtime.models import BudgetConsumption, BudgetEnvelope, TraceEvent
from agent_runtime.reporting.notifications import notify, notify_budget_threshold, notify_run_complete


@pytest.fixture(autouse=True)
def _env(fake_env: None) -> None:
    pass


def _make_trace(run_id: str, agent: str) -> list[TraceEvent]:
    return [
        TraceEvent(
            event_type="info",
            metadata={"event": "run_start", "agent": agent, "run_id": run_id},
        ),
        TraceEvent(
            event_type="llm_call",
            metadata={
                "llm.model": "claude-sonnet-4-6",
                "llm.input_tokens": 1000,
                "llm.output_tokens": 500,
                "llm.cost_usd": 0.0105,
            },
        ),
        TraceEvent(
            event_type="tool_call",
            metadata={"tool.name": "web_search", "tool.input": "query", "tool.output": "results"},
        ),
        TraceEvent(
            event_type="info",
            metadata={
                "event": "run_end",
                "agent": agent,
                "run_id": run_id,
                "status": "completed",
                "envelope": {"session_id": "sess-001"},
                "summary": {
                    "cost_usd": 0.0105,
                    "wall_time_sec": 3.14,
                    "llm_calls": 1,
                    "tool_calls": 1,
                    "delegations": 0,
                    "items_processed": 0,
                },
            },
        ),
    ]


class TestRenderRunReport:
    def test_report_written_to_expected_path(self, tmp_path: Path) -> None:
        from agent_runtime.config import reset_config
        import os
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        os.environ["AGENT_REPORTS_VAULT"] = str(tmp_path / "reports")
        reset_config()

        try:
            run_id = "test-run-render"
            agent = "tutorial-research"
            trace_events = _make_trace(run_id, agent)

            with patch("agent_runtime.reporting.renderer.load_trace", return_value=trace_events):
                from agent_runtime.reporting.renderer import render_run_report
                out_path = render_run_report(run_id, agent)

            assert out_path.exists()
            assert out_path.parent.name == agent
            assert out_path.suffix == ".md"
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            os.environ.pop("AGENT_REPORTS_VAULT", None)
            reset_config()

    def test_frontmatter_is_valid_yaml(self, tmp_path: Path) -> None:
        from agent_runtime.config import reset_config
        import os
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        os.environ["AGENT_REPORTS_VAULT"] = str(tmp_path / "reports")
        reset_config()

        try:
            run_id = "test-run-yaml"
            agent = "tutorial-research"
            trace_events = _make_trace(run_id, agent)

            with patch("agent_runtime.reporting.renderer.load_trace", return_value=trace_events):
                from agent_runtime.reporting.renderer import render_run_report
                out_path = render_run_report(run_id, agent)

            content = out_path.read_text()
            # Extract YAML frontmatter between first --- delimiters
            parts = content.split("---")
            assert len(parts) >= 3, "Expected frontmatter delimiters"
            fm = yaml.safe_load(parts[1])
            assert fm["agent"] == agent
            assert fm["run_id"] == run_id
            assert "cost_usd" in fm
            assert "status" in fm
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            os.environ.pop("AGENT_REPORTS_VAULT", None)
            reset_config()

    def test_report_contains_expected_sections(self, tmp_path: Path) -> None:
        from agent_runtime.config import reset_config
        import os
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        os.environ["AGENT_REPORTS_VAULT"] = str(tmp_path / "reports")
        reset_config()

        try:
            run_id = "test-run-sections"
            agent = "music-curation"
            trace_events = _make_trace(run_id, agent)

            with patch("agent_runtime.reporting.renderer.load_trace", return_value=trace_events):
                from agent_runtime.reporting.renderer import render_run_report
                out_path = render_run_report(run_id, agent)

            content = out_path.read_text()
            for section in (
                "## Summary", "## Delegation Tree", "## Tool Calls",
                "## LLM Usage", "## Memory Operations",
                "## Notable Events", "## Outputs",
            ):
                assert section in content, f"Missing section: {section}"
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            os.environ.pop("AGENT_REPORTS_VAULT", None)
            reset_config()


class TestNotifications:
    def test_notify_calls_osascript_on_darwin(self) -> None:
        with patch("subprocess.run") as mock_run, \
             patch.object(sys, "platform", "darwin"):
            notify("Test Title", "Test message")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "osascript" in args
            assert "Test Title" in " ".join(args)

    def test_notify_noop_on_non_darwin(self) -> None:
        with patch("subprocess.run") as mock_run, \
             patch.object(sys, "platform", "linux"):
            notify("Title", "Message")
            mock_run.assert_not_called()

    def test_notify_escapes_quotes(self) -> None:
        with patch("subprocess.run") as mock_run, \
             patch.object(sys, "platform", "darwin"):
            notify('Title with "quotes"', 'Message with "quotes"')
            args = mock_run.call_args[0][0]
            script = args[-1]
            # The raw quote chars should be escaped
            assert '\\"' in script

    def test_notify_budget_threshold_fires_above_75pct(self) -> None:
        with patch("agent_runtime.reporting.notifications.notify") as mock_notify:
            envelope = BudgetEnvelope(max_cost_usd=1.0)
            consumption = BudgetConsumption(cost_usd=0.80)
            notify_budget_threshold("my-agent", consumption, envelope)
            mock_notify.assert_called_once()

    def test_notify_budget_threshold_silent_below_75pct(self) -> None:
        with patch("agent_runtime.reporting.notifications.notify") as mock_notify:
            envelope = BudgetEnvelope(max_cost_usd=1.0)
            consumption = BudgetConsumption(cost_usd=0.50)
            notify_budget_threshold("my-agent", consumption, envelope)
            mock_notify.assert_not_called()

    def test_notify_run_complete(self) -> None:
        with patch("agent_runtime.reporting.notifications.notify") as mock_notify:
            notify_run_complete("my-agent", "run-123", "completed", 0.042)
            mock_notify.assert_called_once()
            args = mock_notify.call_args[0]
            assert "completed" in args[0]
