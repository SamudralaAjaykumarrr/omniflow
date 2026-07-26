"""Silver — validated, deduplicated, normalized events.

Reads Bronze (streaming), one query per event type (Bronze is partitioned by
`event_type`, so each query only ever scans its own partition). Per query:

1. Parse `data_json` against that (event_type, schema_version)'s registered
   Spark schema (app.schemas.SILVER_SCHEMA_REGISTRY) and flatten it into
   typed columns.
2. Validate: unknown schema_version, unparseable `occurred_at`, a missing
   envelope `event_id`, or a missing required business key (see
   `REQUIRED_DATA_FIELDS`) fails validation — the row is quarantined to
   `silver_rejects` with a reason, never silently dropped.
3. Deduplicate valid rows by `event_id` within a watermark window
   (`dropDuplicatesWithinWatermark`) — bounds state size while making
   at-least-once redelivery safe (docs/data-pipeline.md's "Duplicate
   handling"; a duplicate arriving after the watermark has closed is a
   documented, accepted limitation, not a silent bug).
4. Mark lateness: a valid row whose Bronze ingestion (`ingested_at`) lagged
   its own event time (`occurred_at`) by more than `LATE_THRESHOLD_SECONDS`
   is routed to `late_events` (with a `dropped_reason: "late"` flag) instead
   of Silver — see "Watermarks and late data" in docs/data-pipeline.md for
   why this is measured here rather than per-Gold-dataset.
5. Write on-time valid rows to Silver, partitioned by `event_type`/`date`.

See "Silver — validated, deduplicated, normalized" in docs/data-pipeline.md.
"""

from __future__ import annotations

import argparse
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery
from pyspark.sql.types import DateType, StructField, StructType

from app.config import Settings, get_settings
from app.metrics import record_rows, start_metrics_server, track_batch_duration
from app.s3 import ensure_prefix_exists
from app.schemas import BRONZE_TABLE_SCHEMA, REQUIRED_DATA_FIELDS, SILVER_SCHEMA_REGISTRY
from app.spark_session import build_spark_session
from app.topics import ALL_TOPICS
from event_contracts.event_types import EventType

# `date` declared explicitly (not left to Structured Streaming's
# partition-column auto-discovery — see `app.s3.ensure_prefix_exists`'s
# docstring for why that breaks the first time a real `date=<Y>` directory
# appears after the query has already started against an empty path).
BRONZE_STREAM_SCHEMA = StructType([*BRONZE_TABLE_SCHEMA.fields, StructField("date", DateType())])

logger = logging.getLogger("data_platform.silver")

DEDUP_WATERMARK = "10 minutes"

# Matches DEDUP_WATERMARK, expressed in seconds for the lateness comparison
# below. Gold datasets use their own, per-dataset watermarks (10-30 minutes,
# app.gold.queries) for their windowed aggregations; this single, fixed
# threshold is deliberately not synced to each of those individually. It is
# the one point in the pipeline where lateness can be measured directly off
# an event's own already-known timestamps (`ingested_at` - `occurred_at`)
# rather than depending on Structured Streaming's internal per-query
# watermark advancement, which isn't observable per-row from inside a
# `foreachBatch` sink. A row this flags "late" is always at least as late as
# any individual Gold watermark would judge it for the *narrowest* watermark
# in the system (10 minutes) — for a wider-watermark dataset (e.g.
# fulfillment_latency's 30 minutes) this can flag a row "late" that such a
# dataset would still have successfully windowed. Documented, deliberate
# false-positive-safe simplification: never a false negative.
LATE_THRESHOLD_SECONDS = 600

# Columns common to every Silver row regardless of event type — kept
# alongside the flattened, event-type-specific payload columns.
ENVELOPE_COLUMNS = [
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "producer",
    "correlation_id",
    "causation_id",
    "traceparent",
    "kafka_topic",
    "kafka_partition",
    "kafka_offset",
    "ingested_at",
]


