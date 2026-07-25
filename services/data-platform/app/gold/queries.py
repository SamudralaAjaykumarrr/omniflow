"""The ten Gold datasets from docs/data-pipeline.md's Gold table. Each
function is a pure transform (streaming or static Silver DataFrames in,
aggregated DataFrame out — flattened, not yet written) so it is unit
testable without Kafka/MinIO. `app.gold.runner` wires these to real Silver
streams and a Parquet sink; `app.lag_poller` produces the tenth (consumer
lag isn't event data, it's Kafka consumer-group offset metadata).

Two datasets deliberately differ from the original design table in
docs/data-pipeline.md because the *actual* Phase 2 event payloads
(`services/event-contracts/event_contracts/schemas.py`) don't carry the
field the table assumed:
- **Stockout frequency** groups by `sku` only, not `sku, node_id` —
  `InventoryRejectedReason` (the real `inventory.rejected` payload) never
  carried a `node_id` field; a rejection is evaluated across all candidate
  nodes, not attributed to one.
- **Product demand by window** groups by `sku` only, not `sku, node_hint` —
  `OrderItemData` (the real `order.created` payload) has no `node_hint`
  field.
Both are documented here and in docs/data-pipeline.md rather than silently
diverging from the spec.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from app.gold.common import flatten_window

DEFAULT_WATERMARK = "10 minutes"
# Ship time can lag order/assignment time by design (real fulfillment SLAs
# are hours-to-days) — joins and aggregations spanning that gap need a wider
# watermark than the single-event Gold datasets. See docs/data-pipeline.md.
FULFILLMENT_WATERMARK = "30 minutes"
MAX_FULFILLMENT_WINDOW = "7 days"


def orders_per_minute(order_created: DataFrame) -> DataFrame:
    agg = (
        order_created.withWatermark("occurred_at", DEFAULT_WATERMARK)
        .groupBy(F.window("occurred_at", "1 minute"))
        .agg(F.count("*").alias("order_count"))
    )
    return flatten_window(agg)


def revenue_by_product_location(order_created: DataFrame, order_shipped: DataFrame) -> DataFrame:
    created = order_created.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("c_order_id"),
        F.col("occurred_at").alias("c_occurred_at"),
        F.explode("items").alias("item"),
    )
    shipped = order_shipped.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("s_order_id"),
        F.col("occurred_at").alias("s_occurred_at"),
        F.col("node_id"),
    )
    joined = created.join(
        shipped,
        F.expr(
            f"""
            c_order_id = s_order_id AND
            s_occurred_at >= c_occurred_at AND
            s_occurred_at <= c_occurred_at + interval {MAX_FULFILLMENT_WINDOW}
            """
        ),
    )
    agg = joined.groupBy(
        F.window("s_occurred_at", "1 hour"),
        F.col("item.sku").alias("sku"),
        F.col("node_id"),
    ).agg(F.sum(F.col("item.qty") * F.col("item.unit_price")).alias("revenue"))
    return flatten_window(agg)


def fulfillment_success_rate(order_shipped: DataFrame, order_failed: DataFrame) -> DataFrame:
    shipped = order_shipped.select("occurred_at").withColumn("outcome", F.lit("shipped"))
    failed = order_failed.select("occurred_at").withColumn("outcome", F.lit("failed"))
    unioned = shipped.unionByName(failed).withWatermark("occurred_at", FULFILLMENT_WATERMARK)
    agg = unioned.groupBy(F.window("occurred_at", "1 hour")).agg(
        F.sum(F.when(F.col("outcome") == "shipped", 1).otherwise(0)).alias("shipped_count"),
        F.sum(F.when(F.col("outcome") == "failed", 1).otherwise(0)).alias("failed_count"),
    )
    agg = agg.withColumn(
        "success_rate",
        F.col("shipped_count")
        / F.greatest(F.col("shipped_count") + F.col("failed_count"), F.lit(1)),
    )
    return flatten_window(agg)


def fulfillment_latency(order_created: DataFrame, order_shipped: DataFrame) -> DataFrame:
    created = order_created.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("c_order_id"),
        F.col("occurred_at").alias("c_occurred_at"),
    )
    shipped = order_shipped.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("s_order_id"),
        F.col("occurred_at").alias("s_occurred_at"),
    )
    joined = created.join(
        shipped,
        F.expr(
            f"""
            c_order_id = s_order_id AND
            s_occurred_at >= c_occurred_at AND
            s_occurred_at <= c_occurred_at + interval {MAX_FULFILLMENT_WINDOW}
            """
        ),
    ).withColumn(
        "latency_seconds",
        F.col("s_occurred_at").cast("double") - F.col("c_occurred_at").cast("double"),
    )
    agg = joined.groupBy(F.window("s_occurred_at", "1 hour")).agg(
        F.avg("latency_seconds").alias("avg_latency_seconds"),
        F.count("*").alias("sample_count"),
    )
    return flatten_window(agg)


def inventory_reservation_failure_rate(
    inventory_reserved: DataFrame, inventory_rejected: DataFrame
) -> DataFrame:
    reserved = inventory_reserved.select("occurred_at").withColumn("outcome", F.lit("reserved"))
    rejected = inventory_rejected.select("occurred_at").withColumn("outcome", F.lit("rejected"))
    unioned = reserved.unionByName(rejected).withWatermark("occurred_at", DEFAULT_WATERMARK)
    agg = unioned.groupBy(F.window("occurred_at", "1 hour")).agg(
        F.sum(F.when(F.col("outcome") == "reserved", 1).otherwise(0)).alias("reserved_count"),
        F.sum(F.when(F.col("outcome") == "rejected", 1).otherwise(0)).alias("rejected_count"),
    )
    agg = agg.withColumn(
        "failure_rate",
        F.col("rejected_count")
        / F.greatest(F.col("reserved_count") + F.col("rejected_count"), F.lit(1)),
    )
    return flatten_window(agg)


def stockout_frequency(inventory_rejected: DataFrame) -> DataFrame:
    """Grouped by `sku` only — see module docstring: `inventory.rejected`'s
    real payload has no `node_id`."""
    exploded = inventory_rejected.withWatermark("occurred_at", DEFAULT_WATERMARK).select(
        "occurred_at", F.explode("reasons").alias("reason")
    )
    agg = exploded.groupBy(F.window("occurred_at", "1 hour"), F.col("reason.sku").alias("sku")).agg(
        F.count("*").alias("stockout_count")
    )
    return flatten_window(agg)


def late_order_rate(order_shipped: DataFrame, fulfillment_assigned: DataFrame) -> DataFrame:
    shipped = order_shipped.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("s_order_id"),
        F.col("occurred_at").alias("s_occurred_at"),
    )
    assigned = fulfillment_assigned.withWatermark("occurred_at", FULFILLMENT_WATERMARK).select(
        F.col("order_id").alias("a_order_id"),
        F.col("occurred_at").alias("a_occurred_at"),
        F.to_timestamp("estimated_ship_date").alias("estimated_ship_date"),
    )
    joined = shipped.join(
        assigned,
        F.expr(
            f"""
            s_order_id = a_order_id AND
            s_occurred_at >= a_occurred_at AND
            s_occurred_at <= a_occurred_at + interval {MAX_FULFILLMENT_WINDOW}
            """
        ),
    ).withColumn("is_late", F.col("s_occurred_at") > F.col("estimated_ship_date"))
    agg = joined.groupBy(F.window("s_occurred_at", "1 hour")).agg(
        F.count("*").alias("total_count"),
        F.sum(F.when(F.col("is_late"), 1).otherwise(0)).alias("late_count"),
    )
    agg = agg.withColumn(
        "late_rate", F.col("late_count") / F.greatest(F.col("total_count"), F.lit(1))
    )
    return flatten_window(agg)


def product_demand_by_window(order_created: DataFrame) -> DataFrame:
    """Grouped by `sku` only — see module docstring: `order.created`'s real
    item payload has no `node_hint`."""
    exploded = order_created.withWatermark("occurred_at", DEFAULT_WATERMARK).select(
        "occurred_at", F.explode("items").alias("item")
    )
    agg = exploded.groupBy(
        F.window("occurred_at", "15 minutes"), F.col("item.sku").alias("sku")
    ).agg(F.sum("item.qty").alias("qty_demanded"))
    return flatten_window(agg)


def dead_letter_volume(deadletter_event: DataFrame) -> DataFrame:
    enriched = deadletter_event.withWatermark("occurred_at", DEFAULT_WATERMARK).withColumn(
        "original_event_type", F.get_json_object("original_event", "$.event_type")
    )
    agg = enriched.groupBy(
        F.window("occurred_at", "1 hour"),
        F.col("original_event_type"),
        F.col("failed_consumer"),
    ).agg(F.count("*").alias("dead_letter_count"))
    return flatten_window(agg)
