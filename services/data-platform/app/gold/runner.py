"""Gold — business-ready aggregations. One Spark driver, nine concurrent
streaming queries (the tenth Gold dataset, consumer lag, is produced by
`app.lag_poller` — it's Kafka consumer-group offset metadata, not event
data, so it doesn't fit the Silver-stream-in/aggregate-out shape the other
nine share). See docs/data-pipeline.md's Gold table.
"""

from __future__ import annotations

import argparse
import logging

from pyspark.sql import SparkSession
from pyspark.sql.streaming import StreamingQuery

from app.config import Settings, get_settings
from app.gold import queries
from app.gold.common import write_gold_stream
from app.silver_io import read_silver_stream
from app.spark_session import build_spark_session
from event_contracts.event_types import EventType

logger = logging.getLogger("data_platform.gold")


def start_all(
    spark: SparkSession, settings: Settings, *, trigger_once: bool = False
) -> list[StreamingQuery]:
    def silver(event_type: str):
        return read_silver_stream(spark, settings, event_type)

    datasets = {
        "orders_per_minute": (
            queries.orders_per_minute(silver(EventType.ORDER_CREATED)),
            ["date"],
        ),
        "revenue_by_product_location": (
            queries.revenue_by_product_location(
                silver(EventType.ORDER_CREATED), silver(EventType.ORDER_SHIPPED)
            ),
            ["date"],
        ),
        "fulfillment_success_rate": (
            queries.fulfillment_success_rate(
                silver(EventType.ORDER_SHIPPED), silver(EventType.ORDER_FAILED)
            ),
            ["date"],
        ),
        "fulfillment_latency": (
            queries.fulfillment_latency(
                silver(EventType.ORDER_CREATED), silver(EventType.ORDER_SHIPPED)
            ),
            ["date"],
        ),
        "inventory_reservation_failure_rate": (
            queries.inventory_reservation_failure_rate(
                silver(EventType.INVENTORY_RESERVED), silver(EventType.INVENTORY_REJECTED)
            ),
            ["date"],
        ),
        "stockout_frequency": (
            queries.stockout_frequency(silver(EventType.INVENTORY_REJECTED)),
            ["date"],
        ),
        "late_order_rate": (
            queries.late_order_rate(
                silver(EventType.ORDER_SHIPPED), silver(EventType.FULFILLMENT_ASSIGNED)
            ),
            ["date"],
        ),
        "product_demand_by_window": (
            queries.product_demand_by_window(silver(EventType.ORDER_CREATED)),
            ["date"],
        ),
        "dead_letter_volume": (
            queries.dead_letter_volume(silver(EventType.DEADLETTER_EVENT)),
            ["date"],
        ),
    }

    started = []
    for name, (df, partition_cols) in datasets.items():
        query = write_gold_stream(
            df, settings, name, partition_cols=partition_cols, trigger_once=trigger_once
        )
        logger.info("gold query started: %s", name)
        started.append(query)
    return started


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold: Silver -> business aggregations")
    parser.add_argument("--once", action="store_true", help="availableNow trigger, then stop.")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    # `local[*]` (the default, per ADR 0005) matters more here than for most
    # jobs in this package — this job runs 9 concurrent datasets; see
    # app.silver.main's comment for why that many concurrent queries need it.
    spark = build_spark_session("omniflow-gold", settings, shuffle_partitions=8)

    queries_started = start_all(spark, settings, trigger_once=args.once)
    logger.info("gold: %s streaming queries started (once=%s)", len(queries_started), args.once)
    for query in queries_started:
        query.awaitTermination()


if __name__ == "__main__":
    main()
