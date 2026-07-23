"""Dead-letter replay tooling (docs/event-catalog.md "Replay tooling").

Re-publishes a dead-lettered event's original envelope back onto its
original topic, preserving `event_id` — so an idempotent consumer correctly
treats it as the same logical event, not a new one — and marks the row
`replayed_at`. Run via `docker compose run --rm fulfillment-orchestrator
python -m app.replay [--id ID | --all]` (see `make replay`).

Never replays a message the operator hasn't chosen to (no automatic retry
loop here — that's what the consumer's own retry/backoff already did before
giving up); this tool is deliberately manual and explicit.
"""

from __future__ import annotations

import argparse
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.models import DeadLetterEvent
from event_contracts import EventEnvelope, build_producer, publish_envelope

logger = logging.getLogger("fulfillment_orchestrator.replay")


def replay_one(producer, db, dead_letter: DeadLetterEvent) -> None:
    original = dead_letter.payload["original_event"]
    envelope = EventEnvelope.model_validate(original)
    publish_envelope(
        producer,
        topic=envelope.event_type,
        key=str(dead_letter.original_event_id),
        envelope=envelope,
    )
    dead_letter.replayed_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "replayed %s (%s) back onto %s", envelope.event_id, envelope.event_type, envelope.event_type
    )


def replay(dead_letter_id: uuid.UUID | None, replay_all: bool) -> int:
    settings = get_settings()
    producer = build_producer(settings.kafka_bootstrap_servers)
    session_factory = sessionmaker(bind=get_engine(), future=True)

    with session_factory() as db:
        if replay_all:
            targets = list(
                db.scalars(select(DeadLetterEvent).where(DeadLetterEvent.replayed_at.is_(None)))
            )
        elif dead_letter_id is not None:
            row = db.get(DeadLetterEvent, dead_letter_id)
            targets = [row] if row is not None else []
        else:
            raise ValueError("must pass either dead_letter_id or replay_all=True")

        for dead_letter in targets:
            replay_one(producer, db, dead_letter)
        return len(targets)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=str, help="dead_letter_events.id to replay")
    group.add_argument("--all", action="store_true", help="replay every unreplayed dead letter")
    args = parser.parse_args()

    count = replay(uuid.UUID(args.id) if args.id else None, args.all)
    logger.info("replayed %s dead letter(s)", count)


if __name__ == "__main__":
    main()
