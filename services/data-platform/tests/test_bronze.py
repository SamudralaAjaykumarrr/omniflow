from __future__ import annotations

from datetime import UTC, datetime

from app.bronze import transform_to_bronze
from event_contracts.envelope import EventEnvelope
from event_contracts.event_types import EventType


def _kafka_row(envelope: EventEnvelope, *, topic: str, partition: int = 0, offset: int = 0):
    return {
        "value": envelope.model_dump_json(),
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
