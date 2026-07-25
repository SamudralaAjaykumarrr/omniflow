"""Spark schemas mirroring `event_contracts.envelope`/`event_contracts.schemas`
(docs/event-catalog.md is the authoritative contract both mirror).

Bronze keeps `data` loosely typed (raw JSON string) per the schema-evolution
strategy in docs/data-pipeline.md — a new/renamed field in a producer's
payload never breaks Bronze ingestion. Silver is where each event type's
payload gets a real, versioned, typed schema.
"""

from __future__ import annotations

from pyspark.sql.types import (
    ArrayType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from event_contracts.event_types import EventType

# --- Bronze -----------------------------------------------------------------

TRACE_CONTEXT_SCHEMA = StructType(
    [
        StructField("traceparent", StringType(), nullable=True),
    ]
)

# The envelope fields Kafka's JSON value parses into, *excluding* `data`
# (extracted separately via get_json_object so a malformed/unknown payload
# shape never breaks parsing of the envelope itself).
ENVELOPE_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), nullable=True),
        StructField("event_type", StringType(), nullable=True),
        StructField("schema_version", StringType(), nullable=True),
        StructField("occurred_at", StringType(), nullable=True),
        StructField("producer", StringType(), nullable=True),
        StructField("correlation_id", StringType(), nullable=True),
        StructField("causation_id", StringType(), nullable=True),
        StructField("trace_context", TRACE_CONTEXT_SCHEMA, nullable=True),
    ]
)

BRONZE_COLUMNS = [
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "producer",
    "correlation_id",
    "causation_id",
    "traceparent",
    "data_json",
    "kafka_topic",
    "kafka_partition",
    "kafka_offset",
    "kafka_timestamp",
    "ingested_at",
    "date",
]

# The physical, non-partition-column schema of a Bronze Parquet file — i.e.
# `BRONZE_COLUMNS` minus `event_type` and `date`, which `partitionBy` strips
# from the data files themselves and encodes only in the directory path
# (`event_type=.../date=.../`). Used to read a specific `event_type=`
# subdirectory back as a stream (see `app.silver.read_bronze_stream_for_type`)
# with `date` recovered via Spark's own partition-directory discovery and
# `event_type` re-added as a literal (the caller already knows it, since
# they chose which subdirectory to read).
BRONZE_TABLE_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), nullable=True),
        StructField("schema_version", StringType(), nullable=True),
        StructField("occurred_at", StringType(), nullable=True),
        StructField("producer", StringType(), nullable=True),
        StructField("correlation_id", StringType(), nullable=True),
        StructField("causation_id", StringType(), nullable=True),
        StructField("traceparent", StringType(), nullable=True),
        StructField("data_json", StringType(), nullable=True),
        StructField("kafka_topic", StringType(), nullable=True),
        StructField("kafka_partition", IntegerType(), nullable=True),
        StructField("kafka_offset", LongType(), nullable=True),
        StructField("kafka_timestamp", TimestampType(), nullable=True),
        StructField("ingested_at", TimestampType(), nullable=True),
    ]
)

# --- Silver per-event-type payload schemas -----------------------------------

ORDER_ITEM_SCHEMA = StructType(
    [
        StructField("sku", StringType(), nullable=True),
        StructField("qty", LongType(), nullable=True),
        StructField("unit_price", DoubleType(), nullable=True),
    ]
)

ORDER_CREATED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("customer_id", StringType(), nullable=True),
        StructField("items", ArrayType(ORDER_ITEM_SCHEMA), nullable=True),
        StructField("order_total", DoubleType(), nullable=True),
        StructField("currency", StringType(), nullable=True),
        StructField("idempotency_key", StringType(), nullable=True),
    ]
)

ORDER_VALIDATED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("validated_at", StringType(), nullable=True),
    ]
)

SKU_QTY_SCHEMA = StructType(
    [
        StructField("sku", StringType(), nullable=True),
        StructField("qty", LongType(), nullable=True),
    ]
)

INVENTORY_RESERVATION_REQUESTED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("items", ArrayType(SKU_QTY_SCHEMA), nullable=True),
        StructField("candidate_node_ids", ArrayType(StringType()), nullable=True),
    ]
)

RESERVATION_ENTRY_SCHEMA = StructType(
    [
        StructField("sku", StringType(), nullable=True),
        StructField("node_id", StringType(), nullable=True),
        StructField("qty", LongType(), nullable=True),
        StructField("reservation_id", StringType(), nullable=True),
        StructField("expires_at", StringType(), nullable=True),
    ]
)

INVENTORY_RESERVED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("reservations", ArrayType(RESERVATION_ENTRY_SCHEMA), nullable=True),
    ]
)

REJECTED_REASON_SCHEMA = StructType(
    [
        StructField("sku", StringType(), nullable=True),
        StructField("requested_qty", LongType(), nullable=True),
        StructField("available_qty", LongType(), nullable=True),
    ]
)

INVENTORY_REJECTED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("reasons", ArrayType(REJECTED_REASON_SCHEMA), nullable=True),
    ]
)

SCORE_BREAKDOWN_SCHEMA = StructType(
    [
        StructField("stock", DoubleType(), nullable=True),
        StructField("distance", DoubleType(), nullable=True),
        StructField("capacity", DoubleType(), nullable=True),
        StructField("delivery_estimate", DoubleType(), nullable=True),
        StructField("backlog", DoubleType(), nullable=True),
    ]
)

