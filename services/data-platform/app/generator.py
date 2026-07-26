"""Synthetic event generator — produces a realistic stream of the 11
event-catalog event types directly onto Kafka, for exercising the data
platform (Bronze/Silver/Gold) with real, schema-valid traffic without
needing a live order to move through the full order-service/inventory-
service/fulfillment-orchestrator saga for every test run.

Each synthetic "order" is a coherent, causally-chained sequence of events
(one shared `correlation_id`, each event's `causation_id` pointing at the
one before it), built and validated against `event_contracts.schemas`'
`SCHEMA_REGISTRY` before publish — the same contract every real producer in
this system is held to (`services/event-contracts/tests/test_contracts.py`).

Also injects a configurable rate of duplicate redelivery (republishes an
already-sent envelope unchanged, same `event_id`), late arrival (backdates
`occurred_at` past Silver's late-event threshold before publish), and
malformed records (raw, intentionally-broken bytes published directly,
bypassing schema validation) so a single generator run can exercise
Silver's dedup/late-event paths and Bronze's malformed-JSON quarantine
(`app.bronze.transform_to_bronze_rejects`) end-to-end with real
Kafka/Parquet, not just in isolated unit tests against hand-built
DataFrames.
"""

from __future__ import annotations

import argparse
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from event_contracts.envelope import EventEnvelope
from event_contracts.event_types import EventType
from event_contracts.kafka import build_producer, publish_envelope
from event_contracts.schemas import validate_event_data

logger = logging.getLogger("data_platform.generator")

PRODUCER_NAME = "synthetic-generator"
SCHEMA_VERSION = "1.0.0"

SKUS = [f"SKU-GEN-{i:03d}" for i in range(1, 21)]
NODE_IDS = [str(uuid.uuid4()) for _ in range(3)]

# Matches app.silver.LATE_THRESHOLD_SECONDS — an event backdated by more
# than this, relative to when it's actually published/ingested, is what
# Silver routes to late_events.
LATE_THRESHOLD_SECONDS = 600


def _envelope(
    event_type: str,
    data: dict,
    *,
    correlation_id: str,
    causation_id: str | None,
    occurred_at: datetime,
) -> EventEnvelope:
    validate_event_data(event_type, SCHEMA_VERSION, data)
    return EventEnvelope(
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        producer=PRODUCER_NAME,
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred_at,
        data=data,
    )


def _order_items() -> list[dict]:
    chosen = random.sample(SKUS, random.randint(1, 3))
    return [
        {"sku": sku, "qty": random.randint(1, 5), "unit_price": round(random.uniform(5, 200), 2)}
        for sku in chosen
    ]


