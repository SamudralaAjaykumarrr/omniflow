import json
from datetime import datetime

from app.models import STATUS_PASSED
from app.scenarios import late_event_arrival
from tests.fakes import FakeKafkaProducer


def test_run_publishes_a_well_formed_but_late_order_shipped_event(make_ctx):
    producer = FakeKafkaProducer()
    ctx = make_ctx(producer=producer)

    outcome = late_event_arrival.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert len(producer.produced) == 1
    published = producer.produced[0]
    assert published["topic"] == "order.shipped"

    envelope = json.loads(published["value"])
    occurred_at = datetime.fromisoformat(envelope["occurred_at"])
    now = datetime.now(occurred_at.tzinfo)
    lateness_seconds = (now - occurred_at).total_seconds()
    # Comfortably past Silver's 600-second LATE_THRESHOLD_SECONDS.
    assert lateness_seconds > 600
    # A genuinely valid envelope — not the malformed-record scenario.
    assert envelope["data"]["order_id"] == outcome.resources["order_id"]


def test_reset_message(make_ctx):
    outcome = late_event_arrival.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
