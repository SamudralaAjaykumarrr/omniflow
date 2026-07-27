import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.consumer import dead_letter, process_message
from app.models import DeadLetterEvent, OutboxEvent
from app.replay import replay_one
from event_contracts import EventEnvelope, EventType
from event_contracts.kafka import run_consume_loop
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


class FakeMessage:
    def __init__(self, envelope: EventEnvelope) -> None:
        self._envelope = envelope

    def error(self):
        return None

    def value(self) -> bytes:
        return self._envelope.model_dump_json().encode("utf-8")


class FakeConsumer:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = list(messages)
        self.committed: list[FakeMessage] = []

    def poll(self, timeout):
        if self._messages:
            return self._messages.pop(0)
        return None

    def commit(self, message):
        self.committed.append(message)


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bytes]] = []

    def produce(self, topic, key, value, on_delivery=None):
        self.published.append((topic, key, value))
        if on_delivery:
            on_delivery(None, None)

    def flush(self, timeout=10):
        return 0


def _poison_envelope() -> EventEnvelope:
    # Missing "order_id" — handle_order_validated will KeyError on
    # envelope.data["order_id"], a genuine unexpected-exception poison
    # message, not a modeled business rejection.
    return EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"not_order_id": "oops"},
    )


def test_poison_message_is_dead_lettered_and_committed(session_factory, db_session):
    envelope = _poison_envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])
    order_client = FakeOrderServiceClient()
    inventory_client = FakeInventoryServiceClient()

    counter = {"polls": 0}

    def running():
        counter["polls"] += 1
        return counter["polls"] <= 10

    run_consume_loop(
        consumer,
        lambda e: process_message(session_factory, order_client, inventory_client, e),
        on_dead_letter=lambda e, err, attempt: dead_letter(session_factory, e, err, attempt),
        max_attempts=3,
        base_delay=0.001,
        max_delay=0.01,
        running=running,
    )

    assert len(consumer.committed) == 1  # poison message must not block the partition

    dead_letters = (
        db_session.execute(
            select(DeadLetterEvent).where(
                DeadLetterEvent.original_event_id == uuid.UUID(envelope.event_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(dead_letters) == 1
    assert dead_letters[0].error_type == "KeyError"
    assert dead_letters[0].attempt_count == 3
    assert dead_letters[0].replayed_at is None

    outbox_rows = (
        db_session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == EventType.DEADLETTER_EVENT)
        )
        .scalars()
        .all()
    )
    assert len(outbox_rows) == 1


def test_replay_republishes_the_original_event_and_marks_replayed(db_session):
    original = EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": str(uuid.uuid4()), "validated_at": "2026-07-24T00:00:00Z"},
    )
    now = datetime.now(UTC)
    dead_letter_row = DeadLetterEvent(
        original_event_id=uuid.UUID(original.event_id),
        event_type=original.event_type,
        failed_consumer="fulfillment-orchestrator",
        error_type="KeyError",
        error_message="boom",
        attempt_count=5,
        # The flat envelope itself — matches what app.consumer.dead_letter()
        # actually stores (`payload=envelope.model_dump(...)`), not wrapped
        # in an "original_event" key. An earlier version of this fixture
        # used the wrong (wrapped) shape, which made this test a false
        # positive: it never caught replay_one's real KeyError bug (fixed
        # alongside this test, found running Phase 8's downstream-outage
        # scenario against a live stack, not by any existing test).
        payload=original.model_dump(mode="json"),
        first_failed_at=now,
        last_failed_at=now,
    )
    db_session.add(dead_letter_row)
    db_session.commit()

    producer = FakeProducer()
    replay_one(producer, db_session, dead_letter_row)

    assert len(producer.published) == 1
    topic, key, value = producer.published[0]
    assert topic == EventType.ORDER_VALIDATED
    republished = EventEnvelope.model_validate_json(value)
    assert republished.event_id == original.event_id  # identity preserved for idempotent consumers

    db_session.refresh(dead_letter_row)
    assert dead_letter_row.replayed_at is not None
