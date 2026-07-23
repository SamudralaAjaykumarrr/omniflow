"""Kafka consumer entrypoint: subscribes to `order.validated` and
`order.cancelled`, dispatches to the saga engine (app.saga), and routes
poison messages / retry-exhausted events to the dead-letter table + topic.

On startup, resumes any saga a previous crashed process left `RUNNING`
before entering the consume loop — see app.saga.resume_incomplete_sagas.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from app.clients import InventoryServiceClient, OrderServiceClient
from app.config import get_settings
from app.db import get_engine
from app.models import DeadLetterEvent
from app.outbox import stage_event
from app.saga import (
    CONSUMER_NAME,
    handle_order_cancelled,
    handle_order_validated,
    resume_incomplete_sagas,
)
from event_contracts import EventEnvelope, EventType, build_consumer, run_consume_loop

logger = logging.getLogger("fulfillment_orchestrator.consumer")


def process_message(
    session_factory: sessionmaker,
    order_client: OrderServiceClient,
    inventory_client: InventoryServiceClient,
    envelope: EventEnvelope,
) -> None:
    with session_factory() as db:
        if envelope.event_type == EventType.ORDER_VALIDATED:
            handle_order_validated(db, order_client, inventory_client, envelope)
        elif envelope.event_type == EventType.ORDER_CANCELLED:
            handle_order_cancelled(db, inventory_client, envelope)


def dead_letter(
    session_factory: sessionmaker,
    envelope: EventEnvelope,
    error: BaseException,
    attempt_count: int,
) -> None:
    logger.error(
        "dead-lettering %s (%s) after %s attempts: %s",
        envelope.event_id,
        envelope.event_type,
        attempt_count,
        error,
    )
    now = datetime.now(UTC)
    with session_factory() as db:
        db.add(
            DeadLetterEvent(
                original_event_id=uuid.UUID(envelope.event_id),
                event_type=envelope.event_type,
                failed_consumer=CONSUMER_NAME,
                error_type=type(error).__name__,
                error_message=str(error),
                attempt_count=attempt_count,
                payload=envelope.model_dump(mode="json"),
                first_failed_at=now,
                last_failed_at=now,
            )
        )
        stage_event(
            db,
            aggregate_type=envelope.event_type,
            aggregate_id=uuid.UUID(envelope.event_id),
            event_type=EventType.DEADLETTER_EVENT,
            correlation_id=uuid.UUID(envelope.correlation_id),
            causation_id=uuid.UUID(envelope.event_id),
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
        db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    session_factory = sessionmaker(bind=get_engine(), future=True)
    order_client = OrderServiceClient(settings.order_service_url)
    inventory_client = InventoryServiceClient(settings.inventory_service_url)

    with session_factory() as db:
        resumed = resume_incomplete_sagas(db, order_client, inventory_client)
    if resumed:
        logger.info("resumed %s in-flight saga(s) from a previous run", resumed)

    consumer = build_consumer(
        settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        topics=[EventType.ORDER_VALIDATED, EventType.ORDER_CANCELLED],
    )
    logger.info("%s consumer started", CONSUMER_NAME)

    run_consume_loop(
        consumer,
        lambda envelope: process_message(session_factory, order_client, inventory_client, envelope),
        on_dead_letter=lambda envelope, error, attempt: dead_letter(
            session_factory, envelope, error, attempt
        ),
    )


if __name__ == "__main__":
    main()