def read_bronze_stream_for_type(
    spark: SparkSession,
    settings: Settings,
    event_type: str,
) -> DataFrame:
    """Read only this event type's Bronze partition — reading the specific
    `event_type=<X>` subdirectory directly (rather than the whole Bronze path
    with a filter) avoids Spark trying to reconcile every other event type's
    eventually-different Silver-payload schema against one shared
    `.schema(...)`, and gets partition pruning for free. `event_type` is
    re-added as a literal since the caller already knows it (they picked
    this subdirectory); `date` is declared explicitly in
    `BRONZE_STREAM_SCHEMA` rather than left to partition auto-discovery
    (see that constant's comment)."""
    path = f"{settings.bronze_path}/event_type={event_type}"
    ensure_prefix_exists(settings, path)
    return (
        spark.readStream.schema(BRONZE_STREAM_SCHEMA)
        .parquet(path)
        .withColumn("event_type", F.lit(event_type))
    )


def parse_and_flatten(
    bronze_df: DataFrame, event_type: str, schema_version: str = "1.0.0"
) -> DataFrame:
    """Pure transform: Bronze rows for one event type -> flattened,
    typed-but-unvalidated Silver candidate rows. No I/O, no watermark —
    unit-testable with a static DataFrame."""
    payload_schema = SILVER_SCHEMA_REGISTRY[(event_type, schema_version)]
    parsed = F.from_json(F.col("data_json"), payload_schema)
    payload_cols = []
    for field in payload_schema.fields:
        if event_type == EventType.DEADLETTER_EVENT and field.name == "original_event":
            # `original_event` is a full nested envelope+payload of
            # arbitrary shape, and the real producers
            # (fulfillment-orchestrator/app/consumer.py,
            # order-service/app/validator_consumer.py) publish it as a JSON
            # *object*, matching event_contracts.schemas.DeadLetterEventDataV1's
            # `original_event: dict` — not the JSON string the rest of this
            # field's own StructField(StringType) would need `from_json` to
            # populate it (from_json returns null for an object-shaped node
            # against a StringType target). Extracted directly instead, via
            # the same get_json_object trick app.bronze.transform_to_bronze
            # uses for the top-level `data` field, one level deeper.
            payload_cols.append(
                F.get_json_object(F.col("data_json"), "$.original_event").alias("original_event")
            )
        else:
            payload_cols.append(parsed[field.name].alias(field.name))
    return bronze_df.select(
        *[F.col(c) for c in ENVELOPE_COLUMNS],
        F.to_timestamp(F.col("occurred_at")).alias("occurred_at_ts"),
        *payload_cols,
    )


def validate(df: DataFrame, event_type: str, schema_version: str = "1.0.0") -> DataFrame:
    """Adds `_valid`/`_rejection_reason`. Never drops a row — that is the
    caller's job, split by `_valid` after this.

    `unknown_schema_version` checks each row's own `schema_version` column
    against every version registered for this `event_type` — not the
    `schema_version` parameter (the version `parse_and_flatten` used to
    parse `data_json`, always a registered one in practice, since
    `build_type_query` only ever calls it with its own default). A row
    whose *producer* declared an unsupported version is what this catches;
    checking the query's own static parameter instead would make this
    branch permanently dead code."""
    known_versions = {sv for (et, sv) in SILVER_SCHEMA_REGISTRY if et == event_type}
    required = REQUIRED_DATA_FIELDS.get(event_type, [])

    reasons = [(~F.col("schema_version").isin(known_versions), F.lit("unknown_schema_version"))]
    reasons.append((F.col("event_id").isNull(), F.lit("missing_event_id")))
    reasons.append((F.col("occurred_at_ts").isNull(), F.lit("invalid_timestamp")))
    for field in required:
        reasons.append((F.col(field).isNull(), F.lit(f"missing_required_field:{field}")))

    reason_expr = F.lit(None).cast("string")
    is_invalid = F.lit(False)
    for condition, reason in reversed(reasons):
        reason_expr = F.when(condition, reason).otherwise(reason_expr)
        is_invalid = is_invalid | condition

    return df.withColumn("_valid", ~is_invalid).withColumn("_rejection_reason", reason_expr)