FULFILLMENT_ASSIGNED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("node_id", StringType(), nullable=True),
        StructField("score", DoubleType(), nullable=True),
        StructField("score_breakdown", SCORE_BREAKDOWN_SCHEMA, nullable=True),
        StructField("estimated_ship_date", StringType(), nullable=True),
    ]
)

ORDER_SHIPPED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("node_id", StringType(), nullable=True),
        StructField("shipped_at", StringType(), nullable=True),
        StructField("carrier_sim", StringType(), nullable=True),
        StructField("tracking_ref", StringType(), nullable=True),
    ]
)

ORDER_CANCELLED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("cancelled_by", StringType(), nullable=True),
        StructField("reason", StringType(), nullable=True),
        StructField("previous_state", StringType(), nullable=True),
    ]
)

ORDER_FAILED_V1 = StructType(
    [
        StructField("order_id", StringType(), nullable=True),
        StructField("failed_step", StringType(), nullable=True),
        StructField("reason", StringType(), nullable=True),
        StructField("compensations_applied", ArrayType(StringType()), nullable=True),
    ]
)

INVENTORY_LOW_V1 = StructType(
    [
        StructField("sku", StringType(), nullable=True),
        StructField("node_id", StringType(), nullable=True),
        StructField("available_qty", LongType(), nullable=True),
        StructField("threshold", LongType(), nullable=True),
        StructField("evaluated_at", StringType(), nullable=True),
    ]
)

# `original_event` is a full nested envelope+payload of arbitrary shape —
# kept as a raw JSON string, same loose-typing rule Bronze applies to `data`.
# The real producers publish it as a JSON *object*
# (`event_contracts.schemas.DeadLetterEventDataV1.original_event: dict`), so
# `app.silver.parse_and_flatten` extracts it via `get_json_object` rather
# than relying on `from_json` against this StringType field directly (which
# would null it out for an object-shaped JSON node) — see that function's
# docstring for the full explanation.
DEADLETTER_EVENT_V1 = StructType(
    [
        StructField("original_event", StringType(), nullable=True),
        StructField("failed_consumer", StringType(), nullable=True),
        StructField("error_type", StringType(), nullable=True),
        StructField("error_message", StringType(), nullable=True),
        StructField("attempt_count", LongType(), nullable=True),
        StructField("first_failed_at", StringType(), nullable=True),
        StructField("last_failed_at", StringType(), nullable=True),
    ]
)

# Keyed exactly like event_contracts.schemas.SCHEMA_REGISTRY: (event_type,
# schema_version) -> Spark StructType for that payload. A new schema_version
# gets its own entry (additive), never mutates an existing one in place —
# see "Schema evolution strategy" in docs/data-pipeline.md.
SILVER_SCHEMA_REGISTRY: dict[tuple[str, str], StructType] = {
    (EventType.ORDER_CREATED, "1.0.0"): ORDER_CREATED_V1,
    (EventType.ORDER_VALIDATED, "1.0.0"): ORDER_VALIDATED_V1,
    (EventType.INVENTORY_RESERVATION_REQUESTED, "1.0.0"): INVENTORY_RESERVATION_REQUESTED_V1,
    (EventType.INVENTORY_RESERVED, "1.0.0"): INVENTORY_RESERVED_V1,
    (EventType.INVENTORY_REJECTED, "1.0.0"): INVENTORY_REJECTED_V1,
    (EventType.FULFILLMENT_ASSIGNED, "1.0.0"): FULFILLMENT_ASSIGNED_V1,
    (EventType.ORDER_SHIPPED, "1.0.0"): ORDER_SHIPPED_V1,
    (EventType.ORDER_CANCELLED, "1.0.0"): ORDER_CANCELLED_V1,
    (EventType.ORDER_FAILED, "1.0.0"): ORDER_FAILED_V1,
    (EventType.INVENTORY_LOW, "1.0.0"): INVENTORY_LOW_V1,
    (EventType.DEADLETTER_EVENT, "1.0.0"): DEADLETTER_EVENT_V1,
}

# The business key(s) a Silver row for this event type must have non-null to
# be considered structurally valid, beyond generic envelope checks — used by
# both Silver validation and the DQ "missing IDs" check.
REQUIRED_DATA_FIELDS: dict[str, list[str]] = {
    EventType.ORDER_CREATED: ["order_id", "customer_id"],
    EventType.ORDER_VALIDATED: ["order_id"],
    EventType.INVENTORY_RESERVATION_REQUESTED: ["order_id"],
    EventType.INVENTORY_RESERVED: ["order_id"],
    EventType.INVENTORY_REJECTED: ["order_id"],
    EventType.FULFILLMENT_ASSIGNED: ["order_id", "node_id"],
    EventType.ORDER_SHIPPED: ["order_id", "node_id"],
    EventType.ORDER_CANCELLED: ["order_id"],
    EventType.ORDER_FAILED: ["order_id"],
    EventType.INVENTORY_LOW: ["sku", "node_id"],
    EventType.DEADLETTER_EVENT: ["failed_consumer"],
}
