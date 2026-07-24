"""Outbox relay: polls `outbox_events` for unpublished rows and publishes
them to Redpanda. Runs as its own long-lived process (a separate
docker-compose service reusing this image with a different command) so a
publish failure or restart never blocks saga processing.

See docs/adrs/0003-transactional-outbox.md.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from opentelemetry import trace
from prometheus_client import start_http_server
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.models import OutboxEvent
from event_contracts import (
    EventEnvelope,
    build_producer,
    configure_logging,
    configure_tracing,
    context_from_traceparent,
    correlation_id_var,
    publish_envelope,
)
from event_contracts.kafka import KafkaPublishError

logger = logging.getLogger("fulfillment_orchestrator.outbox_relay")
_tracer = trace.get_tracer(__name__)

POLL_INTERVAL_SECONDS = 0.25
BACKOFF_BASE_SECONDS = 1
MAX_BACKOFF_SECONDS = 60
BATCH_SIZE = 100


def _due_rows(db: Session, now: datetime) -> list[OutboxEvent]:
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
        )
        .order_by(OutboxEvent.created_at)
        .limit(BATCH_SIZE)
    )
    return list(db.scalars(stmt))


def run_relay_once(session_factory: sessionmaker, producer) -> int:
    """Publish one batch of due outbox rows. Returns the count published.

    Each row's `correlation_id_var` is set (structured logs) and its publish
    happens inside a tracing span that resumes the trace captured at
    `stage_event` time — see `event_contracts.tracing_setup` — so the outbox
    relay's own hop is visible in Jaeger between "request handled" and
    "consumer processed"."""
    published = 0
    with session_factory() as db:
        now = datetime.now(UTC)
        for row in _due_rows(db, now):
            envelope = EventEnvelope.model_validate(row.payload)
            correlation_token = correlation_id_var.set(envelope.correlation_id)
            try:
                span_context = context_from_traceparent(envelope.trace_context.traceparent)
                with _tracer.start_as_current_span(
                    f"publish {envelope.event_type}", context=span_context
                ) as span:
                    span.set_attribute("correlation_id", envelope.correlation_id)
                    span.set_attribute("event_id", envelope.event_id)
                    try:
                        publish_envelope(
                            producer,
                            topic=row.event_type,
                            key=str(row.aggregate_id),
                            envelope=envelope,
                        )
                    except KafkaPublishError as exc:
                        span.record_exception(exc)
                        row.attempt_count += 1
                        backoff = min(
                            BACKOFF_BASE_SECONDS * (2**row.attempt_count), MAX_BACKOFF_SECONDS
                        )
                        row.next_attempt_at = now + timedelta(seconds=backoff)
                        db.commit()
                        logger.warning(
                            "publish failed for outbox row %s (attempt %s, retrying in %ss)",
                            row.id,
                            row.attempt_count,
                            backoff,
                            exc_info=True,
                        )
                        continue
            finally:
                correlation_id_var.reset(correlation_token)
            row.published_at = now
            row.attempt_count += 1
            db.commit()
            published += 1
    return published


def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name)
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    start_http_server(settings.metrics_port)
    producer = build_producer(settings.kafka_bootstrap_servers)
    session_factory = sessionmaker(bind=get_engine(), future=True)
    logger.info("outbox relay started for %s", settings.service_name)
    while True:
        try:
            count = run_relay_once(session_factory, producer)
            if count:
                logger.info("published %s outbox event(s)", count)
        except Exception:
            logger.exception("outbox relay iteration failed")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
