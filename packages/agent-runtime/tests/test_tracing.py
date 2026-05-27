from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_runtime.models import TraceEvent
from agent_runtime.tracing.decorators import (
    record_delegation,
    record_llm_call,
    record_memory_query,
    record_memory_write,
    record_tool_call,
    span,
    traced,
)
from agent_runtime.tracing.persistence import TracePersister, load_trace


@pytest.fixture
def in_memory_tracer():
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.util._once import Once

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Reset OTel's global singleton so set_tracer_provider works in each test
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    trace._TRACER_PROVIDER = None
    trace.set_tracer_provider(provider)

    yield exporter

    exporter.clear()
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    trace._TRACER_PROVIDER = None


class TestTracedDecorator:
    def test_sync_function_traced(self, in_memory_tracer: InMemorySpanExporter) -> None:
        @traced()
        def add(a: int, b: int) -> int:
            return a + b

        result = add(1, 2)
        assert result == 3
        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "add"

    def test_async_function_traced(self, in_memory_tracer: InMemorySpanExporter) -> None:
        @traced(name="my_async_fn")
        async def fetch(url: str) -> str:
            return f"fetched:{url}"

        result = asyncio.run(fetch("http://example.com"))
        assert result == "fetched:http://example.com"
        spans = in_memory_tracer.get_finished_spans()
        assert any(s.name == "my_async_fn" for s in spans)

    def test_exception_recorded(self, in_memory_tracer: InMemorySpanExporter) -> None:
        @traced()
        def boom() -> None:
            raise ValueError("oops")

        with pytest.raises(ValueError):
            boom()

        spans = in_memory_tracer.get_finished_spans()
        assert spans[0].status.status_code == trace.StatusCode.ERROR
        events = spans[0].events
        assert any(e.name == "exception" for e in events)

    def test_async_exception_recorded(self, in_memory_tracer: InMemorySpanExporter) -> None:
        @traced()
        async def async_boom() -> None:
            raise RuntimeError("async oops")

        with pytest.raises(RuntimeError):
            asyncio.run(async_boom())

        spans = in_memory_tracer.get_finished_spans()
        assert spans[0].status.status_code == trace.StatusCode.ERROR

    def test_custom_name(self, in_memory_tracer: InMemorySpanExporter) -> None:
        @traced(name="custom.operation")
        def fn() -> None:
            pass

        fn()
        spans = in_memory_tracer.get_finished_spans()
        assert spans[0].name == "custom.operation"


