from __future__ import annotations

import asyncio
import functools
import json
from contextlib import contextmanager
from typing import Any, Callable, Generator

from opentelemetry import trace
from opentelemetry.trace import SpanKind


def _safe_attr(value: Any, max_len: int = 200) -> str:
    try:
        s = json.dumps(value)
    except (TypeError, ValueError):
        s = str(value)
    return s[:max_len] if len(s) > max_len else s


def _span_kind(kind: str) -> SpanKind:
    return {
        "internal": SpanKind.INTERNAL,
        "client": SpanKind.CLIENT,
        "server": SpanKind.SERVER,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
    }.get(kind, SpanKind.INTERNAL)


def traced(
    name: str | None = None,
    kind: str = "internal",
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__name__

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span(span_name, kind=_span_kind(kind)) as s:
                    _record_call_attrs(s, args, kwargs)
                    try:
                        result = await fn(*args, **kwargs)
                        s.set_attribute("return.value", _safe_attr(result))
                        return result
                    except Exception as exc:
                        s.record_exception(exc)
                        s.set_status(trace.StatusCode.ERROR, str(exc))
                        raise
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span(span_name, kind=_span_kind(kind)) as s:
                    _record_call_attrs(s, args, kwargs)
                    try:
                        result = fn(*args, **kwargs)
                        s.set_attribute("return.value", _safe_attr(result))
                        return result
                    except Exception as exc:
                        s.record_exception(exc)
                        s.set_status(trace.StatusCode.ERROR, str(exc))
                        raise
            return sync_wrapper

    return decorator


def _record_call_attrs(s: trace.Span, args: tuple, kwargs: dict) -> None:
    for i, arg in enumerate(args):
        s.set_attribute(f"arg.{i}", _safe_attr(arg))
    for key, val in kwargs.items():
        s.set_attribute(f"kwarg.{key}", _safe_attr(val))


@contextmanager
def span(name: str, kind: str = "internal") -> Generator[trace.Span, None, None]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name, kind=_span_kind(kind)) as s:
        yield s


def record_llm_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    s = trace.get_current_span()
    s.set_attribute("llm.model", model)
    s.set_attribute("llm.input_tokens", input_tokens)
    s.set_attribute("llm.output_tokens", output_tokens)
    s.set_attribute("llm.cost_usd", cost_usd)


def record_tool_call(tool_name: str, input_summary: str, output_summary: str) -> None:
    s = trace.get_current_span()
    s.set_attribute("tool.name", tool_name)
    s.set_attribute("tool.input", input_summary[:200])
    s.set_attribute("tool.output", output_summary[:200])


def record_delegation(target_agent: str, status: str, cost_usd: float) -> None:
    s = trace.get_current_span()
    s.set_attribute("delegation.target", target_agent)
    s.set_attribute("delegation.status", status)
    s.set_attribute("delegation.cost_usd", cost_usd)


def record_memory_query(collection: str, query: str, results_count: int) -> None:
    s = trace.get_current_span()
    s.set_attribute("memory.operation", "query")
    s.set_attribute("memory.collection", collection)
    s.set_attribute("memory.query", query[:200])
    s.set_attribute("memory.results_count", results_count)


def record_memory_write(collection: str, count: int) -> None:
    s = trace.get_current_span()
    s.set_attribute("memory.operation", "write")
    s.set_attribute("memory.collection", collection)
    s.set_attribute("memory.write_count", count)