def mark_lateness(df: DataFrame) -> DataFrame:
    """Adds `_late`. No I/O, no watermark — pure column derivation off
    `ingested_at`/`occurred_at_ts`, unit-testable with a static DataFrame."""
    lag_seconds = F.col("ingested_at").cast("double") - F.col("occurred_at_ts").cast("double")
    return df.withColumn("_late", lag_seconds > F.lit(LATE_THRESHOLD_SECONDS))


def normalize(df: DataFrame) -> DataFrame:
    """Final normalization on rows that passed validation: coerce
    `occurred_at` to the canonical typed column, derive the `date` partition
    column, drop the now-redundant raw string column."""
    return (
        df.drop("occurred_at")
        .withColumnRenamed("occurred_at_ts", "occurred_at")
        .withColumn("date", F.to_date("occurred_at"))
    )


def split_silver_batch(batch_df: DataFrame) -> tuple[DataFrame, DataFrame, DataFrame]:
    """Splits a validated (`_valid`/`_rejection_reason`-tagged) batch into
    `(on_time, late, invalid)`, each already normalized (see `normalize`).
    Shared by the real-time Silver write path (`_write_batch` below) and
    batch backfill/reprocessing (`app.backfill.reprocess_silver`), so the
    exact same validation/lateness/normalization logic runs whether Silver
    is being written by the live streaming query or rebuilt from scratch."""
    marked = mark_lateness(batch_df)
    on_time = normalize(
        marked.filter(F.col("_valid") & ~F.col("_late")).drop(
            "_valid", "_rejection_reason", "_late"
        )
    )
    late = normalize(
        marked.filter(F.col("_valid") & F.col("_late")).drop("_valid", "_rejection_reason")
    ).withColumn("dropped_reason", F.lit("late"))
    invalid = normalize(marked.filter(~F.col("_valid")).drop("_late", "_valid"))
    return on_time, late, invalid


def _write_batch(settings: Settings, event_type: str):
    def _inner(batch_df: DataFrame, batch_id: int) -> None:
        with track_batch_duration("silver", event_type):
            on_time, late, invalid = split_silver_batch(batch_df)

            # Each event type's query writes to its own base path
            # (`.../event_type=<X>`, partitioned only by `date`) rather than a
            # path shared across all 11 concurrent per-event-type queries
            # (previously `settings.silver_path` etc. directly, dynamically
            # partitioned by `event_type`). Spark's default rename-based
            # FileOutputCommitter stages writes under a `_temporary/<jobId>/...`
            # directory scoped to the *output path*, not the query — with 11
            # independent streaming queries committing concurrently to the same
            # output path, their `_temporary` staging collided, and S3A/MinIO
            # (rename = copy+delete, not atomic) surfaced this as a real
            # `RemoteFileChangedException` write failure that killed the query.
            # Caught running this for real against MinIO with real concurrent
            # traffic, not in unit tests, which use one query at a time. A
            # distinct base path per event type gives every query its own
            # non-shared `_temporary` directory — matches the read side's own
            # "read the specific event_type= subdirectory directly" pattern
            # (`read_bronze_stream_for_type`/`read_silver_stream`). `event_type`
            # is dropped before writing since it's now encoded in the path
            # itself, same as when it was a partition column; readers already
            # re-add it via `.withColumn("event_type", F.lit(event_type))`.
            on_time_count = on_time.count()
            if on_time_count > 0:
                on_time.drop("event_type").write.mode("append").partitionBy("date").parquet(
                    f"{settings.silver_path}/event_type={event_type}"
                )
            late_count = late.count()
            if late_count > 0:
                late.drop("event_type").write.mode("append").partitionBy("date").parquet(
                    f"{settings.late_events_path}/event_type={event_type}"
                )
            invalid_count = invalid.count()
            if invalid_count > 0:
                invalid.drop("event_type").write.mode("append").partitionBy("date").parquet(
                    f"{settings.silver_rejects_path}/event_type={event_type}"
                )

        record_rows(
            "silver",
            event_type,
            {"on_time": on_time_count, "late": late_count, "invalid": invalid_count},
        )
        logger.info(
            "silver batch %s (%s): %s on-time, %s late, %s rejected",
            batch_id,
            event_type,
            on_time_count,
            late_count,
            invalid_count,
        )

    return _inner


