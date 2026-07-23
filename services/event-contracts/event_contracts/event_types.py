"""Event type string constants — one authoritative spelling per event.

Kept as plain string constants (not an Enum) so they serialize directly as
the `event_type` field and the Kafka topic name without an extra `.value`.
"""


class EventType:
    ORDER_CREATED = "order.created"
    ORDER_VALIDATED = "order.validated"
    INVENTORY_RESERVATION_REQUESTED = "inventory.reservation.requested"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_REJECTED = "inventory.rejected"
    FULFILLMENT_ASSIGNED = "fulfillment.assigned"
    ORDER_SHIPPED = "order.shipped"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_FAILED = "order.failed"
    INVENTORY_LOW = "inventory.low"
    DEADLETTER_EVENT = "deadletter.event"
