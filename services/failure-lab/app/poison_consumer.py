"""Standalone worker for the poison-message-dlq scenario
(app.scenarios.poison_message_dlq): consumes `failure-lab.poison`
(app.kafka_topics.POISON_TOPIC) using the exact same generic
`event_contracts.run_consume_loop` every production consumer in this repo
uses, but its `process()` deliberately raises unconditionally — every
message on this topic is poison by definition. No real business consumer
ever subscribes to this topic, so a bug here can never affect order/
inventory/saga processing.

On retry exhaustion, persists to the failure lab's own
`failure_lab_dead_letters` table (mirroring, but never confused with,
fulfillment-orchestrator's `dead_letter_events`) and publishes a real
`deadletter.event` envelope, same as every other consumer's DLQ path — so
this genuinely exercises the same dead-letter mechanism end to end,
including its Bronze/Silver visibility.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from prometheus_client import start_http_server
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.kafka_topics import POISON_TOPIC
from app.models import FailureLabDeadLetter
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

logger = logging.getLogger("failure_lab.poison_consumer")

CONSUMER_NAME = "failure-lab-poison-consumer"


class PoisonMessageError(Exception):
    """Raised unconditionally — every message on POISON_TOPIC is poison."""


def process_poison_message(envelope: EventEnvelope) -> None:
    raise PoisonMessageError(
        f"simulated unrecoverable processing failure for {envelope.event_id} "
        "(this is the point of the scenario, not a real bug)"
    )


def dead_letter(
    session_factory: sessionmaker,
    producer,
    envelope: EventEnvelope,
    error: BaseException,
    attempt_count: int,
) -> None:
    logger.info(
        "dead-lettering poison message %s after %s attempts (expected)",
        envelope.event_id,
        attempt_count,
    )
    now = datetime.now(UTC)
    with session_factory() as db:
        db.add(
            FailureLabDeadLetter(
                original_event_id=uuid.UUID(envelope.event_id),
                correlation_id=uuid.UUID(envelope.correlation_id),
                error_type=type(error).__name__,
                error_message=str(error),
                attempt_count=attempt_count,
                payload=envelope.model_dump(mode="json"),
                first_failed_at=now,
                last_failed_at=now,
            )
        )
        db.commit()

    dead_letter_envelope = EventEnvelope(
        event_type=EventType.DEADLETTER_EVENT,
        producer="failure-lab",
        correlation_id=envelope.correlation_id,
        causation_id=envelope.event_id,
        data={
            "original_event": envelope.model_dump(mode="json"),
            "failed_consumer": CONSUMER_NAME,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "attempt_count": attempt_count,
            "first_failed_at": now.isoformat(),
            "last_failed_at": now.isoformat(),
        },
    )
    publish_envelope(
        producer,
        topic=EventType.DEADLETTER_EVENT,
        key=envelope.event_id,
        envelope=dead_letter_envelope,
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name)
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    start_http_server(settings.metrics_port)

    consumer = build_consumer(
        settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        topics=[POISON_TOPIC],
        stats_cb=kafka_stats_callback(),
    )
    producer = build_producer(settings.kafka_bootstrap_servers)
    session_factory = sessionmaker(bind=get_engine(), future=True)
    logger.info("%s started, subscribed to %s", CONSUMER_NAME, POISON_TOPIC)

    run_consume_loop(
        consumer,
        process_poison_message,
        on_dead_letter=lambda envelope, error, attempt: dead_letter(
            session_factory, producer, envelope, error, attempt
        ),
        max_attempts=3,
        base_delay=0.1,
        max_delay=1.0,
    )


if __name__ == "__main__":
    main()
