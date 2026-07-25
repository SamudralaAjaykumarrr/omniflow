"""Bronze — immutable raw events. Kafka (all 11 topics) -> Parquet, as-is.

See "Bronze — immutable raw events" in docs/data-pipeline.md. Append-only,
never updated or deleted: the system of record for "what did the bus
actually carry" and the input to any Silver reprocessing.
"""

from __future__ import annotations

import argparse
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from app.config import Settings, get_settings
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


def transform_to_bronze(raw_df: DataFrame) -> DataFrame:
    """Pure transform: raw Kafka rows -> Bronze rows. Works identically on a
    streaming or a static (batch/test) DataFrame — no I/O, no watermark, so
    it is unit-testable with a plain `spark.createDataFrame(...)`."""
    value_str = F.col("value").cast("string")
    parsed = F.from_json(value_str, ENVELOPE_SCHEMA)
    return raw_df.select(
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


def write_bronze_stream(
    df: DataFrame,
    settings: Settings,
    *,
    trigger_once: bool = False,
) -> StreamingQuery:
    writer = (
        df.writeStream.format("parquet")
        .option("path", settings.bronze_path)
        .option("checkpointLocation", f"{settings.checkpoints_path}/bronze")
        .partitionBy("event_type", "date")
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
    spark = build_spark_session("omniflow-bronze", settings)

    raw = read_kafka_stream(spark, settings)
    bronze = transform_to_bronze(raw)
    query = write_bronze_stream(bronze, settings, trigger_once=args.once)
    logger.info("bronze streaming query started (once=%s)", args.once)
    query.awaitTermination()


if __name__ == "__main__":
    main()
