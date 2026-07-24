import uuid

from event_contracts import EventEnvelope, EventType
from event_contracts.kafka import run_consume_loop
from event_contracts.logging_setup import correlation_id_var
from event_contracts.metrics_setup import KAFKA_CONSUMER_RETRY_TOTAL, KAFKA_DEAD_LETTER_TOTAL


class FakeMessage:
    def __init__(self, envelope: EventEnvelope) -> None:
        self._envelope = envelope

    def error(self):
        return None

    def value(self) -> bytes:
        return self._envelope.model_dump_json().encode("utf-8")


class FakeConsumer:
    """Yields each message in `messages` once, then returns None forever
    (simulating an idle partition) so `running()` becomes the only way the
    loop under test actually stops."""

    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = list(messages)
        self.committed: list[FakeMessage] = []

    def poll(self, timeout):
        if self._messages:
            return self._messages.pop(0)
        return None

    def commit(self, message):
        self.committed.append(message)


def _envelope(data: dict | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="test",
        correlation_id=str(uuid.uuid4()),
        data=data or {"order_id": "x"},
    )


def _run_until_processed(consumer: FakeConsumer, n_messages: int, **kwargs):
    processed = []
    counter = {"polls": 0}

    def process(envelope):
        processed.append(envelope)

    def running():
        counter["polls"] += 1
        # stop once we've had a chance to process every message plus a
        # handful of idle polls (bounds the loop without needing real time)
        return counter["polls"] <= n_messages + 5

    run_consume_loop(consumer, process, running=running, **kwargs)
    return processed


def test_successful_message_is_processed_once_and_committed():
    envelope = _envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])
    dead_lettered = []

    processed = _run_until_processed(
        consumer, 1, on_dead_letter=lambda e, err, n: dead_lettered.append(e)
    )

    assert [p.event_id for p in processed] == [envelope.event_id]
    assert len(consumer.committed) == 1
    assert dead_lettered == []


def test_transient_failure_retries_then_succeeds_without_dead_lettering():
    envelope = _envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])
    dead_lettered = []
    attempts = {"count": 0}

    def process(e):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")

    run_consume_loop(
        consumer,
        process,
        on_dead_letter=lambda e, err, n: dead_lettered.append((e, err, n)),
        base_delay=0.001,
        max_delay=0.01,
        running=lambda: attempts["count"] < 3,
    )

    assert attempts["count"] == 3
    assert dead_lettered == []
    assert len(consumer.committed) == 1


def test_permanent_failure_is_dead_lettered_and_still_committed():
    envelope = _envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])
    dead_lettered = []

    def process(e):
        raise ValueError("poison message")

    run_consume_loop(
        consumer,
        process,
        on_dead_letter=lambda e, err, n: dead_lettered.append((e.event_id, str(err), n)),
        max_attempts=3,
        base_delay=0.001,
        max_delay=0.01,
        running=lambda: len(consumer.committed) == 0,
    )

    assert len(dead_lettered) == 1
    dead_event_id, error_message, attempt_count = dead_lettered[0]
    assert dead_event_id == envelope.event_id
    assert "poison message" in error_message
    assert attempt_count == 3
    # committed even though it failed every attempt — a poison message must
    # not block the partition forever
    assert len(consumer.committed) == 1


def test_correlation_id_is_set_during_processing_and_cleared_after():
    envelope = _envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])
    observed = {}
    counter = {"polls": 0}

    def process(e):
        observed["during"] = correlation_id_var.get()

    def running():
        counter["polls"] += 1
        return counter["polls"] <= 3

    run_consume_loop(consumer, process, on_dead_letter=lambda e, err, n: None, running=running)

    assert observed["during"] == envelope.correlation_id
    assert correlation_id_var.get() is None  # reset once the message is done


def test_retry_and_dead_letter_counters_increment():
    envelope = _envelope()
    consumer = FakeConsumer([FakeMessage(envelope)])

    before_retry = KAFKA_CONSUMER_RETRY_TOTAL.labels(envelope.event_type)._value.get()
    before_dlq = KAFKA_DEAD_LETTER_TOTAL.labels(envelope.event_type)._value.get()

    def process(e):
        raise ValueError("always fails")

    run_consume_loop(
        consumer,
        process,
        on_dead_letter=lambda e, err, n: None,
        max_attempts=3,
        base_delay=0.001,
        max_delay=0.01,
        running=lambda: len(consumer.committed) == 0,
    )

    after_retry = KAFKA_CONSUMER_RETRY_TOTAL.labels(envelope.event_type)._value.get()
    after_dlq = KAFKA_DEAD_LETTER_TOTAL.labels(envelope.event_type)._value.get()

    assert after_retry == before_retry + 2  # 3 attempts = 2 retries before giving up
    assert after_dlq == before_dlq + 1


def test_idle_poll_returning_none_does_not_call_process_or_commit():
    consumer = FakeConsumer([])
    calls = {"process": 0}

    def process(e):
        calls["process"] += 1

    counter = {"n": 0}

    def running():
        counter["n"] += 1
        return counter["n"] <= 5

    run_consume_loop(consumer, process, on_dead_letter=lambda e, err, n: None, running=running)

    assert calls["process"] == 0
    assert consumer.committed == []
