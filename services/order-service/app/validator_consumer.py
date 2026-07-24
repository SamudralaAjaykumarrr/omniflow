"""Order Service's own consumer for `order.created`: performs (currently a
placeholder, always-passes) validation and transitions CREATED -> VALIDATED,
emitting `order.validated` per docs/event-catalog.md.

Kept as its own asynchronous step — not inlined into `create_order` — so
order creation stays a fast, synchronous, Kafka-independent API call; the
existing Phase 1 behavior (`POST /orders` returns status `CREATED`
immediately) is unchanged. See DECISIONS.md for why this shape was chosen
over validating inline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from prometheus_client import start_http_server
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.models import Order, OrderStatusHistory, ProcessedEvent
from app.outbox import stage_event
from app.state_machine import OrderStatus
from event_contracts import (
    EventEnvelope,
    EventType,
    build_consumer,
    build_producer,
    configure_logging,
    configure_tracing,
    kafka_stats_callback,
    publish_envelope,
    run_consume_loop,
)

logger = logging.getLogger("order_service.validator_consumer")

CONSUMER_NAME = "order-service-validator"


def _already_processed(db: Session, event_id: str) -> bool:
    return db.get(ProcessedEvent, (CONSUMER_NAME, uuid.UUID(event_id))) is not None


def _mark_processed(db: Session, event_id: str) -> None:
    db.add(ProcessedEvent(consumer_name=CONSUMER_NAME, event_id=uuid.UUID(event_id)))


def process_order_created(session_factory: sessionmaker, envelope: EventEnvelope) -> None:
    if envelope.event_type != EventType.ORDER_CREATED:
        return

    with session_factory() as db:
        if _already_processed(db, envelope.event_id):
            return

        order_id = uuid.UUID(envelope.data["order_id"])
        order = db.get(Order, order_id)
        if order is None or order.status != OrderStatus.CREATED.value:
            # Already moved on (e.g. concurrently cancelled) or genuinely
            # unknown — nothing to validate, but still record we saw this
            # event so redelivery stays a no-op.
            _mark_processed(db, envelope.event_id)
            db.commit()
            return

        result = db.execute(
            update(Order)
            .where(Order.id == order_id, Order.version == order.version)
            .values(status=OrderStatus.VALIDATED.value, version=Order.version + 1)
        )
        if result.rowcount == 0:
            # Lost a race with a concurrent cancellation — nothing to do.
            _mark_processed(db, envelope.event_id)
            db.commit()
            return

        db.add(
            OrderStatusHistory(
                order_id=order_id,
                from_status=OrderStatus.CREATED.value,
                to_status=OrderStatus.VALIDATED.value,
                reason="automatic validation",
            )
        )
        stage_event(
            db,
            aggregate_type="order",
            aggregate_id=order_id,
            event_type=EventType.ORDER_VALIDATED,
            correlation_id=order.correlation_id,
            causation_id=uuid.UUID(envelope.event_id),
            data={"order_id": str(order_id), "validated_at": datetime.now(UTC).isoformat()},
        )
        _mark_processed(db, envelope.event_id)
        db.commit()


def _dead_letter(
    producer, envelope: EventEnvelope, error: BaseException, attempt_count: int
) -> None:
    logger.error("dead-lettering %s after %s attempts: %s", envelope.event_id, attempt_count, error)
    now = datetime.now(UTC).isoformat()
    dead_letter_envelope = EventEnvelope(
        event_type=EventType.DEADLETTER_EVENT,
        producer="order-service",
        correlation_id=envelope.correlation_id,
        causation_id=envelope.event_id,
        data={
            "original_event": envelope.model_dump(mode="json"),
            "failed_consumer": CONSUMER_NAME,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "attempt_count": attempt_count,
            "first_failed_at": now,
            "last_failed_at": now,
        },
    )
    publish_envelope(
        producer, EventType.DEADLETTER_EVENT, key=envelope.event_id, envelope=dead_letter_envelope
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name)
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    start_http_server(settings.metrics_port)
    consumer = build_consumer(
        settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        topics=[EventType.ORDER_CREATED],
        stats_cb=kafka_stats_callback(),
    )
    producer = build_producer(settings.kafka_bootstrap_servers)
    session_factory = sessionmaker(bind=get_engine(), future=True)
    logger.info("%s started", CONSUMER_NAME)

    run_consume_loop(
        consumer,
        lambda envelope: process_order_created(session_factory, envelope),
        on_dead_letter=lambda envelope, error, attempt: _dead_letter(
            producer, envelope, error, attempt
        ),
    )


if __name__ == "__main__":
    main()
