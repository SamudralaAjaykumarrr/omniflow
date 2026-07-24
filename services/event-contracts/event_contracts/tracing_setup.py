"""OpenTelemetry tracing shared by every service and worker.

Trace context crosses the Kafka boundary through the event envelope's own
`trace_context.traceparent` field (W3C Trace Context format): captured at
event-creation time — inside whatever request or message handler calls
`stage_event`, via `current_traceparent()` — and stored as part of the
outbox row's payload. `event_contracts.kafka.run_consume_loop` extracts it
again with `context_from_traceparent()` and starts its consumer span as a
child of that context. That is what lets one order's HTTP request, its
outbox publish, and every saga step a Kafka event triggers land in the same
trace in Jaeger, despite the async gap in between.
"""

from __future__ import annotations

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str, otlp_endpoint: str) -> trace.Tracer:
    """Set the process-wide tracer provider and return a tracer for
    `service_name`. `otlp_endpoint` is the OTel Collector's base HTTP URL
    (e.g. `http://otel-collector:4318`); `/v1/traces` is appended here so
    every caller passes the same bare endpoint."""
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def current_traceparent() -> str | None:
    """Capture the active span's context as a W3C `traceparent` string, to
    be stored on an outgoing event envelope."""
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get("traceparent")


def context_from_traceparent(traceparent: str | None) -> otel_context.Context:
    """Rebuild a `Context` from a stored `traceparent`, or the current
    context if none was recorded (e.g. a root event, or one written before
    tracing existed)."""
    if not traceparent:
        return otel_context.get_current()
    return extract({"traceparent": traceparent})
