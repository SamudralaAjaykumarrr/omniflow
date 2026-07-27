import json
import uuid

import pytest
from sqlalchemy import select

from app.models import FailureLabDeadLetter
from app.poison_consumer import PoisonMessageError, dead_letter, process_poison_message
from event_contracts import EventEnvelope
from tests.fakes import FakeKafkaProducer


def test_process_poison_message_always_raises():
    envelope = EventEnvelope(
        event_type="failure-lab.poison",
        producer="failure-lab",
        correlation_id=str(uuid.uuid4()),
        data={},
    )
    with pytest.raises(PoisonMessageError):
        process_poison_message(envelope)


def test_dead_letter_persists_a_row_and_publishes_a_real_deadletter_event(
    db_session, session_factory
):
    envelope = EventEnvelope(
        event_type="failure-lab.poison",
        producer="failure-lab",
        correlation_id=str(uuid.uuid4()),
        data={"reason": "x"},
    )
    producer = FakeKafkaProducer()

    dead_letter(
        session_factory, producer, envelope, PoisonMessageError("simulated"), attempt_count=3
    )

    row = db_session.execute(
        select(FailureLabDeadLetter).where(
            FailureLabDeadLetter.original_event_id == uuid.UUID(envelope.event_id)
        )
    ).scalar_one()
    assert row.error_type == "PoisonMessageError"
    assert row.attempt_count == 3
    assert row.error_message == "simulated"

    assert len(producer.produced) == 1
    published = producer.produced[0]
    assert published["topic"] == "deadletter.event"
    published_envelope = json.loads(published["value"])
    assert published_envelope["data"]["original_event"]["event_id"] == envelope.event_id
    assert published_envelope["data"]["failed_consumer"] == "failure-lab-poison-consumer"
