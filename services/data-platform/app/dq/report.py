"""Data-quality report: runs `app.dq.checks` against one date's real
Bronze/Silver/silver_rejects/late_events Parquet and writes a JSON report to
`s3a://<bucket>/dq-reports/date=<date>/report.json`.

Usage: `python -m app.dq.report [--date YYYY-MM-DD] [--no-fail-on-error]`
(date defaults to today, UTC). Exits non-zero if any gating check failed, so
this is safe to wire into a scheduler/CI step directly.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime

import s3fs
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.utils import AnalysisException

from app.bronze import read_bronze_batch
from app.config import Settings, get_settings
from app.dq.checks import run_all_checks
from app.s3 import s3_options
from app.spark_session import build_spark_session
from app.topics import ALL_TOPICS

logger = logging.getLogger("data_platform.dq")


def _read_layer_for_date(spark: SparkSession, path: str, date: str) -> DataFrame | None:
    """Reads `path` (partitioned by `event_type`/`date`) filtered to one
    date, or `None` if the path doesn't exist yet (nothing has been written
    there yet — e.g. `late_events` before any late row has ever occurred).
    Parquet is self-describing, so no explicit schema is needed for a batch
    read of files that already exist (unlike a streaming read, which needs
    one before any file may exist)."""
    try:
        df = spark.read.parquet(path)
    except AnalysisException:
        return None
    return df.filter(F.col("date") == date)


def _read_bronze_for_date(spark: SparkSession, settings: Settings, date: str) -> DataFrame | None:
    """Reads Bronze per `event_type=<X>` subdirectory (`app.bronze.read_bronze_batch`
    — the same access pattern `app.backfill` already uses) and unions the
    results, rather than a single `spark.read.parquet(settings.bronze_path)`
    against the Bronze *root*.

    Deliberately not `_read_layer_for_date(spark, settings.bronze_path, date)`:
    an environment that ever ran Bronze's original single `.writeStream
    .format("parquet")` writer (before Bronze moved to the same
    per-micro-batch `foreachBatch` + plain-write pattern Silver/Gold already
    used — see `app.bronze._write_batch`) has a `_spark_metadata` commit log
    sitting at the Bronze root from that writer. Spark's plain
    `spark.read.parquet(path)` auto-detects that log when it's present at
    `path` and silently scopes the read to *only* the files it recorded,
    hiding every file written since by a different mechanism (including
    every `foreachBatch` write from this pattern going forward) — hit for
    real running this for real against a MinIO volume with pre-existing
    Bronze data, see DECISIONS.md. Reading each `event_type=` subdirectory
    directly (never the root) sidesteps this entirely, matching how Silver/
    late_events/silver_rejects are already laid out (no shared root either)."""
    frames = []
    for event_type in ALL_TOPICS:
        try:
            frames.append(
                read_bronze_batch(spark, settings, event_type, from_date=date, to_date=date)
            )
        except AnalysisException:
            continue
    if not frames:
        return None
    result = frames[0]
    for frame in frames[1:]:
        result = result.unionByName(frame)
    return result


def build_report(spark: SparkSession, settings: Settings, date: str) -> dict:
    bronze = _read_bronze_for_date(spark, settings, date)
    silver = _read_layer_for_date(spark, settings.silver_path, date)
    rejects = _read_layer_for_date(spark, settings.silver_rejects_path, date)
    late = _read_layer_for_date(spark, settings.late_events_path, date)

    results = run_all_checks(
        bronze=bronze, silver=silver, rejects=rejects, late=late, now=datetime.now(UTC)
    )
    return {
        "date": date,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_passed": all(r.passed for r in results),
        "checks": [r.to_dict() for r in results],
    }


def write_report(settings: Settings, date: str, report: dict) -> str:
    fs = s3fs.S3FileSystem(**s3_options(settings))
    path = f"{settings.data_lake_bucket}/dq-reports/date={date}/report.json"
    with fs.open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    return f"s3a://{path}"


def print_summary(report: dict) -> None:
    print(
        f"DQ report for {report['date']} — overall: "
        f"{'PASS' if report['overall_passed'] else 'FAIL'}"
    )
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(
            f"  [{status}] {check['name']}: value={check['value']} threshold={check['threshold']}"
        )
        if check["details"]:
            print(f"           details={check['details']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run data-quality checks and write a report")
    parser.add_argument(
        "--date",
        default=datetime.now(UTC).date().isoformat(),
        help="Date partition to check (YYYY-MM-DD), default: today (UTC)",
    )
    parser.add_argument(
        "--no-fail-on-error",
        action="store_true",
        help="Exit 0 even if a gating check failed (report is still written).",
    )
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    spark = build_spark_session("omniflow-dq-report", settings)

    report = build_report(spark, settings, args.date)
    location = write_report(settings, args.date, report)
    print_summary(report)
    logger.info("dq report written to %s", location)

    if not report["overall_passed"] and not args.no_fail_on_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
