"""Topic list for the data platform's Kafka reads — the same 11 topics
`infra/docker/redpanda/create-topics.sh` creates (docs/event-catalog.md)."""

from __future__ import annotations

from event_contracts.event_types import EventType

ALL_TOPICS: list[str] = [
    EventType.ORDER_CREATED,
    EventType.ORDER_VALIDATED,
    EventType.INVENTORY_RESERVATION_REQUESTED,
    EventType.INVENTORY_RESERVED,
    EventType.INVENTORY_REJECTED,
    EventType.FULFILLMENT_ASSIGNED,
    EventType.ORDER_SHIPPED,
    EventType.ORDER_CANCELLED,
    EventType.ORDER_FAILED,
    EventType.INVENTORY_LOW,
    EventType.DEADLETTER_EVENT,
]