def generate_order_lifecycle(*, now: datetime) -> list[EventEnvelope]:
    """One synthetic order's full causal chain of events, timestamps
    advancing realistically (seconds-to-minutes apart, matching real
    saga-step latency) rather than all sharing one identical timestamp."""
    order_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())
    items = _order_items()
    order_total = round(sum(i["qty"] * i["unit_price"] for i in items), 2)
    node_id = random.choice(NODE_IDS)

    t = now
    events: list[EventEnvelope] = []

    created = _envelope(
        EventType.ORDER_CREATED,
        {
            "order_id": order_id,
            "customer_id": customer_id,
            "items": items,
            "order_total": order_total,
            "currency": "USD",
            "idempotency_key": idempotency_key,
        },
        correlation_id=correlation_id,
        causation_id=None,
        occurred_at=t,
    )
    events.append(created)

    t += timedelta(seconds=random.uniform(1, 5))
    validated = _envelope(
        EventType.ORDER_VALIDATED,
        {"order_id": order_id, "validated_at": t.isoformat()},
        correlation_id=correlation_id,
        causation_id=created.event_id,
        occurred_at=t,
    )
    events.append(validated)

    t += timedelta(seconds=random.uniform(1, 5))
    reservation_requested = _envelope(
        EventType.INVENTORY_RESERVATION_REQUESTED,
        {
            "order_id": order_id,
            "items": [{"sku": i["sku"], "qty": i["qty"]} for i in items],
            "candidate_node_ids": NODE_IDS,
        },
        correlation_id=correlation_id,
        causation_id=validated.event_id,
        occurred_at=t,
    )
    events.append(reservation_requested)

    t += timedelta(seconds=random.uniform(1, 5))
    if random.random() > 0.1:  # 90% of synthetic orders have stock available
        reserved = _envelope(
            EventType.INVENTORY_RESERVED,
            {
                "order_id": order_id,
                "reservations": [
                    {
                        "sku": i["sku"],
                        "node_id": node_id,
                        "qty": i["qty"],
                        "reservation_id": str(uuid.uuid4()),
                        "expires_at": (t + timedelta(minutes=30)).isoformat(),
                    }
                    for i in items
                ],
            },
            correlation_id=correlation_id,
            causation_id=reservation_requested.event_id,
            occurred_at=t,
        )
        events.append(reserved)

        t += timedelta(seconds=random.uniform(1, 10))
        assigned = _envelope(
            EventType.FULFILLMENT_ASSIGNED,
            {
                "order_id": order_id,
                "node_id": node_id,
                "score": round(random.uniform(0.5, 1.0), 4),
                "score_breakdown": {
                    "stock": round(random.uniform(0, 1), 4),
                    "distance": round(random.uniform(0, 1), 4),
                    "capacity": round(random.uniform(0, 1), 4),
                    "delivery_estimate": round(random.uniform(0, 1), 4),
                    "backlog": round(random.uniform(0, 1), 4),
                },
                "estimated_ship_date": (t + timedelta(days=2)).isoformat(),
            },
            correlation_id=correlation_id,
            causation_id=reserved.event_id,
            occurred_at=t,
        )
        events.append(assigned)

        t += timedelta(minutes=random.uniform(1, 60))
        if random.random() > 0.05:  # 5% synthetic payment failures
            shipped = _envelope(
                EventType.ORDER_SHIPPED,
                {
                    "order_id": order_id,
                    "node_id": node_id,
                    "shipped_at": t.isoformat(),
                    "carrier_sim": random.choice(["sim-ups", "sim-fedex", "sim-usps"]),
                    "tracking_ref": str(uuid.uuid4()),
                },
                correlation_id=correlation_id,
                causation_id=assigned.event_id,
                occurred_at=t,
            )
            events.append(shipped)
        else:
            failed = _envelope(
                EventType.ORDER_FAILED,
                {
                    "order_id": order_id,
                    "failed_step": "AUTHORIZE_PAYMENT",
                    "reason": "synthetic_payment_decline",
                    "compensations_applied": ["release_reservation"],
                },
                correlation_id=correlation_id,
                causation_id=assigned.event_id,
                occurred_at=t,
            )
            events.append(failed)
    else:
        rejected = _envelope(
            EventType.INVENTORY_REJECTED,
            {
                "order_id": order_id,
                "reasons": [
                    {"sku": i["sku"], "requested_qty": i["qty"], "available_qty": 0} for i in items
                ],
            },
            correlation_id=correlation_id,
            causation_id=reservation_requested.event_id,
            occurred_at=t,
        )
        events.append(rejected)

        t += timedelta(seconds=random.uniform(1, 5))
        failed = _envelope(
            EventType.ORDER_FAILED,
            {
                "order_id": order_id,
                "failed_step": "SELECT_AND_RESERVE",
                "reason": "no_node_had_stock",
                "compensations_applied": [],
            },
            correlation_id=correlation_id,
            causation_id=rejected.event_id,
            occurred_at=t,
        )
        events.append(failed)

    if random.random() < 0.05:
        events.append(
            _envelope(
                EventType.INVENTORY_LOW,
                {
                    "sku": random.choice(SKUS),
                    "node_id": node_id,
                    "available_qty": random.randint(0, 3),
                    "threshold": 5,
                    "evaluated_at": t.isoformat(),
                },
                correlation_id=correlation_id,
                causation_id=None,
                occurred_at=t,
            )
        )

    return events


def generate_dead_letter(*, now: datetime, original: EventEnvelope) -> EventEnvelope:
    return _envelope(
        EventType.DEADLETTER_EVENT,
        {
            "original_event": original.model_dump(mode="json"),
            "failed_consumer": "synthetic-generator",
            "error_type": "SyntheticFailure",
            "error_message": "synthetic dead-letter for pipeline testing",
            "attempt_count": 5,
            "first_failed_at": now.isoformat(),
            "last_failed_at": now.isoformat(),
        },
        correlation_id=original.correlation_id,
        causation_id=original.event_id,
        occurred_at=now,
    )


