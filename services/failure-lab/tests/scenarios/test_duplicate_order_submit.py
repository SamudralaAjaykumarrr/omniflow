from app.models import STATUS_PASSED
from app.scenarios import duplicate_order_submit
from tests.fakes import FakeGatewayClient


def test_run_dedupes_repeats_and_rejects_a_payload_mismatch(make_ctx):
    gateway = FakeGatewayClient()
    ctx = make_ctx(gateway=gateway)

    outcome = duplicate_order_submit.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert len(outcome.diagnostics["distinct_order_ids"]) == 1
    assert outcome.diagnostics["conflict_on_different_payload"] is True
    # Only 1 order actually created despite 3 repeated submissions.
    assert len(gateway.created_orders) == 1


def test_run_is_safe_to_rerun_with_a_fresh_key_each_time(make_ctx):
    gateway = FakeGatewayClient()
    ctx1 = make_ctx(gateway=gateway)
    ctx2 = make_ctx(gateway=gateway)  # different correlation_id -> different idempotency key

    first = duplicate_order_submit.run(ctx1)
    second = duplicate_order_submit.run(ctx2)

    assert first.status == STATUS_PASSED
    assert second.status == STATUS_PASSED
    assert first.resources["order_id"] != second.resources["order_id"]


def test_reset_message(make_ctx):
    outcome = duplicate_order_submit.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
