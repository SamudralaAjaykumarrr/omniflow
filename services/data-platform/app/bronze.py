"""Bronze — immutable raw events. Kafka (all 11 topics) -> Parquet, as-is.

See "Bronze — immutable raw events" in docs/data-pipeline.md. Append-only,
never updated or deleted: the system of record for "what did the bus
actually carry" and the input to any Silver reprocessing.

Malformed-event handling: a Kafka record whose `value` isn't parseable JSON
matching the event envelope shape (or is empty/tombstone) is quarantined to
`bronze_rejects` (see `transform_to_bronze_rejects`) rather than being
written into Bronze with null envelope fields under an unusable
`event_type=null/date=null` partition, which would otherwise leave it
invisible to every downstream reader (Silver only ever reads a specific
`event_type=<X>` subdirectory — see `app.silver.read_bronze_stream_for_type`).
This is a distinct, earlier quarantine step from Silver's own
`silver_rejects` (which quarantines rows with a parseable envelope but a
failed schema/business validation) — see "Malformed-event handling" in
docs/data-pipeline.md.
"""

from __future__ import annotations

import argparse
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from app.config import Settings, get_settings
from app.metrics import record_rows, start_metrics_server, track_batch_duration
from app.schemas import BRONZE_TABLE_SCHEMA, ENVELOPE_SCHEMA
from app.spark_session import build_spark_session
from app.topics import ALL_TOPICS

logger = logging.getLogger("data_platform.bronze")


def read_kafka_stream(
    spark: SparkSession,
    settings: Settings,
    topics: list[str] | None = None,
    starting_offsets: str = "earliest",
) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka_bootstrap_servers)
        .option("subscribe", ",".join(topics or ALL_TOPICS))
        .option("startingOffsets", starting_offsets)
        .option("failOnDataLoss", "false")
        .load()
    )


def _envelope_is_malformed(raw_df: DataFrame) -> DataFrame:
    """Shared detection expression: flags a Kafka row as malformed if its
    `value` is empty/null, or is JSON that doesn't parse into anything
    matching the envelope shape. `from_json` against a `StructType` never
    raises — it returns a wholly-null struct (unparseable JSON syntax, or
    top-level JSON that isn't an object) or a struct with individually-null
    fields (valid JSON object, wrong/empty shape); a row missing *both*
    `event_id` and `event_type` is not a real envelope in either case (every
    real producer always sets both — `docs/event-catalog.md`'s envelope is
    non-optional on both). Adds `_malformed`/`_malformed_reason`; never
    drops a row — callers filter by `_malformed` after this."""
    value_str = F.col("value").cast("string")
    parsed = F.from_json(value_str, ENVELOPE_SCHEMA)
    unparseable = parsed.isNull() | (parsed["event_id"].isNull() & parsed["event_type"].isNull())
    reason = F.when(value_str.isNull(), F.lit("empty_kafka_value")).when(
        unparseable, F.lit("unparseable_or_empty_envelope")
    )
    return raw_df.withColumn("_malformed", value_str.isNull() | unparseable).withColumn(
        "_malformed_reason", reason
    )


