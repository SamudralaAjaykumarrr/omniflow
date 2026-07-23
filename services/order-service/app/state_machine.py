"""Order state machine.

Required states and transitions per docs/architecture.md / docs/data-model.md.
Cancellation is only a simple state flip through FULFILLMENT_ASSIGNED — once
an order enters PROCESSING (simulated payment captured), cancelling it would
require a refund/compensation flow, which is out of scope for a simple
transition and is instead handled by the saga's own compensation path
(Phase 2), not this state machine.
"""

from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    INVENTORY_PENDING = "INVENTORY_PENDING"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    FULFILLMENT_ASSIGNED = "FULFILLMENT_ASSIGNED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


TERMINAL_STATES: set[OrderStatus] = {
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.FAILED,
}

CANCELLABLE_STATES: set[OrderStatus] = {
    OrderStatus.CREATED,
    OrderStatus.VALIDATED,
    OrderStatus.INVENTORY_PENDING,
    OrderStatus.INVENTORY_RESERVED,
    OrderStatus.FULFILLMENT_ASSIGNED,
}

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.VALIDATED, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.VALIDATED: {
        OrderStatus.INVENTORY_PENDING,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.INVENTORY_PENDING: {
        OrderStatus.INVENTORY_RESERVED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.INVENTORY_RESERVED: {
        OrderStatus.FULFILLMENT_ASSIGNED,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.FULFILLMENT_ASSIGNED: {
        OrderStatus.PROCESSING,
        OrderStatus.CANCELLED,
        OrderStatus.FAILED,
    },
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.FAILED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.FAILED: set(),
}


class InvalidTransitionError(Exception):
    def __init__(self, from_status: OrderStatus, to_status: OrderStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"cannot transition order from {from_status} to {to_status}")


def assert_valid_transition(from_status: OrderStatus, to_status: OrderStatus) -> None:
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise InvalidTransitionError(from_status, to_status)
