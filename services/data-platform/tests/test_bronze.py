from __future__ import annotations

from datetime import UTC, datetime

from app.bronze import transform_to_bronze, transform_to_bronze_rejects
from event_contracts.envelope import EventEnvelope
from event_contracts.event_types import EventType


def _kafka_row(envelope: EventEnvelope, *, topic: str, partition: int = 0, offset: int = 0):
    return _kafka_row_raw(
        envelope.model_dump_json(), topic=topic, partition=partition, offset=offset
    )


def _kafka_row_raw(value: str, *, topic: str, partition: int = 0, offset: int = 0):
    return {
        "value": value,
        "topic": topic,
        "partition": partition,
        "offset": offset,
        "timestamp": datetime.now(UTC),
    }


def test_transform_to_bronze_extracts_envelope_fields_and_keeps_data_as_json(spark):
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="order-service",
        correlation_id="corr-1",
        causation_id=None,
        occurred_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC),
        data={
            "order_id": "order-1",
            "customer_id": "cust-1",
            "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 9.99}],
            "order_total": 19.98,
            "currency": "USD",
            "idempotency_key": "idem-1",
        },
    )
    raw = spark.createDataFrame([_kafka_row(envelope, topic="order.created")])

    bronze = transform_to_bronze(raw)
    row = bronze.collect()[0]

    assert row["event_id"] == envelope.event_id
    assert row["event_type"] == EventType.ORDER_CREATED
    assert row["kafka_topic"] == "order.created"
    assert row["kafka_offset"] == 0
    assert row["date"] == datetime(2026, 7, 1).date()
    # data is kept as a loosely-typed JSON string, not parsed here — Bronze
    # never breaks on an unexpected/new payload shape (docs/data-pipeline.md
    # "Schema evolution strategy").
    assert '"order_id":"order-1"' in row["data_json"]


def test_transform_to_bronze_handles_null_traceparent(spark):
    envelope = EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id="corr-2",
        data={"order_id": "order-2", "validated_at": "2026-07-01T12:00:00Z"},
    )
    raw = spark.createDataFrame([_kafka_row(envelope, topic="order.validated")])

    bronze = transform_to_bronze(raw)
    row = bronze.collect()[0]

    assert row["traceparent"] is None


def test_transform_to_bronze_is_append_only_no_dedup_or_filtering(spark):
    """Bronze keeps every delivery, including exact duplicates — dedup is
    Silver's job, not Bronze's (docs/data-pipeline.md)."""
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="order-service",
        correlation_id="corr-3",
        data={
            "order_id": "order-3",
            "customer_id": "cust-3",
            "items": [],
            "order_total": 0.0,
            "currency": "USD",
            "idempotency_key": "idem-3",
        },
    )
    raw = spark.createDataFrame(
        [
            _kafka_row(envelope, topic="order.created", offset=0),
            _kafka_row(envelope, topic="order.created", offset=1),
        ]
    )

    bronze = transform_to_bronze(raw)

    assert bronze.count() == 2


def test_transform_to_bronze_excludes_malformed_json(spark):
    """Garbage (unparseable) JSON must never reach the main Bronze table —
    `transform_to_bronze` should filter it out entirely; it's
    `transform_to_bronze_rejects`'s job to keep it (quarantined)."""
    rows = [
        _kafka_row_raw("not valid json at all {{{", topic="order.created"),
    ]
    raw = spark.createDataFrame(rows)

    bronze = transform_to_bronze(raw)

    assert bronze.count() == 0


def test_transform_to_bronze_excludes_valid_json_with_no_envelope_shape(spark):
    """Well-formed JSON that isn't an event envelope (missing both
    `event_id` and `event_type`) is also treated as malformed, not silently
    written into Bronze with null envelope columns."""
    rows = [
        _kafka_row_raw('{"totally": "unrelated", "shape": 1}', topic="order.created"),
    ]
    raw = spark.createDataFrame(rows)

    bronze = transform_to_bronze(raw)

    assert bronze.count() == 0


def test_transform_to_bronze_rejects_quarantines_malformed_json_with_reason(spark):
    rows = [
        _kafka_row_raw("not valid json at all {{{", topic="order.created", offset=5),
    ]
    raw = spark.createDataFrame(rows)

    rejects = transform_to_bronze_rejects(raw)
    row = rejects.collect()[0]

    assert row["kafka_topic"] == "order.created"
    assert row["kafka_offset"] == 5
    assert row["raw_value"] == "not valid json at all {{{"
    assert row["reason"] == "unparseable_or_empty_envelope"


def test_transform_to_bronze_rejects_is_empty_for_valid_events(spark):
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="order-service",
        correlation_id="corr-4",
        data={
            "order_id": "order-4",
            "customer_id": "cust-4",
            "items": [],
            "order_total": 0.0,
            "currency": "USD",
            "idempotency_key": "idem-4",
        },
    )
    raw = spark.createDataFrame([_kafka_row(envelope, topic="order.created")])

    rejects = transform_to_bronze_rejects(raw)

    assert rejects.count() == 0


def test_transform_to_bronze_and_rejects_partition_every_row_exactly_once(spark):
    """A mixed batch of one valid event and one malformed record must have
    every row accounted for in exactly one of the two outputs — never both,
    never neither."""
    envelope = EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id="corr-5",
        data={"order_id": "order-5", "validated_at": "2026-07-01T12:00:00Z"},
    )
    rows = [
        _kafka_row(envelope, topic="order.validated"),
        _kafka_row_raw("{{{not json", topic="order.validated", offset=1),
    ]
    raw = spark.createDataFrame(rows)

    assert transform_to_bronze(raw).count() == 1
    assert transform_to_bronze_rejects(raw).count() == 1
