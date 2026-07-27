from app.models import STATUS_FAILED, STATUS_RECOVERED
from app.scenarios import payment_timeout
from tests.fakes import FakeGatewayClient, FakeOrchestratorClient, FakeOrderServiceClient


def test_run_recovers_when_saga_completes_and_ships(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    original_create = gateway.create_order

    def _create_and_seed(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        order_service.orders[order_id] = {"id": order_id, "status": "SHIPPED", "version": 6}
        orchestrator.sagas[order_id] = {
            "status": "COMPLETED",
            "current_step": "DONE",
            "context": {},
        }
        return response

    gateway.create_order = _create_and_seed

    outcome = payment_timeout.run(ctx)

    assert outcome.status == STATUS_RECOVERED
    assert gateway.created_orders[0]["items"][0]["sku"] == payment_timeout.TRANSIENT_RECOVER_SKU


def test_run_fails_when_saga_does_not_recover(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    original_create = gateway.create_order

    def _create_and_seed(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        order_service.orders[order_id] = {"id": order_id, "status": "FAILED", "version": 3}
        orchestrator.sagas[order_id] = {"status": "FAILED", "current_step": "DONE", "context": {}}
        return response

    gateway.create_order = _create_and_seed

    outcome = payment_timeout.run(ctx)
    assert outcome.status == STATUS_FAILED


def test_reset_is_a_no_op_message(make_ctx):
    outcome = payment_timeout.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
