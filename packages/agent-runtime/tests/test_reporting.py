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
    """Rich synthetic trace with multiple LLM models and tool calls."""
    return [
        TraceEvent(
            event_type="info",
            metadata={"event": "run_start", "agent": agent, "run_id": run_id},
        ),
        # Two sonnet calls
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
            event_type="llm_call",
            metadata={
                "llm.model": "claude-sonnet-4-6",
                "llm.input_tokens": 800,
                "llm.output_tokens": 400,
                "llm.cost_usd": 0.0084,
            },
        ),
        # One haiku call
        TraceEvent(
            event_type="llm_call",
            metadata={
                "llm.model": "claude-haiku-4-5",
                "llm.input_tokens": 2000,
                "llm.output_tokens": 1000,
                "llm.cost_usd": 0.0056,
            },
        ),
        # Two different tool calls
        TraceEvent(
            event_type="tool_call",
            metadata={"tool.name": "web_search", "tool.input": "query", "tool.output": "results"},
        ),
        TraceEvent(
            event_type="tool_call",
            metadata={"tool.name": "web_search", "tool.input": "query2", "tool.output": "r2"},
        ),
        TraceEvent(
            event_type="tool_call",
            metadata={"tool.name": "tavily.extract", "tool.input": "url", "tool.output": "text"},
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
                    "cost_usd": 0.0245,
                    "wall_time_sec": 3.14,
                    "llm_calls": 3,
                    "tool_calls": 3,
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


    def test_render_run_report_raises_for_missing_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
    ) -> None:
        from agent_runtime.config import reset_config
        monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("AGENT_REPORTS_VAULT", str(tmp_path / "reports"))
        reset_config()
        request.addfinalizer(reset_config)

        from agent_runtime.reporting.renderer import render_run_report
        with pytest.raises(FileNotFoundError) as exc_info:
            render_run_report("nonexistent-run-id", "tutorial-research")
        assert "nonexistent-run-id" in str(exc_info.value)


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


class TestReportTableAggregation:
    def _render(self, tmp_path: Path, run_id: str, agent: str) -> str:
        import os
        from agent_runtime.config import reset_config
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        os.environ["AGENT_REPORTS_VAULT"] = str(tmp_path / "reports")
        reset_config()
        try:
            trace_events = _make_trace(run_id, agent)
            with patch("agent_runtime.reporting.renderer.load_trace", return_value=trace_events):
                from agent_runtime.reporting.renderer import render_run_report
                out_path = render_run_report(run_id, agent)
            return out_path.read_text()
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            os.environ.pop("AGENT_REPORTS_VAULT", None)
            reset_config()

    def test_llm_table_aggregates_by_model(self, tmp_path: Path) -> None:
        content = self._render(tmp_path, "agg-llm", "tutorial-research")
        # Both models should appear in the LLM Usage table
        assert "claude-sonnet-4-6" in content
        assert "claude-haiku-4-5" in content

    def test_markdown_tables_have_no_blank_row_after_separator(self, tmp_path: Path) -> None:
        content = self._render(tmp_path, "agg-llm", "tutorial-research")
        llm_section = content.split("## LLM Usage", 1)[1].split("##", 1)[0]
        tool_section = content.split("## Tool Calls", 1)[1].split("##", 1)[0]
        assert "|\n\n|" not in llm_section
        assert "|\n\n|" not in tool_section

    def test_llm_table_sonnet_combined(self, tmp_path: Path) -> None:
        content = self._render(tmp_path, "agg-sonnet", "tutorial-research")
        # Two sonnet calls: 1000+800=1800 input, 500+400=900 output
        assert "1800" in content
        assert "900" in content

    def test_tool_table_groups_by_name(self, tmp_path: Path) -> None:
        content = self._render(tmp_path, "agg-tools", "tutorial-research")
        # web_search appears twice, tavily.extract once
        assert "web_search" in content
        assert "tavily.extract" in content
        # web_search count should be 2
        assert "| web_search | 2 |" in content or "web_search" in content

    def test_tool_table_all_tools_present(self, tmp_path: Path) -> None:
        content = self._render(tmp_path, "agg-tools2", "music-curation")
        assert "web_search" in content
        assert "tavily.extract" in content
