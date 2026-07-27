"""Kafka helpers for the scenarios that need to publish directly onto real
(or failure-lab-owned) topics rather than going through a service's REST
API. Every envelope published here that lands on a *real* domain-event topic
uses a synthetic order_id that never corresponds to a real order-service
row — the same safe, already-accepted pattern the Phase 4 synthetic
generator uses against these same topics (RISKS.md #17): real consumers
handle "order not found" as a clean no-op, not a crash.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from confluent_kafka import Producer

from event_contracts import EventEnvelope, EventType, build_producer, publish_envelope, utc_now

__all__ = [
    "build_producer",
    "publish_late_order_shipped_envelope",
    "publish_malformed_record",
    "publish_order_created_envelope",
]


def publish_order_created_envelope(
    producer: Producer, *, correlation_id: str, envelope: EventEnvelope | None = None
) -> EventEnvelope:
    """Publish (or republish, if `envelope` is given) a synthetic
    `order.created` envelope. Passing the same `envelope` back in a second
    time is exactly what a duplicate delivery looks like on the wire: same
    event_id, same everything."""
    if envelope is None:
        order_id = str(uuid.uuid4())
        envelope = EventEnvelope(
            event_type=EventType.ORDER_CREATED,
            producer="failure-lab",
            correlation_id=correlation_id,
            data={
                "order_id": order_id,
                "customer_id": str(uuid.uuid4()),
                "items": [{"sku": "FAILURE-LAB-SYNTHETIC-SKU", "qty": 1, "unit_price": 1.0}],
                "order_total": 1.0,
                "currency": "USD",
                "idempotency_key": f"failure-lab-synthetic-{order_id}",
            },
        )
    publish_envelope(
        producer, topic=EventType.ORDER_CREATED, key=envelope.data["order_id"], envelope=envelope
    )
    return envelope


def publish_late_order_shipped_envelope(
    producer: Producer, *, correlation_id: str, lateness: timedelta
) -> EventEnvelope:
    """Publish a well-formed `order.shipped` envelope whose business
    `occurred_at` trails real time by `lateness` — no transactional consumer
    subscribes to `order.shipped` (only order-service's validator consumes
    `order.created`, only fulfillment-orchestrator's saga consumer consumes
    `order.validated`/`order.cancelled`), so this is only ever observed by
    the data platform's Bronze/Silver layers."""
    order_id = str(uuid.uuid4())
    occurred_at = utc_now() - lateness
    envelope = EventEnvelope(
        event_type=EventType.ORDER_SHIPPED,
        producer="failure-lab",
        correlation_id=correlation_id,
        occurred_at=occurred_at,
        data={
            "order_id": order_id,
            "node_id": str(uuid.uuid4()),
            "shipped_at": occurred_at.isoformat(),
            "carrier_sim": "sim-ground",
            "tracking_ref": f"FAILURE-LAB-{order_id}",
        },
    )
    publish_envelope(producer, topic=EventType.ORDER_SHIPPED, key=order_id, envelope=envelope)
    return envelope


def publish_malformed_record(producer: Producer, *, topic: str, key: str, raw_bytes: bytes) -> None:
    """Publish raw, deliberately non-envelope-shaped bytes directly onto
    `topic` — bypasses `publish_envelope` entirely (which requires a valid
    `EventEnvelope`). `topic` must be a real event-catalog topic with zero
    transactional consumers (see docs/phase-8-failure-laboratory.md
    "Isolation of chaos topics") so only Bronze's malformed-JSON quarantine
    ever has to deal with this, never a business consumer.
    """
    delivery_errors: list[str] = []

    def _on_delivery(err, _msg) -> None:
        if err is not None:
            delivery_errors.append(str(err))

    producer.produce(topic, key=key.encode("utf-8"), value=raw_bytes, on_delivery=_on_delivery)
    still_queued = producer.flush(timeout=10.0)
    if still_queued > 0:
        raise RuntimeError(f"malformed record publish to {topic} timed out before delivery")
    if delivery_errors:
        raise RuntimeError(f"malformed record publish to {topic} failed: {delivery_errors[0]}")
