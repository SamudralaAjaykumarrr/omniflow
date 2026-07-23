import uuid

from event_contracts import EventEnvelope, EventType


def test_envelope_requires_producer_type_correlation_and_data():
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": str(uuid.uuid4())},
    )
    assert envelope.event_id  # minted automatically
    assert envelope.schema_version == "1.0.0"
    assert envelope.causation_id is None
    assert envelope.occurred_at.tzinfo is not None  # always tz-aware (UTC)


def test_envelope_round_trips_through_json():
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CANCELLED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        causation_id=str(uuid.uuid4()),
        data={"order_id": "abc", "reason": "test"},
    )
    raw = envelope.model_dump_json()
    restored = EventEnvelope.model_validate_json(raw)
    assert restored == envelope


def test_two_envelopes_get_distinct_event_ids():
    a = EventEnvelope(event_type=EventType.ORDER_CREATED, producer="x", correlation_id="c", data={})
    b = EventEnvelope(event_type=EventType.ORDER_CREATED, producer="x", correlation_id="c", data={})
    assert a.event_id != b.event_id
