import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.models import OutboxEvent
from app.outbox_relay import run_relay_once


class FakeProducer:
    """Stands in for confluent_kafka.Producer — no real broker needed to test
    the relay's polling/backoff logic, only the Kafka client's own delivery
    guarantees (tested separately against real Redpanda in the compose smoke
    test)."""

    def __init__(self, fail_topics: set[str] | None = None) -> None:
        self.published: list[tuple[str, str, bytes]] = []
        self.fail_topics = fail_topics or set()

    def produce(self, topic, key, value, on_delivery=None):
        if topic in self.fail_topics:
            if on_delivery:
                on_delivery(Exception("simulated broker unavailable"), None)
            return
        self.published.append((topic, key, value))
        if on_delivery:
            on_delivery(None, None)

    def flush(self, timeout=10):
        return 0


def _make_outbox_row(event_type: str = "inventory.reserved") -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        aggregate_type="inventory_reservation",
        aggregate_id=uuid.uuid4(),
        event_type=event_type,
        correlation_id=uuid.uuid4(),
        causation_id=None,
        payload={
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "schema_version": "1.0.0",
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "inventory-service",
            "correlation_id": str(uuid.uuid4()),
            "causation_id": None,
            "trace_context": {"traceparent": None},
            "data": {"order_id": "x"},
        },
    )


def test_relay_publishes_due_rows_and_marks_published(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    row = _make_outbox_row()
    db_session.add(row)
    db_session.commit()

    producer = FakeProducer()
    published_count = run_relay_once(session_factory, producer)

    assert published_count == 1
    assert len(producer.published) == 1
    topic, key, _value = producer.published[0]
    assert topic == "inventory.reserved"
    assert key == str(row.aggregate_id).encode("utf-8")  # publish_envelope encodes the key

    db_session.expire_all()
    refreshed = db_session.get(OutboxEvent, row.id)
    assert refreshed.published_at is not None
    assert refreshed.attempt_count == 1


def test_relay_backs_off_on_publish_failure_and_does_not_mark_published(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    row = _make_outbox_row(event_type="inventory.reserved")
    db_session.add(row)
    db_session.commit()

    producer = FakeProducer(fail_topics={"inventory.reserved"})
    published_count = run_relay_once(session_factory, producer)

    assert published_count == 0
    db_session.expire_all()
    refreshed = db_session.get(OutboxEvent, row.id)
    assert refreshed.published_at is None
    assert refreshed.attempt_count == 1
    assert refreshed.next_attempt_at is not None
    assert refreshed.next_attempt_at > datetime.now(UTC)


def test_relay_skips_rows_not_yet_due_for_retry(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    row = _make_outbox_row()
    row.attempt_count = 1
    row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
    db_session.add(row)
    db_session.commit()

    producer = FakeProducer()
    published_count = run_relay_once(session_factory, producer)

    assert published_count == 0
    assert producer.published == []


def test_relay_ignores_already_published_rows(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    row = _make_outbox_row()
    row.published_at = datetime.now(UTC)
    db_session.add(row)
    db_session.commit()

    producer = FakeProducer()
    published_count = run_relay_once(session_factory, producer)

    assert published_count == 0
    assert producer.published == []
