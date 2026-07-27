"""Thin confluent-kafka wrappers shared by every producer/consumer in the
platform. This is boilerplate, not business logic — build a producer/consumer,
publish an `EventEnvelope` as JSON, parse one back out, and run a generic
retry-then-dead-letter consume loop. What counts as "processed successfully",
idempotency bookkeeping, and how a dead letter gets persisted are each
service's own responsibility (passed in as callbacks), not duplicated here.

The consume loop also carries the platform's cross-cutting observability:
it sets `correlation_id_var` (structured logging), starts a tracing span
extracted from the envelope's stored `trace_context.traceparent` (so the
consumer span lands in the same Jaeger trace as whatever created the
event), and increments retry/dead-letter Prometheus counters.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable

from confluent_kafka import Consumer, Message, Producer
from opentelemetry import trace

from event_contracts.envelope import EventEnvelope
from event_contracts.logging_setup import correlation_id_var
from event_contracts.metrics_setup import (
    KAFKA_CONSUMER_RETRY_TOTAL,
    KAFKA_DEAD_LETTER_TOTAL,
    KAFKA_MALFORMED_RECORD_TOTAL,
)
from event_contracts.tracing_setup import context_from_traceparent

_tracer = trace.get_tracer(__name__)
_logger = logging.getLogger(__name__)


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


def build_consumer(
    bootstrap_servers: str,
    group_id: str,
    topics: Iterable[str],
    stats_cb: Callable[[str], None] | None = None,
) -> Consumer:
    """Manual offset commits — a message's offset is only committed after
    the caller has finished processing it (including DLQ routing on
    failure), never automatically in the background. That is what makes
    "commit after DLQ" a real guarantee instead of a race.

    `stats_cb` (paired with `statistics.interval.ms`) is how consumer lag is
    measured — see `event_contracts.metrics_setup.kafka_stats_callback`.
    """
    config = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    if stats_cb is not None:
        config["stats_cb"] = stats_cb
        config["statistics.interval.ms"] = 15000
    consumer = Consumer(config)
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

    A record that isn't even valid-envelope-shaped JSON (`parse_envelope`
    itself raising) is a distinct failure mode from a *business-logic*
    failure inside `process()`: there is no valid `EventEnvelope` to hand to
    `on_dead_letter`, retrying parsing again would never succeed (the bytes
    are what they are), and every caller of this loop only ever provisioned
    one Kafka consumer group per process — blocking on it would starve
    every other message behind it forever. So this is logged + counted
    (`KAFKA_MALFORMED_RECORD_TOTAL`) and the offset is committed
    immediately, never retried and never crashing the consumer process.
    Found for real during Phase 8 validation: a message the Phase 6
    synthetic generator's `--malformed-rate` had left sitting in a real
    topic crashed the process on every restart until this existed (see
    RISKS.md).

    The offset is committed after successful processing OR after DLQ
    routing, **never before either** — that ordering is what makes "a
    poison message doesn't block the partition forever, but also doesn't
    get silently skipped" an actual guarantee rather than a race.

    Each message is processed with `correlation_id_var` set to the
    envelope's `correlation_id` (structured logs) and inside a tracing span
    that is a child of whatever span was active when the event was created
    (`envelope.trace_context.traceparent`) — see `event_contracts.tracing_setup`.
    """
    while running():
        msg = consumer.poll(poll_timeout)
        if msg is None:
            continue
        if msg.error():
            continue  # transient broker-level poll error; retried on next poll

        try:
            envelope = parse_envelope(msg)
        except Exception as exc:  # noqa: BLE001 - any parse failure is equally unrecoverable
            _logger.error(
                "skipping unparseable Kafka record on %s (partition %s, offset %s): %s",
                msg.topic(),
                msg.partition(),
                msg.offset(),
                exc,
            )
            KAFKA_MALFORMED_RECORD_TOTAL.labels(msg.topic()).inc()
            consumer.commit(msg)
            continue

        correlation_token = correlation_id_var.set(envelope.correlation_id)
        try:
            span_context = context_from_traceparent(envelope.trace_context.traceparent)
            with _tracer.start_as_current_span(
                f"consume {envelope.event_type}", context=span_context
            ) as span:
                span.set_attribute("correlation_id", envelope.correlation_id)
                span.set_attribute("event_id", envelope.event_id)
                span.set_attribute("event_type", envelope.event_type)

                attempt = 0
                while True:
                    attempt += 1
                    try:
                        process(envelope)
                        break
                    except Exception as exc:  # noqa: BLE001 - must catch everything to route to DLQ
                        if attempt >= max_attempts:
                            KAFKA_DEAD_LETTER_TOTAL.labels(envelope.event_type).inc()
                            span.record_exception(exc)
                            on_dead_letter(envelope, exc, attempt)
                            break
                        KAFKA_CONSUMER_RETRY_TOTAL.labels(envelope.event_type).inc()
                        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        delay += random.uniform(0, delay * 0.1)
                        time.sleep(delay)
        finally:
            correlation_id_var.reset(correlation_token)
        consumer.commit(msg)