class TestSpanContextManager:
    def test_span_yields_span_object(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test.span") as s:
            s.set_attribute("key", "value")

        finished = in_memory_tracer.get_finished_spans()
        assert finished[0].name == "test.span"
        assert finished[0].attributes.get("key") == "value"


class TestRecordHelpers:
    def test_record_llm_call(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test"):
            record_llm_call("claude-sonnet-4-6", 100, 200, 0.0045)

        s = in_memory_tracer.get_finished_spans()[0]
        assert s.attributes["llm.model"] == "claude-sonnet-4-6"
        assert s.attributes["llm.input_tokens"] == 100
        assert s.attributes["llm.cost_usd"] == pytest.approx(0.0045)

    def test_record_tool_call(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test"):
            record_tool_call("web_search", "query: python", "10 results")

        s = in_memory_tracer.get_finished_spans()[0]
        assert s.attributes["tool.name"] == "web_search"

    def test_record_delegation(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test"):
            record_delegation("music-curation", "completed", 0.10)

        s = in_memory_tracer.get_finished_spans()[0]
        assert s.attributes["delegation.target"] == "music-curation"
        assert s.attributes["delegation.status"] == "completed"

    def test_record_memory_query(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test"):
            record_memory_query("tutorials", "python async", 5)

        s = in_memory_tracer.get_finished_spans()[0]
        assert s.attributes["memory.operation"] == "query"
        assert s.attributes["memory.results_count"] == 5

    def test_record_memory_write(self, in_memory_tracer: InMemorySpanExporter) -> None:
        with span("test"):
            record_memory_write("tutorials", 12)

        s = in_memory_tracer.get_finished_spans()[0]
        assert s.attributes["memory.operation"] == "write"
        assert s.attributes["memory.write_count"] == 12


class TestTracePersister:
    def test_writes_and_reads_events(self, fake_env: None, tmp_path: Path) -> None:
        from agent_runtime.config import get_config, reset_config
        reset_config()
        import os
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()

        try:
            run_id = "test-run-001"
            event = TraceEvent(event_type="info", metadata={"msg": "hello"})

            with TracePersister(agent="test-agent", run_id=run_id) as p:
                p.record(event)

            events = load_trace(run_id, "test-agent")
            assert len(events) == 1
            assert events[0].event_type == "info"
            assert events[0].metadata["msg"] == "hello"
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_concurrent_writes(self, fake_env: None, tmp_path: Path) -> None:
        import os
        from agent_runtime.config import reset_config
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()

        try:
            run_id = "concurrent-run"
            errors: list[Exception] = []

            def write_events(n: int) -> None:
                try:
                    with TracePersister(agent="test-agent", run_id=run_id) as p:
                        for i in range(n):
                            p.record(TraceEvent(event_type="info", metadata={"i": i}))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=write_events, args=(5,)) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            events = load_trace(run_id, "test-agent")
            assert len(events) == 20
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_load_trace_empty_when_not_found(self, fake_env: None) -> None:
        events = load_trace("nonexistent-run", "test-agent")
        assert events == []

    def test_persister_writes_to_configured_path(
        self, fake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
    ) -> None:
        from agent_runtime.config import reset_config
        monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))
        reset_config()
        request.addfinalizer(reset_config)

        run_id = "path-check-run"
        with TracePersister(agent="test-agent", run_id=run_id) as p:
            p.record(TraceEvent(event_type="info", metadata={"check": True}))

        traces = list((tmp_path / "data" / "runs").rglob("trace.jsonl"))
        assert len(traces) == 1
        assert '"check"' in traces[0].read_text()


class TestInitTracing:
    def test_idempotent(self, fake_env: None) -> None:
        from agent_runtime.tracing.setup import _initialized, init_tracing
        _initialized.discard("test-service")

        t1 = init_tracing("test-service")
        t2 = init_tracing("test-service")

        assert "test-service" in _initialized
        # Both calls succeed without error
        assert t1 is not None
        assert t2 is not None
        _initialized.discard("test-service")


class TestTracePersisterContextVar:
    def test_none_when_no_persister_active(self) -> None:
        from agent_runtime.tracing.persistence import get_current_persister
        assert get_current_persister() is None

    def test_contextvar_set_on_enter(self, fake_env: None, tmp_path: Path) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import get_current_persister
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            assert get_current_persister() is None
            with TracePersister(agent="cv-agent", run_id="cv-run-001") as p:
                assert get_current_persister() is p
            assert get_current_persister() is None
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_contextvar_restored_on_exit(self, fake_env: None, tmp_path: Path) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import get_current_persister
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            with TracePersister(agent="cv-agent", run_id="cv-run-002") as outer:
                with TracePersister(agent="cv-agent", run_id="cv-run-003") as inner:
                    assert get_current_persister() is inner
                # inner has exited — outer should be restored
                assert get_current_persister() is outer
            assert get_current_persister() is None
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_record_llm_emits_to_persister(
        self, fake_env: None, tmp_path: Path, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        import os
        from agent_runtime.config import reset_config
        from agent_runtime.tracing.persistence import get_current_persister
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            run_id = "emit-test-llm"
            with TracePersister(agent="emit-agent", run_id=run_id) as p:
                with span("agent.run"):
                    record_llm_call("claude-sonnet-4-6", 500, 250, 0.005)

            events = load_trace(run_id, "emit-agent")
            llm_events = [e for e in events if e.event_type == "llm_call"]
            assert len(llm_events) == 1
            assert llm_events[0].metadata["llm.model"] == "claude-sonnet-4-6"
            assert llm_events[0].metadata["llm.input_tokens"] == 500
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_record_tool_emits_to_persister(
        self, fake_env: None, tmp_path: Path, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        import os
        from agent_runtime.config import reset_config
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            run_id = "emit-test-tool"
            with TracePersister(agent="emit-agent", run_id=run_id) as p:
                with span("agent.run"):
                    record_tool_call("web_search", "python async", "5 results")

            events = load_trace(run_id, "emit-agent")
            tool_events = [e for e in events if e.event_type == "tool_call"]
            assert len(tool_events) == 1
            assert tool_events[0].metadata["tool.name"] == "web_search"
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_record_memory_query_emits_to_persister(
        self, fake_env: None, tmp_path: Path, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        import os
        from agent_runtime.config import reset_config
        os.environ["AGENT_DATA_DIR"] = str(tmp_path / "data")
        reset_config()
        try:
            run_id = "emit-test-mq"
            with TracePersister(agent="emit-agent", run_id=run_id) as p:
                with span("agent.run"):
                    record_memory_query("tutorials", "async python", 3)

            events = load_trace(run_id, "emit-agent")
            mq_events = [e for e in events if e.event_type == "memory_query"]
            assert len(mq_events) == 1
            assert mq_events[0].metadata["memory.collection"] == "tutorials"
            assert mq_events[0].metadata["memory.results_count"] == 3
        finally:
            os.environ.pop("AGENT_DATA_DIR", None)
            reset_config()

    def test_no_emission_without_persister(
        self, fake_env: None, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        # Should not raise even when no persister is active
        with span("standalone"):
            record_llm_call("claude-haiku-4-5", 100, 50, 0.0001)
            record_tool_call("search", "q", "r")
        # No error = pass


class TestToolCallBridge:
    def test_record_tool_call_increments_tracker(
        self,
        fake_env: None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
    ) -> None:
        import asyncio
        from agent_runtime.config import reset_config
        from agent_runtime import BudgetEnvelope
        from agent_runtime.budget import BudgetTracker

        monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path / "data"))
        reset_config()
        request.addfinalizer(reset_config)

        async def _run() -> int:
            async with BudgetTracker(BudgetEnvelope(), "test-agent") as tracker:
                record_tool_call("voyage.embed", "texts", "vectors")
                return tracker._consumption.tool_calls

        count = asyncio.run(_run())
        assert count == 1
