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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.models import OutboxEvent
from event_contracts import EventEnvelope, build_producer, publish_envelope
from event_contracts.kafka import KafkaPublishError

logger = logging.getLogger("fulfillment_orchestrator.outbox_relay")

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
    published = 0
    with session_factory() as db:
        now = datetime.now(UTC)
        for row in _due_rows(db, now):
            envelope = EventEnvelope.model_validate(row.payload)
            try:
                publish_envelope(
                    producer, topic=row.event_type, key=str(row.aggregate_id), envelope=envelope
                )
            except KafkaPublishError:
                row.attempt_count += 1
                backoff = min(BACKOFF_BASE_SECONDS * (2**row.attempt_count), MAX_BACKOFF_SECONDS)
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
            row.published_at = now
            row.attempt_count += 1
            db.commit()
            published += 1
    return published


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
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
