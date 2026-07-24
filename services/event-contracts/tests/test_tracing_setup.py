from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from event_contracts.tracing_setup import context_from_traceparent, current_traceparent

# OpenTelemetry's global tracer provider can only be set once per process
# (later calls are ignored with a warning) — so this module configures it a
# single time at import and every test reuses the same tracer/exporter,
# rather than each test trying to install its own provider.
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider(resource=Resource.create({"service.name": "test"}))
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)
_TRACER = trace.get_tracer("test")


def test_current_traceparent_is_none_with_no_active_span():
    # Outside any `start_as_current_span` block, the current span is the
    # module-level INVALID span — nothing valid to inject into the carrier.
    assert current_traceparent() is None


def test_current_traceparent_captures_the_active_span():
    with _TRACER.start_as_current_span("root") as span:
        traceparent = current_traceparent()
        expected_trace_id = format(span.get_span_context().trace_id, "032x")

    assert traceparent is not None
    assert expected_trace_id in traceparent


def test_context_from_traceparent_round_trips_the_same_trace_id():
    with _TRACER.start_as_current_span("root") as root_span:
        traceparent = current_traceparent()
        root_trace_id = root_span.get_span_context().trace_id

    ctx = context_from_traceparent(traceparent)
    with _TRACER.start_as_current_span("child", context=ctx) as child_span:
        child_trace_id = child_span.get_span_context().trace_id

    assert child_trace_id == root_trace_id


def test_context_from_traceparent_with_none_falls_back_to_current_context():
    ctx = context_from_traceparent(None)
    assert ctx is not None
