from app.config import get_settings
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_PASSED
from app.scenarios import payment_decline
from app.scenarios.base import ScenarioContext
from tests.fakes import (
    FakeGatewayClient,
    FakeInventoryServiceClient,
    FakeKafkaProducer,
    FakeOrchestratorClient,
    FakeOrderServiceClient,
)


def test_run_passes_when_saga_fails_via_compensation(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    # Pre-arrange the outcome a real saga compensation would leave: since
    # FakeGatewayClient assigns the order id, seed the saga/order fakes for
    # whatever id create_order will hand back by wrapping create_order.
    original_create = gateway.create_order

    def _create_and_seed(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        order_service.orders[order_id] = {"id": order_id, "status": "FAILED", "version": 2}
        orchestrator.sagas[order_id] = {
            "status": "FAILED",
            "current_step": "DONE",
            "context": {
                "reservation_ids": ["res-1"],
                "failure_reason": "payment declined (simulated)",
            },
        }
        return response

    gateway.create_order = _create_and_seed

    outcome = payment_decline.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert gateway.created_orders[0]["items"][0]["sku"] == payment_decline.DECLINE_SKU
    order_id = outcome.resources["order_id"]
    assert order_id in orchestrator.sagas
    assert order_service.orders[order_id]["status"] == "FAILED"


def test_run_reports_failed_when_order_does_not_reach_failed(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    original_create = gateway.create_order

    def _create_and_seed(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        # Unexpectedly "recovers" instead of failing — a real regression this test would catch.
        order_service.orders[order_id] = {"id": order_id, "status": "SHIPPED", "version": 5}
        orchestrator.sagas[order_id] = {
            "status": "COMPLETED",
            "current_step": "DONE",
            "context": {},
        }
        return response

    gateway.create_order = _create_and_seed

    outcome = payment_decline.run(ctx)
    assert outcome.status == STATUS_FAILED


def test_run_errors_on_poll_timeout(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "poll_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "poll_interval_seconds", 0.01)
    ctx = ScenarioContext(
        settings=settings,
        gateway=FakeGatewayClient(),
        order_service=FakeOrderServiceClient(),
        inventory=FakeInventoryServiceClient(),
        orchestrator=FakeOrchestratorClient(),  # saga never appears -> times out
        correlation_id="11111111-1111-1111-1111-111111111111",
        db=db_session,
        producer_factory=lambda: FakeKafkaProducer(),
    )
    outcome = payment_decline.run(ctx)
    assert outcome.status == STATUS_ERROR


def test_reset_is_a_no_op_message(make_ctx):
    outcome = payment_decline.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