def build_type_query(
    spark: SparkSession,
    settings: Settings,
    event_type: str,
    *,
    schema_version: str = "1.0.0",
    trigger_once: bool = False,
) -> StreamingQuery:
    bronze_stream = read_bronze_stream_for_type(spark, settings, event_type)
    parsed = parse_and_flatten(bronze_stream, event_type, schema_version)
    validated = validate(parsed, event_type, schema_version)
    # Watermark declared on `ingested_at` (Bronze ingestion wall-clock time),
    # not the business `occurred_at_ts` column — deliberately, not the
    # original choice. `dropDuplicatesWithinWatermark` isn't just "ignore
    # duplicates that arrive after the watermark closes"; Spark's watermark
    # mechanism drops *any* row (duplicate or not) whose watermark column
    # value trails the query's already-advanced max-seen value by more than
    # `DEDUP_WATERMARK`, since that's what bounds the operator's state.
    # `occurred_at_ts` is a *business* timestamp that can legitimately jump
    # far ahead of real time for some event types (e.g. `order.shipped`'s
    # simulated shipping delay is up to 60 minutes after `order.created`,
    # `app.generator.generate_order_lifecycle`) — one high-latency shipment
    # advances the watermark far into the future, and a *subsequent*,
    # perfectly valid, non-duplicate `order.shipped` row with a smaller
    # `occurred_at_ts` (a lower-latency shipment processed later) then falls
    # behind that advanced watermark and is silently dropped by Spark
    # itself, never reaching `_write_batch` at all — not quarantined, not
    # counted late, just gone. Caught for real running the Phase 6 smoke
    # test (`scripts/phase6_smoke_test.sh`) against real Kafka/MinIO data at
    # real volume: `order.shipped` reconciled ~44% short in `app.dq.report`,
    # see DECISIONS.md. `ingested_at` (`F.current_timestamp()` at Bronze
    # write time) only ever moves forward with real processing time, so it
    # safely bounds dedup state without this failure mode. `mark_lateness`'s
    # own late-event classification (`ingested_at` - `occurred_at_ts`,
    # below) is unaffected — it already used `ingested_at` as its measure
    # of "the pipeline saw this late," which is exactly this bug's fix
    # generalized to the dedup watermark too.
    deduped = validated.withWatermark("ingested_at", DEDUP_WATERMARK).dropDuplicatesWithinWatermark(
        ["event_id"]
    )

    writer = (
        deduped.writeStream.foreachBatch(_write_batch(settings, event_type))
        .option("checkpointLocation", f"{settings.checkpoints_path}/silver/{event_type}")
        .outputMode("append")
    )
    writer = (
        writer.trigger(availableNow=True)
        if trigger_once
        else writer.trigger(processingTime="5 seconds")
    )
    return writer.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Silver: Bronze -> validated/deduped Parquet")
    parser.add_argument("--once", action="store_true", help="availableNow trigger, then stop.")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    start_metrics_server(settings.metrics_port)
    # `local[*]` (build_spark_session's default, per ADR 0005) matters more
    # here than for any other job in this package: this job runs 11
    # concurrent per-event-type queries (one per topic in ALL_TOPICS), and
    # even with `spark.scheduler.mode=FAIR` (see app.spark_session), too few
    # cores shared 11 ways starved individual queries of any scheduled time
    # at all under real load, not just slowed them down — caught running
    # this for real against MinIO with real traffic (unit tests only ever
    # run one query at a time, so they never exercise this).
    spark = build_spark_session("omniflow-silver", settings)

    queries = [
        build_type_query(spark, settings, event_type, trigger_once=args.once)
        for event_type in ALL_TOPICS
    ]
    logger.info(
        "silver: %s per-event-type streaming queries started (once=%s)", len(queries), args.once
    )
    for query in queries:
        query.awaitTermination()


if __name__ == "__main__":
    main()
