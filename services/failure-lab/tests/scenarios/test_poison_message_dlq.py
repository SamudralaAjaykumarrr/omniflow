import json
import uuid
from datetime import UTC, datetime

from app.models import STATUS_ERROR, STATUS_PASSED, FailureLabDeadLetter
from app.scenarios import poison_message_dlq
from tests.fakes import FakeKafkaProducer


class _InstantDeadLetterProducer(FakeKafkaProducer):
    """Simulates app.poison_consumer having already processed the message
    and dead-lettered it, by inserting the row directly — this test is
    about poison_message_dlq.run()'s polling/assertion logic, not about
    re-exercising the poison consumer's own retry/backoff (that's
    tests/test_poison_consumer.py's job)."""

    def __init__(self, db_session) -> None:
        super().__init__()
        self._db = db_session

    def produce(self, topic, key=None, value=None, on_delivery=None) -> None:  # noqa: ANN001
        super().produce(topic, key=key, value=value, on_delivery=on_delivery)
        envelope = json.loads(value)
        now = datetime.now(UTC)
        self._db.add(
            FailureLabDeadLetter(
                original_event_id=uuid.UUID(envelope["event_id"]),
                correlation_id=uuid.UUID(envelope["correlation_id"]),
                error_type="PoisonMessageError",
                error_message="simulated unrecoverable processing failure",
                attempt_count=3,
                payload=envelope,
                first_failed_at=now,
                last_failed_at=now,
            )
        )
        self._db.commit()


def test_run_passes_once_the_message_is_dead_lettered(make_ctx, db_session):
    producer = _InstantDeadLetterProducer(db_session)
    ctx = make_ctx(producer=producer)

    outcome = poison_message_dlq.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert outcome.diagnostics["error_type"] == "PoisonMessageError"
    assert outcome.diagnostics["attempt_count"] == 3
    assert len(producer.produced) == 1


def test_run_errors_if_nothing_ever_gets_dead_lettered(make_ctx):
    ctx = make_ctx()  # plain FakeKafkaProducer — nothing inserts a dead-letter row
    outcome = poison_message_dlq.run(ctx)
    assert outcome.status == STATUS_ERROR


def test_reset_clears_failure_lab_dead_letters(make_ctx, db_session):
    producer = _InstantDeadLetterProducer(db_session)
    ctx = make_ctx(producer=producer)
    poison_message_dlq.run(ctx)
    assert db_session.query(FailureLabDeadLetter).count() == 1

    summary = poison_message_dlq.reset(ctx)

    assert db_session.query(FailureLabDeadLetter).count() == 0
    assert "1" in summary
