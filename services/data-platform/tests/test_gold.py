from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.gold import queries
from event_contracts.event_types import EventType
from tests.helpers import make_silver_df

BASE_TIME = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def test_orders_per_minute_counts_within_the_window(spark):
    order_created = make_silver_df(
        spark,
        EventType.ORDER_CREATED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "customer_id": "c1",
                "items": [],
                "order_total": 1.0,
                "currency": "USD",
                "idempotency_key": "i1",
            },
            {
                "occurred_at": BASE_TIME + timedelta(seconds=10),
                "order_id": "o2",
                "customer_id": "c2",
                "items": [],
                "order_total": 1.0,
                "currency": "USD",
                "idempotency_key": "i2",
            },
            {
                "occurred_at": BASE_TIME + timedelta(minutes=5),
                "order_id": "o3",
                "customer_id": "c3",
                "items": [],
                "order_total": 1.0,
                "currency": "USD",
                "idempotency_key": "i3",
            },
        ],
    )

    result = queries.orders_per_minute(order_created).orderBy("window_start").collect()

    assert [r["order_count"] for r in result] == [2, 1]


def test_revenue_by_product_location_sums_qty_times_unit_price(spark):
    order_created = make_silver_df(
        spark,
        EventType.ORDER_CREATED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "customer_id": "c1",
                "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 10.0}],
                "order_total": 20.0,
                "currency": "USD",
                "idempotency_key": "i1",
            }
        ],
    )
    order_shipped = make_silver_df(
        spark,
        EventType.ORDER_SHIPPED,
        [
            {
                "occurred_at": BASE_TIME + timedelta(minutes=10),
                "order_id": "o1",
                "node_id": "node-1",
                "shipped_at": (BASE_TIME + timedelta(minutes=10)).isoformat(),
                "carrier_sim": "sim-ups",
                "tracking_ref": "trk-1",
            }
        ],
    )

    result = queries.revenue_by_product_location(order_created, order_shipped).collect()

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-1"
    assert result[0]["node_id"] == "node-1"
    assert result[0]["revenue"] == 20.0


def test_fulfillment_success_rate_combines_shipped_and_failed(spark):
    shipped = make_silver_df(
        spark,
        EventType.ORDER_SHIPPED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": f"o{i}",
                "node_id": "n1",
                "shipped_at": BASE_TIME.isoformat(),
                "carrier_sim": "sim-ups",
                "tracking_ref": f"t{i}",
            }
            for i in range(3)
        ],
    )
    failed = make_silver_df(
        spark,
        EventType.ORDER_FAILED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o4",
                "failed_step": "AUTHORIZE_PAYMENT",
                "reason": "decline",
                "compensations_applied": [],
            }
        ],
    )

    result = queries.fulfillment_success_rate(shipped, failed).collect()

    assert len(result) == 1
    row = result[0]
    assert row["shipped_count"] == 3
    assert row["failed_count"] == 1
    assert row["success_rate"] == 0.75


def test_fulfillment_latency_averages_seconds_between_created_and_shipped(spark):
    created = make_silver_df(
        spark,
        EventType.ORDER_CREATED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "customer_id": "c1",
                "items": [],
                "order_total": 1.0,
                "currency": "USD",
                "idempotency_key": "i1",
            }
        ],
    )
    shipped = make_silver_df(
        spark,
        EventType.ORDER_SHIPPED,
        [
            {
                "occurred_at": BASE_TIME + timedelta(minutes=30),
                "order_id": "o1",
                "node_id": "n1",
                "shipped_at": (BASE_TIME + timedelta(minutes=30)).isoformat(),
                "carrier_sim": "sim-ups",
                "tracking_ref": "t1",
            }
        ],
    )

    result = queries.fulfillment_latency(created, shipped).collect()

    assert len(result) == 1
    assert result[0]["avg_latency_seconds"] == 1800.0
    assert result[0]["sample_count"] == 1


def test_inventory_reservation_failure_rate_computes_ratio(spark):
    reserved = make_silver_df(
        spark,
        EventType.INVENTORY_RESERVED,
        [{"occurred_at": BASE_TIME, "order_id": "o1", "reservations": []}],
    )
    rejected = make_silver_df(
        spark,
        EventType.INVENTORY_REJECTED,
        [
            {"occurred_at": BASE_TIME, "order_id": "o2", "reasons": []},
            {"occurred_at": BASE_TIME, "order_id": "o3", "reasons": []},
        ],
    )

    result = queries.inventory_reservation_failure_rate(reserved, rejected).collect()

    assert len(result) == 1
    row = result[0]
    assert row["reserved_count"] == 1
    assert row["rejected_count"] == 2
    assert row["failure_rate"] == pytest.approx(2 / 3)


