from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from app.schemas import BRONZE_TABLE_SCHEMA
from app.silver import (
    DEDUP_WATERMARK,
    LATE_THRESHOLD_SECONDS,
    mark_lateness,
    normalize,
    parse_and_flatten,
    split_silver_batch,
    validate,
)
from event_contracts.event_types import EventType

_BRONZE_FIELD_NAMES = [f.name for f in BRONZE_TABLE_SCHEMA.fields]


def _bronze_row(
    *,
    event_id: str | None,
    occurred_at: str,
    ingested_at: datetime,
    data: dict,
    schema_version: str = "1.0.0",
) -> dict:
    return {
        "event_id": event_id,
        "schema_version": schema_version,
        "occurred_at": occurred_at,
        "producer": "test",
        "correlation_id": "corr-1",
        "causation_id": None,
        "traceparent": None,
        "data_json": json.dumps(data),
        "kafka_topic": "test-topic",
        "kafka_partition": 0,
        "kafka_offset": 0,
        "kafka_timestamp": ingested_at,
        "ingested_at": ingested_at,
    }


def _bronze_df(spark, event_type: str, rows: list[dict]):
    """Builds a DataFrame shaped exactly like `app.silver.read_bronze_stream_for_type`'s
    real output (explicit `BRONZE_TABLE_SCHEMA` + a literal `event_type`
    column) — with an explicit schema so all-null test columns (e.g.
    `causation_id`) don't trip Spark's type-inference-from-data path."""
    tuples = [tuple(row.get(name) for name in _BRONZE_FIELD_NAMES) for row in rows]
    df = spark.createDataFrame(tuples, schema=BRONZE_TABLE_SCHEMA)
    return df.withColumn("event_type", F.lit(event_type))


def test_parse_and_flatten_extracts_typed_payload_columns(spark):
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_CREATED,
        [
            _bronze_row(
                event_id="evt-1",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={
                    "order_id": "order-1",
                    "customer_id": "cust-1",
                    "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 9.99}],
                    "order_total": 19.98,
                    "currency": "USD",
                    "idempotency_key": "idem-1",
                },
            )
        ],
    )

    result = parse_and_flatten(df, EventType.ORDER_CREATED).collect()[0]

    assert result["order_id"] == "order-1"
    assert result["order_total"] == 19.98
    assert result["items"][0]["sku"] == "SKU-1"
    # Spark's TimestampType collects as a naive datetime under
    # spark.sql.session.timeZone=UTC (set by both the `spark` fixture and
    # app.spark_session.build_spark_session) — it represents UTC wall-clock
    # time but carries no tzinfo, so it's compared against `now` naive.
    assert result["occurred_at_ts"] == now.replace(tzinfo=None)


def test_parse_and_flatten_extracts_deadletter_original_event_as_json_string(spark):
    """Regression test: the real producers
    (fulfillment-orchestrator/app/consumer.py,
    order-service/app/validator_consumer.py) publish `original_event` as a
    JSON *object*, not a string — a plain `from_json` against this field's
    StringType would silently null it out. See `parse_and_flatten`'s
    docstring/comment for the fix."""
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.DEADLETTER_EVENT,
        [
            _bronze_row(
                event_id="evt-dlq-1",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={
                    "original_event": {
                        "event_id": "evt-original",
                        "event_type": "order.created",
                        "data": {"order_id": "order-1"},
                    },
                    "failed_consumer": "order-service-validator",
                    "error_type": "ValueError",
                    "error_message": "boom",
                    "attempt_count": 5,
                    "first_failed_at": now.isoformat(),
                    "last_failed_at": now.isoformat(),
                },
            )
        ],
    )

    result = parse_and_flatten(df, EventType.DEADLETTER_EVENT).collect()[0]

    assert result["original_event"] is not None
    parsed_original = json.loads(result["original_event"])
    assert parsed_original["event_type"] == "order.created"
    assert parsed_original["data"]["order_id"] == "order-1"


def test_validate_accepts_well_formed_row(spark):
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-1",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={"order_id": "order-1", "validated_at": now.isoformat()},
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    result = validate(flattened, EventType.ORDER_VALIDATED).collect()[0]

    assert result["_valid"] is True
    assert result["_rejection_reason"] is None


def test_validate_rejects_missing_required_field(spark):
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-2",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={"order_id": None, "validated_at": now.isoformat()},
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    result = validate(flattened, EventType.ORDER_VALIDATED).collect()[0]

    assert result["_valid"] is False
    assert result["_rejection_reason"] == "missing_required_field:order_id"


def test_validate_rejects_missing_event_id(spark):
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id=None,
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={"order_id": "order-1", "validated_at": now.isoformat()},
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    result = validate(flattened, EventType.ORDER_VALIDATED).collect()[0]

    assert result["_valid"] is False
    assert result["_rejection_reason"] == "missing_event_id"


def test_validate_rejects_unparseable_timestamp(spark):
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-3",
                occurred_at="not-a-timestamp",
                ingested_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC),
                data={"order_id": "order-1", "validated_at": "2026-07-01T12:00:00Z"},
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    result = validate(flattened, EventType.ORDER_VALIDATED).collect()[0]

    assert result["_valid"] is False
    assert result["_rejection_reason"] == "invalid_timestamp"


