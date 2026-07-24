from event_contracts.envelope import EventEnvelope, TraceContext, new_event_id, utc_now
from event_contracts.event_types import EventType
from event_contracts.kafka import (
    KafkaPublishError,
    KafkaPublishTimeoutError,
    build_consumer,
    build_producer,
    parse_envelope,
    publish_envelope,
    run_consume_loop,
)
from event_contracts.logging_setup import configure_logging, correlation_id_var
from event_contracts.metrics_setup import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    KAFKA_CONSUMER_LAG,
    KAFKA_CONSUMER_RETRY_TOTAL,
    KAFKA_DEAD_LETTER_TOTAL,
    MetricsMiddleware,
    kafka_stats_callback,
    metrics_response,
    register_db_pool_collector,
)
from event_contracts.schemas import SCHEMA_REGISTRY, UnknownSchemaError, validate_event_data
from event_contracts.tracing_setup import (
    configure_tracing,
    context_from_traceparent,
    current_traceparent,
)

__all__ = [
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "KAFKA_CONSUMER_LAG",
    "KAFKA_CONSUMER_RETRY_TOTAL",
    "KAFKA_DEAD_LETTER_TOTAL",
    "SCHEMA_REGISTRY",
    "EventEnvelope",
    "EventType",
    "KafkaPublishError",
    "KafkaPublishTimeoutError",
    "MetricsMiddleware",
    "TraceContext",
    "UnknownSchemaError",
    "build_consumer",
    "build_producer",
    "configure_logging",
    "configure_tracing",
    "context_from_traceparent",
    "correlation_id_var",
    "current_traceparent",
    "kafka_stats_callback",
    "metrics_response",
    "new_event_id",
    "parse_envelope",
    "publish_envelope",
    "register_db_pool_collector",
    "run_consume_loop",
    "utc_now",
    "validate_event_data",
]
