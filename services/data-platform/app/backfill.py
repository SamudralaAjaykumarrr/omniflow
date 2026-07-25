"""Backfill and reprocessing tooling — batch re-runs of Silver (from Bronze)
or Gold (from Silver) over a bounded date range, per docs/data-pipeline.md's
"Backfill process"/"Reprocessing process": always scoped to a date range,
written to a side path (`<path>_backfill/...`), row-count-validated, then
swapped into the live path. Because Bronze/Silver are immutable and
partitioned by date, this is always "replay this date range," never "replay
everything."

Swap is a best-effort per-file rename via s3fs — MinIO/S3 have no atomic
"replace this directory" primitive, so this is a documented limitation, not
silently assumed atomic: a crash mid-swap can leave a partial mix of
old/new files for the affected date range. It is safely re-runnable:
reprocessing overwrites (not appends) the side path, and swapping again
re-copies every affected file.

Usage:
  python -m app.backfill silver --event-type order.created \
      --from-date 2026-07-01 --to-date 2026-07-02 [--apply]
  python -m app.backfill gold --dataset orders_per_minute \
      --from-date 2026-07-01 --to-date 2026-07-02 [--apply]

Without `--apply`, this only writes the side path and reports row counts —
the live path is never touched. `--apply` additionally swaps the validated
side-path output into the live path for the given date range. Restarting
the affected streaming query (Silver or Gold) from a checkpoint pointing
past the backfilled range is a separate, deliberate operational step (see
docs/data-pipeline.md) — not automated here, since it means stopping and
restarting a running container.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import s3fs
from pyspark.sql import DataFrame, SparkSession

from app.bronze import read_bronze_batch
from app.config import Settings, get_settings
from app.gold import queries
from app.s3 import boto3_client, s3_options
from app.silver import parse_and_flatten, split_silver_batch, validate
from app.silver_io import read_silver_batch
from app.spark_session import build_spark_session
from event_contracts.event_types import EventType

logger = logging.getLogger("data_platform.backfill")


class RowCountMismatchError(Exception):
    pass


def _date_range(from_date: str, to_date: str) -> list[str]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if end < start:
        raise ValueError(f"from-date {from_date} is after to-date {to_date}")
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def reprocess_silver(
    spark: SparkSession,
    settings: Settings,
    event_type: str,
    *,
    from_date: str,
    to_date: str,
    schema_version: str = "1.0.0",
) -> dict[str, int]:
    """Batch-reruns Bronze -> Silver for one event type over
    `[from_date, to_date]`, writing on-time/late/rejected rows to side
    paths. Validates that every distinct Bronze `event_id` in range was
    accounted for (on-time + late + rejected) before writing anything —
    raises `RowCountMismatchError` rather than silently swapping a
    inconsistent result. Does not touch the live path; see
    `apply_silver_backfill`."""
    bronze = read_bronze_batch(spark, settings, event_type, from_date=from_date, to_date=to_date)
    parsed = parse_and_flatten(bronze, event_type, schema_version)
    validated = validate(parsed, event_type, schema_version)
    deduped = validated.dropDuplicates(["event_id"])
    on_time, late, invalid = split_silver_batch(deduped)

    counts = {
        "bronze_distinct_event_ids": bronze.select("event_id").distinct().count(),
        "on_time": on_time.count(),
        "late": late.count(),
        "rejected": invalid.count(),
    }
    decided = counts["on_time"] + counts["late"] + counts["rejected"]
    if decided != counts["bronze_distinct_event_ids"]:
        raise RowCountMismatchError(
            f"{event_type} {from_date}..{to_date}: bronze distinct event_ids="
            f"{counts['bronze_distinct_event_ids']} != decided={decided} "
            f"(on_time={counts['on_time']}, late={counts['late']}, rejected={counts['rejected']})"
        )

    # Distinct base path per event type, same reasoning as
    # `app.silver._write_batch`: keeps this safely re-runnable/parallelizable
    # across event types against S3A/MinIO's non-atomic rename, and matches
    # the exact `.../event_type=<X>/date=<Y>/` shape `apply_silver_backfill`
    # already expects on both sides of the swap.
    if counts["on_time"] > 0:
        on_time.drop("event_type").write.mode("overwrite").partitionBy("date").parquet(
            f"{settings.silver_path}_backfill/event_type={event_type}"
        )
    if counts["late"] > 0:
        late.drop("event_type").write.mode("overwrite").partitionBy("date").parquet(
            f"{settings.late_events_path}_backfill/event_type={event_type}"
        )
    if counts["rejected"] > 0:
        invalid.drop("event_type").write.mode("overwrite").partitionBy("date").parquet(
            f"{settings.silver_rejects_path}_backfill/event_type={event_type}"
        )
    logger.info("silver reprocess (%s, %s..%s): %s", event_type, from_date, to_date, counts)
    return counts


def _swap_partition(
    fs: s3fs.S3FileSystem, s3_client, backfill_prefix: str, live_prefix: str
) -> int:
    """Deletes every object currently under `live_prefix`, then copies every
    object from `backfill_prefix` into it and deletes the `backfill_prefix`
    original. Not atomic across the whole prefix — see module docstring.

    Every delete goes through `s3_client.delete_object` (boto3, one call
    per key), never `fs.rm`/`fs.mv` — both always go through S3's bulk
    `DeleteObjects` API even for a single path (`fs.mv` copies, then
    internally calls `fs.rm` on the source), which this MinIO version
    rejects (`MissingContentMD5`) — a real S3-compatibility gap hit running
    this for real, not a hypothetical. See `app.s3.boto3_client`."""
    bucket = live_prefix.split("/", 1)[0]

    def delete(path: str) -> None:
        s3_client.delete_object(Bucket=bucket, Key=path.split("/", 1)[1])

    if fs.exists(live_prefix):
        for existing in fs.find(live_prefix):
            delete(existing)
    if not fs.exists(backfill_prefix):
        return 0
    moved = 0
    for path in fs.find(backfill_prefix):
        rel = path[len(backfill_prefix) :].lstrip("/")
        fs.copy(path, f"{live_prefix.rstrip('/')}/{rel}")
        delete(path)
        moved += 1
    return moved


def apply_silver_backfill(
    settings: Settings, event_type: str, from_date: str, to_date: str
) -> dict[str, int]:
    fs = s3fs.S3FileSystem(**s3_options(settings))
    s3_client = boto3_client(settings)
    swapped: dict[str, int] = {}
    for layer, live_path in [
        ("silver", settings.silver_path),
        ("late_events", settings.late_events_path),
        ("silver_rejects", settings.silver_rejects_path),
    ]:
        live_root = live_path.removeprefix("s3a://")
        backfill_root = f"{live_root}_backfill"
        total = 0
        for day in _date_range(from_date, to_date):
            live_prefix = f"{live_root}/event_type={event_type}/date={day}"
            backfill_prefix = f"{backfill_root}/event_type={event_type}/date={day}"
            total += _swap_partition(fs, s3_client, backfill_prefix, live_prefix)
        swapped[layer] = total
    return swapped


def _gold_builders(spark: SparkSession, settings: Settings, from_date: str, to_date: str):
    def batch(event_type: str) -> DataFrame:
        return read_silver_batch(spark, settings, event_type, from_date=from_date, to_date=to_date)

    return {
        "orders_per_minute": lambda: queries.orders_per_minute(batch(EventType.ORDER_CREATED)),
        "revenue_by_product_location": lambda: queries.revenue_by_product_location(
            batch(EventType.ORDER_CREATED), batch(EventType.ORDER_SHIPPED)
        ),
        "fulfillment_success_rate": lambda: queries.fulfillment_success_rate(
            batch(EventType.ORDER_SHIPPED), batch(EventType.ORDER_FAILED)
        ),
        "fulfillment_latency": lambda: queries.fulfillment_latency(
            batch(EventType.ORDER_CREATED), batch(EventType.ORDER_SHIPPED)
        ),
        "inventory_reservation_failure_rate": lambda: queries.inventory_reservation_failure_rate(
            batch(EventType.INVENTORY_RESERVED), batch(EventType.INVENTORY_REJECTED)
        ),
        "stockout_frequency": lambda: queries.stockout_frequency(
            batch(EventType.INVENTORY_REJECTED)
        ),
        "late_order_rate": lambda: queries.late_order_rate(
            batch(EventType.ORDER_SHIPPED), batch(EventType.FULFILLMENT_ASSIGNED)
        ),
        "product_demand_by_window": lambda: queries.product_demand_by_window(
            batch(EventType.ORDER_CREATED)
        ),
        "dead_letter_volume": lambda: queries.dead_letter_volume(batch(EventType.DEADLETTER_EVENT)),
    }


def reprocess_gold(
    spark: SparkSession, settings: Settings, dataset: str, *, from_date: str, to_date: str
) -> int:
    """Batch-reruns one Gold dataset's aggregation over Silver for
    `[from_date, to_date]`, writing to a side path. The same
    `app.gold.queries` functions the live streaming queries use — a
    watermark/window declared on a batch (non-streaming) DataFrame is a
    documented Spark no-op, not an error, so the aggregation logic itself is
    identical between streaming and batch."""
    builders = _gold_builders(spark, settings, from_date, to_date)
    if dataset not in builders:
        raise ValueError(f"unknown gold dataset {dataset!r} (known: {sorted(builders)})")

    df = builders[dataset]()
    row_count = df.count()
    df.write.mode("overwrite").partitionBy("date").parquet(
        f"{settings.gold_path}_backfill/{dataset}"
    )
    logger.info("gold reprocess (%s, %s..%s): %s row(s)", dataset, from_date, to_date, row_count)
    return row_count


def apply_gold_backfill(settings: Settings, dataset: str, from_date: str, to_date: str) -> int:
    fs = s3fs.S3FileSystem(**s3_options(settings))
    s3_client = boto3_client(settings)
    live_root = f"{settings.gold_path}/{dataset}".removeprefix("s3a://")
    backfill_root = f"{settings.gold_path}_backfill/{dataset}".removeprefix("s3a://")
    total = 0
    for day in _date_range(from_date, to_date):
        total += _swap_partition(
            fs, s3_client, f"{backfill_root}/date={day}", f"{live_root}/date={day}"
        )
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill/reprocess Silver (from Bronze) or Gold (from Silver)"
    )
    sub = parser.add_subparsers(dest="layer", required=True)

    silver_parser = sub.add_parser("silver", help="Reprocess Bronze -> Silver for one event type")
    silver_parser.add_argument("--event-type", required=True)
    silver_parser.add_argument("--from-date", required=True)
    silver_parser.add_argument("--to-date", required=True)
    silver_parser.add_argument(
        "--apply", action="store_true", help="Swap into the live path (default: side-path only)"
    )

    gold_parser = sub.add_parser("gold", help="Reprocess Silver -> one Gold dataset")
    gold_parser.add_argument("--dataset", required=True)
    gold_parser.add_argument("--from-date", required=True)
    gold_parser.add_argument("--to-date", required=True)
    gold_parser.add_argument(
        "--apply", action="store_true", help="Swap into the live path (default: side-path only)"
    )

    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    spark = build_spark_session(f"omniflow-backfill-{args.layer}", settings)

    if args.layer == "silver":
        counts = reprocess_silver(
            spark, settings, args.event_type, from_date=args.from_date, to_date=args.to_date
        )
        print(f"silver reprocess counts: {counts}")
        if args.apply:
            swapped = apply_silver_backfill(settings, args.event_type, args.from_date, args.to_date)
            print(f"swapped into live path: {swapped}")
        else:
            print("dry-run only (pass --apply to swap into the live path)")
    else:
        row_count = reprocess_gold(
            spark, settings, args.dataset, from_date=args.from_date, to_date=args.to_date
        )
        print(f"gold reprocess row count: {row_count}")
        if args.apply:
            swapped_count = apply_gold_backfill(
                settings, args.dataset, args.from_date, args.to_date
            )
            print(f"swapped {swapped_count} file(s) into live path")
        else:
            print("dry-run only (pass --apply to swap into the live path)")


if __name__ == "__main__":
    main()
