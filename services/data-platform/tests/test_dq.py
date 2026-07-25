from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pyspark.sql.types import DateType, StringType, StructField, StructType, TimestampType

from app.dq.checks import (
    check_duplicate_rate,
    check_freshness,
    check_late_rate,
    check_reconciliation,
    check_schema_rejection_rate,
    run_all_checks,
)
from app.dq.report import _read_layer_for_date

_TYPE_ID_SCHEMA = StructType(
    [StructField("event_type", StringType()), StructField("event_id", StringType())]
)


def _df(spark, rows):
    return spark.createDataFrame(rows, schema=_TYPE_ID_SCHEMA)


def test_check_reconciliation_passes_when_every_bronze_id_is_accounted_for(spark):
    bronze = _df(spark, [("order.created", "e1"), ("order.created", "e2")])
    silver = _df(spark, [("order.created", "e1")])
    rejects = _df(spark, [("order.created", "e2")])
    late = _df(spark, [])

    result = check_reconciliation(bronze, silver, rejects, late)

    assert result.passed is True
    assert result.value == 0


def test_check_reconciliation_flags_mismatch_by_event_type(spark):
    bronze = _df(spark, [("order.created", "e1"), ("order.created", "e2")])
    silver = _df(spark, [("order.created", "e1")])  # e2 was never decided
    rejects = _df(spark, [])
    late = _df(spark, [])

    result = check_reconciliation(bronze, silver, rejects, late)

    assert result.passed is False
    assert result.value == 1
    assert "order.created" in result.details["mismatches_by_event_type"]


def test_check_reconciliation_collapses_duplicate_bronze_event_ids(spark):
    """A redelivered event_id counted twice in Bronze should still
    reconcile to one Silver decision — dedup, not data loss."""
    bronze = _df(spark, [("order.created", "e1"), ("order.created", "e1")])
    silver = _df(spark, [("order.created", "e1")])
    rejects = _df(spark, [])
    late = _df(spark, [])

    result = check_reconciliation(bronze, silver, rejects, late)

    assert result.passed is True


def test_check_schema_rejection_rate_flags_high_reject_rate(spark):
    silver = _df(spark, [("order.created", "e1")])
    rejects = _df(spark, [("order.created", f"e{i}") for i in range(2, 12)])

    result = check_schema_rejection_rate(silver, rejects)

    assert result.value == pytest.approx(10 / 11)
    assert result.passed is False


def test_check_duplicate_rate_is_informational_only(spark):
    bronze = _df(spark, [("order.created", "e1"), ("order.created", "e1"), ("order.created", "e2")])

    result = check_duplicate_rate(bronze)

    assert result.passed is True  # never gates, even with duplicates present
    assert result.value == pytest.approx(1 / 3)
    assert result.details == {"total": 3, "distinct_event_ids": 2}


def test_check_late_rate_flags_high_late_rate(spark):
    silver = _df(spark, [("order.created", "e1")])
    late = _df(spark, [("order.created", f"e{i}") for i in range(2, 6)])

    result = check_late_rate(silver, late)

    assert result.passed is False
    assert result.value == 0.8


def test_check_freshness_fails_when_no_bronze_data():
    result = check_freshness(None, now=datetime.now(UTC))
    assert result.passed is False
    assert result.details["reason"] == "no_bronze_data_for_date"


def test_check_freshness_passes_for_recently_ingested_data(spark):
    schema = StructType([StructField("ingested_at", TimestampType())])
    now = datetime.now(UTC)
    bronze = spark.createDataFrame([(now - timedelta(minutes=1),)], schema=schema)

    result = check_freshness(bronze, now=now)

    assert result.passed is True


def test_check_freshness_fails_when_stale(spark):
    schema = StructType([StructField("ingested_at", TimestampType())])
    now = datetime.now(UTC)
    bronze = spark.createDataFrame([(now - timedelta(hours=3),)], schema=schema)

    result = check_freshness(bronze, now=now)

    assert result.passed is False


def test_run_all_checks_returns_all_five_results(spark):
    now = datetime.now(UTC)
    bronze_schema = StructType(
        [
            StructField("event_type", StringType()),
            StructField("event_id", StringType()),
            StructField("ingested_at", TimestampType()),
        ]
    )
    bronze = spark.createDataFrame([("order.created", "e1", now)], schema=bronze_schema)
    silver = _df(spark, [("order.created", "e1")])

    results = run_all_checks(bronze=bronze, silver=silver, rejects=None, late=None, now=now)

    assert {r.name for r in results} == {
        "bronze_silver_reconciliation",
        "schema_rejection_rate",
        "duplicate_rate",
        "late_event_rate",
        "freshness",
    }


def test_read_layer_for_date_returns_none_for_missing_path(spark, tmp_path):
    missing_path = str(tmp_path / "does-not-exist")
    assert _read_layer_for_date(spark, missing_path, "2026-07-01") is None


def test_read_layer_for_date_filters_to_requested_date(spark, tmp_path):
    schema = StructType([StructField("event_type", StringType()), StructField("date", DateType())])
    df = spark.createDataFrame(
        [("order.created", date(2026, 7, 1)), ("order.created", date(2026, 7, 2))], schema=schema
    )
    path = str(tmp_path / "layer")
    df.write.partitionBy("date").parquet(path)

    result = _read_layer_for_date(spark, path, "2026-07-01")

    assert result is not None
    assert result.count() == 1
    assert result.collect()[0]["date"].isoformat() == "2026-07-01"
