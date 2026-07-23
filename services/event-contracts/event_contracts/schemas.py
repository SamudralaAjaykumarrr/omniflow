"""Per-event-type `data` payload schemas, keyed by (event_type, schema_version).

This is the enforcement mechanism behind docs/event-catalog.md's compatibility
rule: a producer's actual payload is validated against its declared schema in
CI (see tests/test_contracts.py), so a breaking change to a payload shape is
caught here, not discovered later by a consumer crashing in production.
"""

from __future__ import annotations

from pydantic import BaseModel

from event_contracts.event_types import EventType


class OrderItemData(BaseModel):
    sku: str
    qty: int
    unit_price: float


class OrderCreatedDataV1(BaseModel):
    order_id: str
    customer_id: str
    items: list[OrderItemData]
    order_total: float
    currency: str
    idempotency_key: str


class OrderValidatedDataV1(BaseModel):
    order_id: str
    validated_at: str


class InventoryReservationRequestedDataV1(BaseModel):
    order_id: str
    items: list[dict]
    candidate_node_ids: list[str]


class InventoryReservationEntry(BaseModel):
    sku: str
    node_id: str
    qty: int
    reservation_id: str
    expires_at: str


class InventoryReservedDataV1(BaseModel):
    order_id: str
    reservations: list[InventoryReservationEntry]


class InventoryRejectedReason(BaseModel):
    sku: str
    requested_qty: int
    available_qty: int


class InventoryRejectedDataV1(BaseModel):
    order_id: str
    reasons: list[InventoryRejectedReason]


class ScoreBreakdown(BaseModel):
    stock: float
    distance: float
    capacity: float
    delivery_estimate: float
    backlog: float


class FulfillmentAssignedDataV1(BaseModel):
    order_id: str
    node_id: str
    score: float
    score_breakdown: ScoreBreakdown
    estimated_ship_date: str


class OrderShippedDataV1(BaseModel):
    order_id: str
    node_id: str
    shipped_at: str
    carrier_sim: str
    tracking_ref: str


class OrderCancelledDataV1(BaseModel):
    order_id: str
    cancelled_by: str
    reason: str
    previous_state: str


class OrderFailedDataV1(BaseModel):
    order_id: str
    failed_step: str
    reason: str
    compensations_applied: list[str]


class InventoryLowDataV1(BaseModel):
    sku: str
    node_id: str
    available_qty: int
    threshold: int
    evaluated_at: str


class DeadLetterEventDataV1(BaseModel):
    original_event: dict
    failed_consumer: str
    error_type: str
    error_message: str
    attempt_count: int
    first_failed_at: str
    last_failed_at: str


SCHEMA_REGISTRY: dict[tuple[str, str], type[BaseModel]] = {
    (EventType.ORDER_CREATED, "1.0.0"): OrderCreatedDataV1,
    (EventType.ORDER_VALIDATED, "1.0.0"): OrderValidatedDataV1,
    (EventType.INVENTORY_RESERVATION_REQUESTED, "1.0.0"): InventoryReservationRequestedDataV1,
    (EventType.INVENTORY_RESERVED, "1.0.0"): InventoryReservedDataV1,
    (EventType.INVENTORY_REJECTED, "1.0.0"): InventoryRejectedDataV1,
    (EventType.FULFILLMENT_ASSIGNED, "1.0.0"): FulfillmentAssignedDataV1,
    (EventType.ORDER_SHIPPED, "1.0.0"): OrderShippedDataV1,
    (EventType.ORDER_CANCELLED, "1.0.0"): OrderCancelledDataV1,
    (EventType.ORDER_FAILED, "1.0.0"): OrderFailedDataV1,
    (EventType.INVENTORY_LOW, "1.0.0"): InventoryLowDataV1,
    (EventType.DEADLETTER_EVENT, "1.0.0"): DeadLetterEventDataV1,
}


class UnknownSchemaError(Exception):
    def __init__(self, event_type: str, schema_version: str) -> None:
        super().__init__(f"no registered schema for {event_type!r} v{schema_version}")


def validate_event_data(event_type: str, schema_version: str, data: dict) -> BaseModel:
    """Validate `data` against its registered schema; raises pydantic's
    ValidationError on a real mismatch, or UnknownSchemaError if the
    (event_type, schema_version) pair was never registered."""
    model = SCHEMA_REGISTRY.get((event_type, schema_version))
    if model is None:
        raise UnknownSchemaError(event_type, schema_version)
    return model.model_validate(data)