def transform_to_bronze(raw_df: DataFrame) -> DataFrame:
    """Pure transform: raw Kafka rows -> Bronze rows, excluding malformed
    rows (see `transform_to_bronze_rejects`). Works identically on a
    streaming or a static (batch/test) DataFrame — no I/O, no watermark, so
    it is unit-testable with a plain `spark.createDataFrame(...)`."""
    flagged = _envelope_is_malformed(raw_df).filter(~F.col("_malformed"))
    value_str = F.col("value").cast("string")
    parsed = F.from_json(value_str, ENVELOPE_SCHEMA)
    return flagged.select(
        parsed["event_id"].alias("event_id"),
        parsed["event_type"].alias("event_type"),
        parsed["schema_version"].alias("schema_version"),
        parsed["occurred_at"].alias("occurred_at"),
        parsed["producer"].alias("producer"),
        parsed["correlation_id"].alias("correlation_id"),
        parsed["causation_id"].alias("causation_id"),
        parsed["trace_context"]["traceparent"].alias("traceparent"),
        F.get_json_object(value_str, "$.data").alias("data_json"),
        F.col("topic").alias("kafka_topic"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_timestamp"),
        F.current_timestamp().alias("ingested_at"),
        F.to_date(F.to_timestamp("occurred_at")).alias("date"),
    )


def transform_to_bronze_rejects(raw_df: DataFrame) -> DataFrame:
    """Pure transform: raw Kafka rows -> Bronze quarantine rows (the
    complement of `transform_to_bronze`). Partitioned by ingestion date only
    (not `event_type`, which is unknown for a malformed payload by
    definition) — see "Malformed-event handling" in docs/data-pipeline.md.
    Keeps the raw string value and Kafka coordinates so an operator can
    inspect exactly what the bus carried and, if a producer bug is later
    fixed, correlate against `kafka_topic`/`kafka_partition`/`kafka_offset`."""
    flagged = _envelope_is_malformed(raw_df).filter(F.col("_malformed"))
    return flagged.select(
        F.col("topic").alias("kafka_topic"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_timestamp"),
        F.col("value").cast("string").alias("raw_value"),
        F.col("_malformed_reason").alias("reason"),
        F.current_timestamp().alias("ingested_at"),
        F.current_date().alias("date"),
    )


def read_bronze_batch(
    spark: SparkSession,
    settings: Settings,
    event_type: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> DataFrame:
    """Batch (non-streaming) read of one event type's Bronze data, optionally
    scoped to a date range — the primitive `app.backfill` reprocessing shares
    with `app.silver_io.read_silver_batch`, one layer earlier. `date` is
    recovered via Spark's own partition-directory discovery, same trick
    `read_kafka_stream`'s streaming counterpart uses (see `app.schemas`)."""
    path = f"{settings.bronze_path}/event_type={event_type}"
    df = (
        spark.read.schema(BRONZE_TABLE_SCHEMA)
        .parquet(path)
        .withColumn("event_type", F.lit(event_type))
    )
    if from_date:
        df = df.filter(F.col("date") >= from_date)
    if to_date:
        df = df.filter(F.col("date") <= to_date)
    return df


def _write_batch(settings: Settings):
    def _inner(batch_df: DataFrame, batch_id: int) -> None:
        with track_batch_duration("bronze", "all_topics"):
            valid = transform_to_bronze(batch_df)
            rejects = transform_to_bronze_rejects(batch_df)
            valid_count = valid.count()
            if valid_count > 0:
                valid.write.mode("append").partitionBy("event_type", "date").parquet(
                    settings.bronze_path
                )
            reject_count = rejects.count()
            if reject_count > 0:
                rejects.write.mode("append").partitionBy("date").parquet(
                    settings.bronze_rejects_path
                )
        record_rows("bronze", "all_topics", {"valid": valid_count, "malformed": reject_count})
        logger.info(
            "bronze batch %s: %s valid, %s malformed (quarantined to bronze_rejects)",
            batch_id,
            valid_count,
            reject_count,
        )

    return _inner


def write_bronze_stream(
    raw_df: DataFrame,
    settings: Settings,
    *,
    trigger_once: bool = False,
) -> StreamingQuery:
    writer = (
        raw_df.writeStream.foreachBatch(_write_batch(settings))
        .option("checkpointLocation", f"{settings.checkpoints_path}/bronze")
        .outputMode("append")
    )
    if trigger_once:
        writer = writer.trigger(availableNow=True)
    else:
        writer = writer.trigger(processingTime="5 seconds")
    return writer.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bronze: Kafka -> raw Parquet")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process all currently-available data then stop (availableNow trigger).",
    )
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    start_metrics_server(settings.metrics_port)
    spark = build_spark_session("omniflow-bronze", settings)

    raw = read_kafka_stream(spark, settings)
    query = write_bronze_stream(raw, settings, trigger_once=args.once)
    logger.info("bronze streaming query started (once=%s)", args.once)
    query.awaitTermination()


if __name__ == "__main__":
    main()