def inject_anomalies(
    events: list[EventEnvelope], *, duplicate_rate: float, late_rate: float, now: datetime
) -> list[EventEnvelope]:
    """Returns a new list, same order otherwise: some events are backdated
    past Silver's late threshold, and some are additionally republished a
    second time unchanged (real at-least-once redelivery, same `event_id`)."""
    output: list[EventEnvelope] = []
    for event in events:
        if random.random() < late_rate:
            event = event.model_copy(
                update={
                    "occurred_at": now
                    - timedelta(seconds=LATE_THRESHOLD_SECONDS + random.uniform(60, 600))
                }
            )
        output.append(event)
        if random.random() < duplicate_rate:
            output.append(event.model_copy())
    return output


def publish_malformed(producer, topic: str) -> None:
    """Publishes an intentionally-broken raw payload directly to `topic`,
    bypassing `publish_envelope`'s schema validation entirely — simulates a
    poison message from a misbehaving/foreign producer. Exercises Bronze's
    malformed-JSON quarantine (`app.bronze.transform_to_bronze_rejects`)
    end-to-end against real Kafka/Parquet."""
    delivery_errors: list[str] = []

    def _on_delivery(err, _msg) -> None:
        if err is not None:
            delivery_errors.append(str(err))

    producer.produce(
        topic,
        key=str(uuid.uuid4()).encode("utf-8"),
        value=b"{not-valid-json::synthetic-malformed-record",
        on_delivery=_on_delivery,
    )
    still_queued = producer.flush(timeout=10.0)
    if still_queued > 0 or delivery_errors:
        logger.warning(
            "synthetic malformed record to %s did not confirm delivery: still_queued=%s errors=%s",
            topic,
            still_queued,
            delivery_errors,
        )


def run(
    *,
    order_count: int,
    dead_letter_count: int,
    duplicate_rate: float,
    late_rate: float,
    malformed_rate: float = 0.0,
    kafka_bootstrap_servers: str,
) -> int:
    producer = build_producer(kafka_bootstrap_servers)
    now = datetime.now(UTC)

    all_events: list[EventEnvelope] = []
    for _ in range(order_count):
        all_events.extend(generate_order_lifecycle(now=now))
    for _ in range(dead_letter_count):
        all_events.append(generate_dead_letter(now=now, original=random.choice(all_events)))

    all_events = inject_anomalies(
        all_events, duplicate_rate=duplicate_rate, late_rate=late_rate, now=now
    )

    published = 0
    malformed_published = 0
    for event in all_events:
        key = str(event.data.get("order_id", event.event_id))
        publish_envelope(producer, topic=event.event_type, key=key, envelope=event)
        published += 1
        if random.random() < malformed_rate:
            publish_malformed(producer, topic=event.event_type)
            malformed_published += 1
    logger.info(
        "published %s synthetic event(s) across %s topic(s), %s malformed record(s)",
        published,
        len({e.event_type for e in all_events}),
        malformed_published,
    )
    return published


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic event generator for the data platform")
    parser.add_argument(
        "--orders", type=int, default=50, help="Number of synthetic order lifecycles to generate."
    )
    parser.add_argument(
        "--dead-letters", type=int, default=2, help="Number of synthetic deadletter.event rows."
    )
    parser.add_argument(
        "--duplicate-rate",
        type=float,
        default=0.05,
        help="Probability an event is redelivered a second time (tests Silver dedup).",
    )
    parser.add_argument(
        "--late-rate",
        type=float,
        default=0.05,
        help="Probability an event is backdated past Silver's late threshold.",
    )
    parser.add_argument(
        "--malformed-rate",
        type=float,
        default=0.0,
        help="Probability an additional raw, unparseable record is published alongside "
        "each event, on the same topic (tests Bronze's malformed-JSON quarantine). "
        "Opt-in (default 0) since it's an intentionally-broken payload, not real traffic.",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed, for reproducible runs."
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    run(
        order_count=args.orders,
        dead_letter_count=args.dead_letters,
        duplicate_rate=args.duplicate_rate,
        late_rate=args.late_rate,
        malformed_rate=args.malformed_rate,
        kafka_bootstrap_servers=settings.kafka_bootstrap_servers,
    )


if __name__ == "__main__":
    main()
