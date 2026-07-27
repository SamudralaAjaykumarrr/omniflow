import json
import uuid
from datetime import timedelta

import pytest

from app.kafka import (
    publish_late_order_shipped_envelope,
    publish_malformed_record,
    publish_order_created_envelope,
)
from event_contracts import EventType
from tests.fakes import FakeKafkaProducer


def test_publish_order_created_envelope_generates_a_fresh_synthetic_order():
    producer = FakeKafkaProducer()
    envelope = publish_order_created_envelope(producer, correlation_id=str(uuid.uuid4()))

    assert len(producer.produced) == 1
    assert producer.produced[0]["topic"] == EventType.ORDER_CREATED
    # publish_envelope encodes the key to bytes before handing it to the producer.
    assert producer.produced[0]["key"] == envelope.data["order_id"].encode("utf-8")


def test_publish_order_created_envelope_republishes_the_identical_envelope():
    producer = FakeKafkaProducer()
    original = publish_order_created_envelope(producer, correlation_id=str(uuid.uuid4()))
    republished = publish_order_created_envelope(
        producer, correlation_id=str(uuid.uuid4()), envelope=original
    )

    assert republished is original
    assert len(producer.produced) == 2
    assert producer.produced[0]["value"] == producer.produced[1]["value"]


def test_publish_late_order_shipped_envelope_is_well_past_the_lateness_threshold():
    producer = FakeKafkaProducer()
    envelope = publish_late_order_shipped_envelope(
        producer, correlation_id=str(uuid.uuid4()), lateness=timedelta(minutes=45)
    )

    assert producer.produced[0]["topic"] == EventType.ORDER_SHIPPED
    # A genuinely valid OrderShippedDataV1 payload, not malformed.
    assert set(envelope.data.keys()) == {
        "order_id",
        "node_id",
        "shipped_at",
        "carrier_sim",
        "tracking_ref",
    }


def test_publish_malformed_record_sends_non_json_bytes():
    producer = FakeKafkaProducer()
    publish_malformed_record(
        producer, topic="inventory.low", key="k1", raw_bytes=b"not json at all {{{"
    )

    assert producer.produced[0]["topic"] == "inventory.low"
    with pytest.raises(json.JSONDecodeError):
        json.loads(producer.produced[0]["value"])


def test_publish_malformed_record_raises_if_delivery_reports_an_error():
    class _FailingProducer(FakeKafkaProducer):
        def produce(self, topic, key=None, value=None, on_delivery=None):
            if on_delivery is not None:
                on_delivery(RuntimeError("broker unavailable"), None)

    with pytest.raises(RuntimeError, match="malformed record publish"):
        publish_malformed_record(
            _FailingProducer(), topic="inventory.low", key="k1", raw_bytes=b"x"
        )
