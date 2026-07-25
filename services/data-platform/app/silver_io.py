"""Shared Silver-reading helpers — used by Gold, DQ, and backfill/reprocess.

Mirrors `app.silver.read_bronze_stream_for_type`'s "read the specific
`event_type=` subdirectory directly" trick, one layer up: each event type's
Silver rows live under `silver_path/event_type=<X>/date=<Y>/` with their own
flattened, typed schema (see docs/data-pipeline.md's partitioning strategy),
so a consumer that wants one event type's Silver data reads that
subdirectory with that type's exact schema rather than the whole Silver path.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from app.config import Settings
from app.s3 import ensure_prefix_exists
from app.schemas import SILVER_SCHEMA_REGISTRY

SILVER_ENVELOPE_FIELDS: list[StructField] = [
    StructField("event_id", StringType(), True),
    StructField("schema_version", StringType(), True),
    StructField("occurred_at", TimestampType(), True),
    StructField("producer", StringType(), True),
    StructField("correlation_id", StringType(), True),
    StructField("causation_id", StringType(), True),
    StructField("traceparent", StringType(), True),
    StructField("kafka_topic", StringType(), True),
    StructField("kafka_partition", IntegerType(), True),
    StructField("kafka_offset", LongType(), True),
    StructField("ingested_at", TimestampType(), True),
]


def silver_read_schema(event_type: str, schema_version: str = "1.0.0") -> StructType:
    payload_schema = SILVER_SCHEMA_REGISTRY[(event_type, schema_version)]
    return StructType(SILVER_ENVELOPE_FIELDS + list(payload_schema.fields))


def read_silver_stream(
    spark: SparkSession, settings: Settings, event_type: str, schema_version: str = "1.0.0"
) -> DataFrame:
    """Streaming read of one event type's Silver partition. Ensures the
    partition path exists first (see `app.s3.ensure_prefix_exists`) — Gold
    can otherwise start before Silver has ever written that event type's
    first row, in which case Structured Streaming's file source raises
    `PATH_NOT_FOUND` at query-start rather than waiting for data to appear.
    `date` is declared explicitly rather than left to Structured Streaming's
    partition-column auto-discovery — see `ensure_prefix_exists`'s
    docstring for why that breaks the first time a real `date=<Y>`
    directory appears after the query has already started against an empty
    path."""
    path = f"{settings.silver_path}/event_type={event_type}"
    ensure_prefix_exists(settings, path)
    schema = StructType(
        [*silver_read_schema(event_type, schema_version).fields, StructField("date", DateType())]
    )
    return spark.readStream.schema(schema).parquet(path).withColumn("event_type", F.lit(event_type))


def read_silver_batch(
    spark: SparkSession,
    settings: Settings,
    event_type: str,
    schema_version: str = "1.0.0",
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> DataFrame:
    """Batch (non-streaming) read of one event type's Silver data, optionally
    scoped to a date range — the primitive backfill/reprocess/DQ all share,
    per "backfill is always bounded to a date range" in docs/data-pipeline.md."""
    path = f"{settings.silver_path}/event_type={event_type}"
    schema = silver_read_schema(event_type, schema_version)
    df = spark.read.schema(schema).parquet(path).withColumn("event_type", F.lit(event_type))
    if from_date:
        df = (
            df.filter(F.col("date") >= from_date)
            if "date" in df.columns
            else df.filter(F.to_date("occurred_at") >= from_date)
        )
    if to_date:
        df = (
            df.filter(F.col("date") <= to_date)
            if "date" in df.columns
            else df.filter(F.to_date("occurred_at") <= to_date)
        )
    return df
