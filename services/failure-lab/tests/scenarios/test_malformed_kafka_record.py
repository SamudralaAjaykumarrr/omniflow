import json

import pytest

from app.models import STATUS_PASSED
from app.scenarios import malformed_kafka_record
from tests.fakes import FakeKafkaProducer


def test_run_publishes_a_malformed_record_to_a_topic_with_no_transactional_consumer(make_ctx):
    producer = FakeKafkaProducer()
    ctx = make_ctx(producer=producer)

    outcome = malformed_kafka_record.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert len(producer.produced) == 1
    published = producer.produced[0]
    assert published["topic"] == malformed_kafka_record.TARGET_TOPIC
    assert published["topic"] not in ("order.created", "order.validated", "order.cancelled")
    # Genuinely not valid JSON — the point of the scenario.
    with pytest.raises(json.JSONDecodeError):
        json.loads(published["value"])


def test_run_is_safe_to_call_repeatedly(make_ctx):
    producer = FakeKafkaProducer()
    ctx = make_ctx(producer=producer)

    first = malformed_kafka_record.run(ctx)
    second = malformed_kafka_record.run(ctx)

    assert first.status == STATUS_PASSED
    assert second.status == STATUS_PASSED
    assert len(producer.produced) == 2
    assert first.resources["key"] != second.resources["key"]


def test_reset_message(make_ctx):
    outcome = malformed_kafka_record.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
