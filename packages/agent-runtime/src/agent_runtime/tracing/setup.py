from __future__ import annotations

import importlib.metadata

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from ulid import ULID

_initialized: set[str] = set()
_instance_id = str(ULID())

try:
    _version = importlib.metadata.version("agent-runtime")
except importlib.metadata.PackageNotFoundError:
    _version = "0.0.1"


def init_tracing(service_name: str) -> trace.Tracer:
    if service_name in _initialized:
        return trace.get_tracer(service_name)

    from agent_runtime.config import get_config
    config = get_config()

    resource = Resource.create({
        "service.name": service_name,
        "service.version": _version,
        "service.instance.id": _instance_id,
    })

    exporter = OTLPSpanExporter(endpoint=f"{config.otel_endpoint}/v1/traces")
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _initialized.add(service_name)
    return trace.get_tracer(service_name)
