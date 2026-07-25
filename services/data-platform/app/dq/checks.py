"""Executable data-quality checks over one date's Bronze/Silver/rejects/
late-events Parquet.

Each check is a pure function over already-loaded DataFrames (or `None` when
that layer has no data at all for the requested date) — no I/O, no Spark
session wiring — so it is unit-testable with static DataFrames.
`app.dq.report` wires these to real S3A reads and turns the results into a
report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# A schema-invalid row is expected at some background rate (a producer bug,
# a hand-crafted bad message) but should never be the norm — see
# docs/data-pipeline.md's Silver validation step.
REJECT_RATE_THRESHOLD = 0.05

# Late events are an accepted, bounded limitation (docs/data-pipeline.md's
# "Watermarks and late data"), not zero-tolerance — but a rate this high
# would mean the pipeline is falling behind its producers, not just
# absorbing occasional redelivery/clock skew.
LATE_RATE_THRESHOLD = 0.10

# How stale the newest ingested row for the checked date is allowed to be
# before freshness fails — generous enough to tolerate the Spark
# micro-batch trigger interval (5-10s) plus normal container start-up
# jitter, not tuned to catch sub-minute lag (Prometheus/Grafana's real-time
# consumer-lag metric is the tool for that, per docs/data-pipeline.md's
# "Consumer lag and pipeline metrics" — this check is a coarser, historical
# safety net).
FRESHNESS_MAX_MINUTES = 60


@dataclass
class DQCheckResult:
    name: str
    passed: bool
    value: float | int | None
    threshold: float | int | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "value": self.value,
            "threshold": self.threshold,
            "details": self.details,
        }


def _count(df: DataFrame | None) -> int:
    return df.count() if df is not None else 0


def _counts_by_type(df: DataFrame | None, *, distinct_col: str | None = None) -> dict[str, int]:
    if df is None:
        return {}
    if distinct_col:
        grouped = df.groupBy("event_type").agg(F.countDistinct(distinct_col).alias("cnt"))
    else:
        grouped = df.groupBy("event_type").count().withColumnRenamed("count", "cnt")
    return {row["event_type"]: row["cnt"] for row in grouped.collect()}


def check_reconciliation(
    bronze: DataFrame | None,
    silver: DataFrame | None,
    rejects: DataFrame | None,
    late: DataFrame | None,
) -> DQCheckResult:
    """Bronze's distinct `event_id`s for this date should equal exactly the
    number of decisions Silver made about them (on-time + late + rejected) —
    every row Bronze carried was either written to Silver, quarantined, or
    flagged late; none silently vanished. Compared against *distinct*
    Bronze event_ids, not raw Bronze row count, because a duplicate
    redelivered within Silver's dedup watermark collapses to one decision by
    design (docs/data-pipeline.md's "Duplicate handling") — see
    `check_duplicate_rate` for that gap measured separately. Broken out per
    `event_type` so one type's mismatch (e.g. a schema bug) isn't averaged
    away by the others."""
    bronze_by_type = _counts_by_type(bronze, distinct_col="event_id")
    silver_by_type = _counts_by_type(silver)
    rejects_by_type = _counts_by_type(rejects)
    late_by_type = _counts_by_type(late)

    event_types = (
        set(bronze_by_type) | set(silver_by_type) | set(rejects_by_type) | set(late_by_type)
    )
    mismatches: dict[str, dict[str, int]] = {}
    total_diff = 0
    for event_type in event_types:
        bronze_n = bronze_by_type.get(event_type, 0)
        decided_n = (
            silver_by_type.get(event_type, 0)
            + rejects_by_type.get(event_type, 0)
            + late_by_type.get(event_type, 0)
        )
        diff = bronze_n - decided_n
        total_diff += diff
        if diff != 0:
            mismatches[event_type] = {"bronze_distinct": bronze_n, "silver_decided": decided_n}

    return DQCheckResult(
        name="bronze_silver_reconciliation",
        passed=total_diff == 0,
        value=total_diff,
        threshold=0,
        details={"mismatches_by_event_type": mismatches} if mismatches else {},
    )


def check_schema_rejection_rate(
    silver: DataFrame | None, rejects: DataFrame | None
) -> DQCheckResult:
    total = _count(silver) + _count(rejects)
    rate = (_count(rejects) / total) if total > 0 else 0.0
    return DQCheckResult(
        name="schema_rejection_rate",
        passed=rate <= REJECT_RATE_THRESHOLD,
        value=rate,
        threshold=REJECT_RATE_THRESHOLD,
        details={"rejected": _count(rejects), "total": total},
    )


def check_duplicate_rate(bronze: DataFrame | None) -> DQCheckResult:
    """Informational, not a pass/fail gate — at-least-once delivery means
    some rate of duplicate `event_id`s in Bronze is expected and correct
    (Bronze is the raw, undeduplicated record of what the bus actually
    carried), not a defect. Reported so it's visible, e.g. to sanity-check
    that Silver's dedup rate roughly tracks it."""
    total = _count(bronze)
    distinct = bronze.select("event_id").distinct().count() if bronze is not None else 0
    rate = ((total - distinct) / total) if total > 0 else 0.0
    return DQCheckResult(
        name="duplicate_rate",
        passed=True,
        value=rate,
        threshold=None,
        details={"total": total, "distinct_event_ids": distinct},
    )


def check_late_rate(silver: DataFrame | None, late: DataFrame | None) -> DQCheckResult:
    total = _count(silver) + _count(late)
    rate = (_count(late) / total) if total > 0 else 0.0
    return DQCheckResult(
        name="late_event_rate",
        passed=rate <= LATE_RATE_THRESHOLD,
        value=rate,
        threshold=LATE_RATE_THRESHOLD,
        details={"late": _count(late), "on_time_and_late_total": total},
    )


def check_freshness(bronze: DataFrame | None, *, now: datetime) -> DQCheckResult:
    if bronze is None or _count(bronze) == 0:
        return DQCheckResult(
            name="freshness",
            passed=False,
            value=None,
            threshold=FRESHNESS_MAX_MINUTES,
            details={"reason": "no_bronze_data_for_date"},
        )
    latest = bronze.agg(F.max("ingested_at").alias("m")).collect()[0]["m"]
    # Spark's TimestampType collects as a naive datetime under
    # spark.sql.session.timeZone=UTC (set by every SparkSession this
    # codebase builds) — it represents UTC wall-clock time but carries no
    # tzinfo, so it can't be subtracted from an aware `now` without this.
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    age_minutes = (now - latest).total_seconds() / 60
    return DQCheckResult(
        name="freshness",
        passed=age_minutes <= FRESHNESS_MAX_MINUTES,
        value=age_minutes,
        threshold=FRESHNESS_MAX_MINUTES,
        details={"latest_ingested_at": latest.isoformat()},
    )


def run_all_checks(
    *,
    bronze: DataFrame | None,
    silver: DataFrame | None,
    rejects: DataFrame | None,
    late: DataFrame | None,
    now: datetime,
) -> list[DQCheckResult]:
    return [
        check_reconciliation(bronze, silver, rejects, late),
        check_schema_rejection_rate(silver, rejects),
        check_duplicate_rate(bronze),
        check_late_rate(silver, late),
        check_freshness(bronze, now=now),
    ]
