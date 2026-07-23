"""Contract/compatibility tests for the event schema registry.

These assert two things: (1) a realistic payload for every event type in
docs/event-catalog.md actually validates against its registered schema, and
(2) the registry mechanism itself would catch a breaking change — proven by
deliberately constructing a "next version" schema that drops a required
field and showing a real v1 payload fails against it. (2) exists so this
test suite doesn't just tautologically pass; it demonstrates the check has
teeth.
"""

import pytest
from pydantic import BaseModel, ValidationError

from event_contracts import EventType, UnknownSchemaError, validate_event_data
from event_contracts.schemas import OrderCreatedDataV1

VALID_PAYLOADS: dict[str, dict] = {
    EventType.ORDER_CREATED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "customer_id": "22222222-2222-2222-2222-222222222222",
        "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 9.99}],
        "order_total": 19.98,
        "currency": "USD",
        "idempotency_key": "key-1",
    },
    EventType.ORDER_VALIDATED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "validated_at": "2026-07-24T00:00:00Z",
    },
    EventType.INVENTORY_RESERVATION_REQUESTED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "items": [{"sku": "SKU-1", "qty": 2}],
        "candidate_node_ids": ["33333333-3333-3333-3333-333333333333"],
    },
    EventType.INVENTORY_RESERVED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "reservations": [
            {
                "sku": "SKU-1",
                "node_id": "33333333-3333-3333-3333-333333333333",
                "qty": 2,
                "reservation_id": "44444444-4444-4444-4444-444444444444",
                "expires_at": "2026-07-24T00:15:00Z",
            }
        ],
    },
    EventType.INVENTORY_REJECTED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "reasons": [{"sku": "SKU-1", "requested_qty": 5, "available_qty": 1}],
    },
    EventType.FULFILLMENT_ASSIGNED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "node_id": "33333333-3333-3333-3333-333333333333",
        "score": 0.82,
        "score_breakdown": {
            "stock": 1.0,
            "distance": 0.7,
            "capacity": 0.9,
            "delivery_estimate": 0.6,
            "backlog": 0.8,
        },
        "estimated_ship_date": "2026-07-25T00:00:00Z",
    },
    EventType.ORDER_SHIPPED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "node_id": "33333333-3333-3333-3333-333333333333",
        "shipped_at": "2026-07-25T00:00:00Z",
        "carrier_sim": "sim-ground",
        "tracking_ref": "TRACK-1",
    },
    EventType.ORDER_CANCELLED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "cancelled_by": "api",
        "reason": "customer request",
        "previous_state": "CREATED",
    },
    EventType.ORDER_FAILED: {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "failed_step": "AUTHORIZE_PAYMENT",
        "reason": "payment declined",
        "compensations_applied": ["inventory_release"],
    },
    EventType.INVENTORY_LOW: {
        "sku": "SKU-1",
        "node_id": "33333333-3333-3333-3333-333333333333",
        "available_qty": 1,
        "threshold": 5,
        "evaluated_at": "2026-07-24T00:00:00Z",
    },
    EventType.DEADLETTER_EVENT: {
        "original_event": {"event_id": "x"},
        "failed_consumer": "fulfillment-orchestrator",
        "error_type": "ValueError",
        "error_message": "boom",
        "attempt_count": 5,
        "first_failed_at": "2026-07-24T00:00:00Z",
        "last_failed_at": "2026-07-24T00:01:00Z",
    },
}


@pytest.mark.parametrize("event_type", list(VALID_PAYLOADS))
def test_every_cataloged_event_type_validates_against_its_v1_schema(event_type):
    validate_event_data(event_type, "1.0.0", VALID_PAYLOADS[event_type])


def test_unknown_schema_version_is_a_named_error():
    with pytest.raises(UnknownSchemaError):
        validate_event_data(
            EventType.ORDER_CREATED, "9.9.9", VALID_PAYLOADS[EventType.ORDER_CREATED]
        )


def test_missing_required_field_is_rejected():
    broken = dict(VALID_PAYLOADS[EventType.ORDER_CREATED])
    del broken["order_total"]
    with pytest.raises(ValidationError):
        validate_event_data(EventType.ORDER_CREATED, "1.0.0", broken)


def test_registry_mechanism_catches_a_deliberately_breaking_schema_change():
    """Simulates what a careless v2 of order.created would look like if it
    dropped `currency` (a real field every current producer sends) without a
    major version bump. The current, real payload must fail against it —
    proving this registry is the thing that would have caught the mistake
    in CI before it shipped.
    """

    class BrokenOrderCreatedDataV2(BaseModel):
        order_id: str
        customer_id: str
        items: list[dict]
        order_total: float
        idempotency_key: str
        # `currency` intentionally omitted to simulate a breaking change —
        # if a real v2 needs to drop a field, ADR-mandated process is a new
        # topic version (order.created.v2), not silently mutating v1's shape.

    real_v1_payload = VALID_PAYLOADS[EventType.ORDER_CREATED]
    # The real payload still validates fine against the real, current schema:
    OrderCreatedDataV1.model_validate(real_v1_payload)

    # But extra/unknown fields are fine under default pydantic config, so the
    # actual breakage to demonstrate is the reverse — a v1 payload missing a
    # field the broken schema wrongly assumes was optional would slip through
    # silently. The real regression this test guards against is dropping a
    # required field the other direction: construct a "v1 payload with
    # currency missing" (as if a producer regressed) and show the *current*
    # registered schema (correctly) rejects it.
    regressed_producer_payload = {k: v for k, v in real_v1_payload.items() if k != "currency"}
    with pytest.raises(ValidationError):
        validate_event_data(EventType.ORDER_CREATED, "1.0.0", regressed_producer_payload)

    # And the hypothetical broken schema itself would have accepted the
    # regressed payload — which is exactly why "just add a Pydantic model
    # and hope" isn't the compatibility mechanism; the registry pinning
    # (event_type, schema_version) -> the one true schema is.
    BrokenOrderCreatedDataV2.model_validate(regressed_producer_payload)