def test_validate_rejects_row_declaring_an_unknown_schema_version(spark):
    """`validate` checks each row's own `schema_version` column against the
    registry — not the static parameter `parse_and_flatten`/`validate` were
    called with (always a registered version in production, since
    `build_type_query` only ever passes its own default). A producer
    declaring an unsupported version in the envelope is what this catches;
    the row's payload otherwise conforms to the "1.0.0" shape, so parsing
    itself still succeeds — only `validate` should flag it."""
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-4",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={"order_id": "order-1", "validated_at": now.isoformat()},
                schema_version="9.9.9",
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    result = validate(flattened, EventType.ORDER_VALIDATED).collect()[0]

    assert result["_valid"] is False
    assert result["_rejection_reason"] == "unknown_schema_version"


def test_normalize_derives_date_and_renames_occurred_at(spark):
    now = datetime(2026, 7, 4, 3, 0, 0, tzinfo=UTC)
    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-5",
                occurred_at=now.isoformat(),
                ingested_at=now,
                data={"order_id": "order-1", "validated_at": now.isoformat()},
            )
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)
    validated = validate(flattened, EventType.ORDER_VALIDATED)

    normalized = normalize(validated.drop("_valid", "_rejection_reason"))
    result = normalized.collect()[0]

    assert "occurred_at_ts" not in normalized.columns
    assert result["occurred_at"] == now.replace(tzinfo=None)
    assert result["date"] == now.date()


def test_mark_lateness_flags_rows_ingested_long_after_they_occurred(spark):
    occurred_at = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    on_time_ingest = occurred_at + timedelta(seconds=5)
    late_ingest = occurred_at + timedelta(seconds=LATE_THRESHOLD_SECONDS + 60)

    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-on-time",
                occurred_at=occurred_at.isoformat(),
                ingested_at=on_time_ingest,
                data={"order_id": "order-1", "validated_at": occurred_at.isoformat()},
            ),
            _bronze_row(
                event_id="evt-late",
                occurred_at=occurred_at.isoformat(),
                ingested_at=late_ingest,
                data={"order_id": "order-2", "validated_at": occurred_at.isoformat()},
            ),
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)

    marked = mark_lateness(flattened)
    by_id = {row["event_id"]: row["_late"] for row in marked.collect()}

    assert by_id["evt-on-time"] is False
    assert by_id["evt-late"] is True


def test_split_silver_batch_routes_on_time_late_and_invalid_rows_separately(spark):
    occurred_at = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    on_time_ingest = occurred_at + timedelta(seconds=5)
    late_ingest = occurred_at + timedelta(seconds=LATE_THRESHOLD_SECONDS + 60)

    df = _bronze_df(
        spark,
        EventType.ORDER_VALIDATED,
        [
            _bronze_row(
                event_id="evt-on-time",
                occurred_at=occurred_at.isoformat(),
                ingested_at=on_time_ingest,
                data={"order_id": "order-1", "validated_at": occurred_at.isoformat()},
            ),
            _bronze_row(
                event_id="evt-late",
                occurred_at=occurred_at.isoformat(),
                ingested_at=late_ingest,
                data={"order_id": "order-2", "validated_at": occurred_at.isoformat()},
            ),
            _bronze_row(
                event_id="evt-invalid",
                occurred_at=occurred_at.isoformat(),
                ingested_at=on_time_ingest,
                data={"order_id": None, "validated_at": occurred_at.isoformat()},
            ),
        ],
    )
    flattened = parse_and_flatten(df, EventType.ORDER_VALIDATED)
    validated = validate(flattened, EventType.ORDER_VALIDATED)

    on_time, late, invalid = split_silver_batch(validated)

    assert [r["event_id"] for r in on_time.collect()] == ["evt-on-time"]
    late_rows = late.collect()
    assert [r["event_id"] for r in late_rows] == ["evt-late"]
    assert late_rows[0]["dropped_reason"] == "late"
    assert [r["event_id"] for r in invalid.collect()] == ["evt-invalid"]


def test_dedup_within_watermark_collapses_redelivered_event_id(spark, tmp_path):
    """Exercises the real streaming primitive `app.silver.build_type_query`
    uses (`withWatermark` + `dropDuplicatesWithinWatermark`), which can't be
    driven by a static DataFrame — Spark requires a genuine streaming
    source for it. Writes input as files, reads them back with
    `readStream`, same `trigger(availableNow=True)` pattern the real jobs
    use for their `--once` mode."""
    schema = StructType(
        [
            StructField("event_id", StringType()),
            StructField("occurred_at_ts", TimestampType()),
            StructField("value", StringType()),
        ]
    )
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    rows = [
        ("evt-1", now, "first-delivery"),
        ("evt-1", now, "redelivered-duplicate"),
        ("evt-2", now, "distinct-event"),
    ]
    input_dir = tmp_path / "input"
    spark.createDataFrame(rows, schema=schema).write.parquet(str(input_dir))

    stream_df = spark.readStream.schema(schema).parquet(str(input_dir))
    deduped = stream_df.withWatermark(
        "occurred_at_ts", DEDUP_WATERMARK
    ).dropDuplicatesWithinWatermark(["event_id"])

    query = (
        deduped.writeStream.format("memory")
        .queryName("dedup_test")
        .outputMode("append")
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()

    result = spark.sql("SELECT * FROM dedup_test").collect()
    assert len(result) == 2
    assert {r["event_id"] for r in result} == {"evt-1", "evt-2"}