def test_stockout_frequency_groups_by_sku(spark):
    rejected = make_silver_df(
        spark,
        EventType.INVENTORY_REJECTED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "reasons": [{"sku": "SKU-1", "requested_qty": 2, "available_qty": 0}],
            },
            {
                "occurred_at": BASE_TIME,
                "order_id": "o2",
                "reasons": [
                    {"sku": "SKU-1", "requested_qty": 1, "available_qty": 0},
                    {"sku": "SKU-2", "requested_qty": 1, "available_qty": 0},
                ],
            },
        ],
    )

    result = {r["sku"]: r["stockout_count"] for r in queries.stockout_frequency(rejected).collect()}

    assert result == {"SKU-1": 2, "SKU-2": 1}


def test_late_order_rate_flags_shipments_after_estimate(spark):
    shipped = make_silver_df(
        spark,
        EventType.ORDER_SHIPPED,
        [
            {
                "occurred_at": BASE_TIME + timedelta(minutes=30),
                "order_id": "o1",
                "node_id": "n1",
                "shipped_at": "",
                "carrier_sim": "sim-ups",
                "tracking_ref": "t1",
            },
            {
                "occurred_at": BASE_TIME + timedelta(minutes=35),
                "order_id": "o2",
                "node_id": "n1",
                "shipped_at": "",
                "carrier_sim": "sim-ups",
                "tracking_ref": "t2",
            },
        ],
    )
    score_breakdown = {
        "stock": 1.0,
        "distance": 1.0,
        "capacity": 1.0,
        "delivery_estimate": 1.0,
        "backlog": 1.0,
    }
    assigned = make_silver_df(
        spark,
        EventType.FULFILLMENT_ASSIGNED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "node_id": "n1",
                "score": 0.9,
                "score_breakdown": score_breakdown,
                "estimated_ship_date": (BASE_TIME + timedelta(minutes=10)).isoformat(),
            },
            {
                "occurred_at": BASE_TIME,
                "order_id": "o2",
                "node_id": "n1",
                "score": 0.9,
                "score_breakdown": score_breakdown,
                "estimated_ship_date": (BASE_TIME + timedelta(hours=2)).isoformat(),
            },
        ],
    )

    result = queries.late_order_rate(shipped, assigned).collect()

    assert len(result) == 1
    row = result[0]
    assert row["total_count"] == 2
    assert row["late_count"] == 1
    assert row["late_rate"] == 0.5


def test_product_demand_by_window_sums_qty_per_sku(spark):
    order_created = make_silver_df(
        spark,
        EventType.ORDER_CREATED,
        [
            {
                "occurred_at": BASE_TIME,
                "order_id": "o1",
                "customer_id": "c1",
                "items": [{"sku": "SKU-1", "qty": 3, "unit_price": 5.0}],
                "order_total": 15.0,
                "currency": "USD",
                "idempotency_key": "i1",
            },
            {
                "occurred_at": BASE_TIME + timedelta(minutes=5),
                "order_id": "o2",
                "customer_id": "c2",
                "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 5.0}],
                "order_total": 10.0,
                "currency": "USD",
                "idempotency_key": "i2",
            },
        ],
    )

    result = queries.product_demand_by_window(order_created).collect()

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-1"
    assert result[0]["qty_demanded"] == 5


def test_dead_letter_volume_groups_by_original_type_and_consumer(spark):
    deadletter = make_silver_df(
        spark,
        EventType.DEADLETTER_EVENT,
        [
            {
                "occurred_at": BASE_TIME,
                "original_event": json.dumps({"event_type": "order.created"}),
                "failed_consumer": "order-service-validator",
                "error_type": "ValueError",
                "error_message": "boom",
                "attempt_count": 5,
                "first_failed_at": BASE_TIME.isoformat(),
                "last_failed_at": BASE_TIME.isoformat(),
            },
            {
                "occurred_at": BASE_TIME + timedelta(minutes=1),
                "original_event": json.dumps({"event_type": "order.created"}),
                "failed_consumer": "order-service-validator",
                "error_type": "ValueError",
                "error_message": "boom again",
                "attempt_count": 5,
                "first_failed_at": BASE_TIME.isoformat(),
                "last_failed_at": BASE_TIME.isoformat(),
            },
        ],
    )

    result = queries.dead_letter_volume(deadletter).collect()

    assert len(result) == 1
    row = result[0]
    assert row["original_event_type"] == "order.created"
    assert row["failed_consumer"] == "order-service-validator"
    assert row["dead_letter_count"] == 2
