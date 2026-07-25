from __future__ import annotations

import pytest

from app.backfill import _date_range, _gold_builders
from app.config import get_settings


def test_date_range_single_day():
    assert _date_range("2026-07-01", "2026-07-01") == ["2026-07-01"]


def test_date_range_multi_day_inclusive():
    assert _date_range("2026-07-01", "2026-07-03") == ["2026-07-01", "2026-07-02", "2026-07-03"]


def test_date_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        _date_range("2026-07-03", "2026-07-01")


def test_gold_builders_cover_every_streaming_gold_dataset(spark):
    """`app.gold.runner.start_all` streams 9 datasets live; `app.backfill`
    must be able to reprocess every one of them from Silver in batch mode,
    or a live bug in one couldn't ever be backfilled. Only inspects the
    builder dict's keys — the lambdas themselves are lazy and never
    invoked here, so this needs no real Silver data."""
    builders = _gold_builders(spark, get_settings(), "2026-07-01", "2026-07-01")

    assert set(builders) == {
        "orders_per_minute",
        "revenue_by_product_location",
        "fulfillment_success_rate",
        "fulfillment_latency",
        "inventory_reservation_failure_rate",
        "stockout_frequency",
        "late_order_rate",
        "product_demand_by_window",
        "dead_letter_volume",
    }
