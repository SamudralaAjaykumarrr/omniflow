"""Test-only helpers for building Silver-shaped batch DataFrames without
Kafka/MinIO — same schema `app.silver_io.silver_read_schema` builds for a
real streaming read, so a Gold query function sees exactly the shape it
would see wired to a real Silver stream."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pyspark.sql import DataFrame, SparkSession

from app.silver_io import silver_read_schema

ENVELOPE_DEFAULTS = {
    "event_id": None,
    "schema_version": "1.0.0",
    "producer": "test",
    "correlation_id": "corr-1",
    "causation_id": None,
    "traceparent": None,
    "kafka_topic": None,
    "kafka_partition": 0,
    "kafka_offset": 0,
    "ingested_at": None,
}


def make_silver_df(spark: SparkSession, event_type: str, rows: list[dict]) -> DataFrame:
    """`rows` need only specify `occurred_at` (a `datetime`) plus that event
    type's own payload fields — every envelope column gets a sensible
    default (a fresh `event_id` per row if not given)."""
    schema = silver_read_schema(event_type)
    field_names = [f.name for f in schema.fields]
    filled = []
    for row in rows:
        complete = dict(ENVELOPE_DEFAULTS)
        complete["event_id"] = str(uuid.uuid4())
        complete["ingested_at"] = datetime.now(UTC)
        complete.update(row)
        filled.append(tuple(complete.get(name) for name in field_names))
    return spark.createDataFrame(filled, schema=schema)
