"""Thin confluent-kafka wrappers shared by every producer/consumer in the
platform. This is boilerplate, not business logic — build a producer/consumer,
publish an `EventEnvelope` as JSON, parse one back out, and run a generic
retry-then-dead-letter consume loop. What counts as "processed successfully",
idempotency bookkeeping, and how a dead letter gets persisted are each
service's own responsibility (passed in as callbacks), not duplicated here.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable

from confluent_kafka import Consumer, Message, Producer

from event_contracts.envelope import EventEnvelope


class KafkaPublishError(Exception):
    def __init__(self, topic: str, event_id: str, reason: str) -> None:
        self.topic = topic
        self.event_id = event_id
        super().__init__(f"failed to publish {event_id} to {topic}: {reason}")


class KafkaPublishTimeoutError(KafkaPublishError):
    def __init__(self, topic: str, event_id: str) -> None:
        super().__init__(topic, event_id, "producer.flush() timed out before delivery")


def build_producer(bootstrap_servers: str) -> Producer:
    return Producer({"bootstrap.servers": bootstrap_servers})


def publish_envelope(
    producer: Producer,
    topic: str,
    key: str,
    envelope: EventEnvelope,
    timeout: float = 10.0,
) -> None:
    """Synchronously publish and flush one envelope.

    Blocking flush-per-call trades raw throughput for a simple, correct
    guarantee: the outbox relay only marks a row `published_at` after Kafka
    has actually acknowledged the write, never optimistically.
    """
    delivery_errors: list[str] = []

    def _on_delivery(err, _msg) -> None:
        if err is not None:
            delivery_errors.append(str(err))

    producer.produce(
        topic,
        key=key.encode("utf-8"),
        value=envelope.model_dump_json().encode("utf-8"),
        on_delivery=_on_delivery,
    )
    still_queued = producer.flush(timeout=timeout)
    if still_queued > 0:
        raise KafkaPublishTimeoutError(topic, envelope.event_id)
    if delivery_errors:
        raise KafkaPublishError(topic, envelope.event_id, delivery_errors[0])


def build_consumer(bootstrap_servers: str, group_id: str, topics: Iterable[str]) -> Consumer:
    """Manual offset commits — a message's offset is only committed after
    the caller has finished processing it (including DLQ routing on
    failure), never automatically in the background. That is what makes
    "commit after DLQ" a real guarantee instead of a race."""
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(list(topics))
    return consumer


def parse_envelope(message: Message) -> EventEnvelope:
    return EventEnvelope.model_validate_json(message.value())


def run_consume_loop(
    consumer: Consumer,
    process: Callable[[EventEnvelope], None],
    *,
    on_dead_letter: Callable[[EventEnvelope, BaseException, int], None],
    max_attempts: int = 5,
    base_delay: float = 0.2,
    max_delay: float = 30.0,
    poll_timeout: float = 1.0,
    running: Callable[[], bool] = lambda: True,
) -> None:
    """Poll `consumer` while `running()`, parse each message as an
    `EventEnvelope`, and call `process(envelope)`.

    On failure, retries with exponential backoff + jitter
    (`base_delay * 2**(attempt-1)`, capped at `max_delay`, jittered up to
    +10%) up to `max_attempts`. If still failing, calls
    `on_dead_letter(envelope, error, attempt_count)` — the caller's job to
    persist the failure and publish it to `deadletter.event` — and moves on.

    The offset is committed after successful processing OR after DLQ
    routing, **never before either** — that ordering is what makes "a
    poison message doesn't block the partition forever, but also doesn't
    get silently skipped" an actual guarantee rather than a race.
    """
    while running():
        msg = consumer.poll(poll_timeout)
        if msg is None:
            continue
        if msg.error():
            continue  # transient broker-level poll error; retried on next poll

        envelope = parse_envelope(msg)
        attempt = 0
        while True:
            attempt += 1
            try:
                process(envelope)
                break
            except Exception as exc:  # noqa: BLE001 - must catch everything to route to DLQ
                if attempt >= max_attempts:
                    on_dead_letter(envelope, exc, attempt)
                    break
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                delay += random.uniform(0, delay * 0.1)
                time.sleep(delay)
        consumer.commit(msg)
