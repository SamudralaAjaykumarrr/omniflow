from app.models import STATUS_PASSED
from app.scenarios import duplicate_event_delivery
from tests.fakes import FakeKafkaProducer, FakeOrderServiceClient


def test_run_passes_when_redelivery_is_a_true_no_op(make_ctx):
    order_service = FakeOrderServiceClient(auto_process_events=True)
    producer = FakeKafkaProducer()
    ctx = make_ctx(order_service=order_service, producer=producer)

    outcome = duplicate_event_delivery.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert outcome.diagnostics["first_processed_at"] == outcome.diagnostics["final_processed_at"]
    assert outcome.diagnostics["synthetic_order_exists"] is False
    # The envelope was published 3 times total (1 original + 2 redeliveries),
    # every time keyed by the same order_id (the same envelope object is
    # reused for the redeliveries, so its event_id is identical too).
    assert len(producer.produced) == 3
    assert len({p["key"] for p in producer.produced}) == 1


def test_reset_message(make_ctx):
    outcome = duplicate_event_delivery.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
