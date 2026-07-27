from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_RECOVERED
from app.scenarios import saga_crash_resume
from tests.fakes import FakeGatewayClient, FakeOrchestratorClient, FakeOrderServiceClient


def test_run_recovers_after_resuming_a_paused_saga(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    original_create = gateway.create_order

    def _create_and_pause(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        order_service.orders[order_id] = {
            "id": order_id,
            "status": "INVENTORY_RESERVED",
            "version": 3,
        }
        orchestrator.sagas[order_id] = {
            "status": "RUNNING",
            "current_step": "ASSIGN_FULFILLMENT",
            "context": {"_crash_simulated": True, "reservation_ids": ["res-1"]},
        }
        return response

    def _on_resume(order_id: str) -> None:
        order_service.orders[order_id] = {"id": order_id, "status": "SHIPPED", "version": 8}
        orchestrator.sagas[order_id] = {
            "status": "COMPLETED",
            "current_step": "DONE",
            "context": {},
        }

    gateway.create_order = _create_and_pause
    orchestrator.on_resume = _on_resume

    outcome = saga_crash_resume.run(ctx)

    assert outcome.status == STATUS_RECOVERED
    order_id = outcome.resources["order_id"]
    assert orchestrator.resume_calls == [order_id]
    assert gateway.created_orders[0]["items"][0]["sku"] == saga_crash_resume.CRASH_SIMULATION_SKU


def test_run_errors_if_the_saga_never_pauses(make_ctx):
    gateway = FakeGatewayClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, orchestrator=orchestrator)
    # No _crash_simulated ever appears -> the first poll_until times out.
    outcome = saga_crash_resume.run(ctx)
    assert outcome.status == STATUS_ERROR


def test_run_fails_if_resume_does_not_reach_shipped(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(gateway=gateway, order_service=order_service, orchestrator=orchestrator)

    original_create = gateway.create_order

    def _create_and_pause(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        order_service.orders[order_id] = {
            "id": order_id,
            "status": "INVENTORY_RESERVED",
            "version": 3,
        }
        orchestrator.sagas[order_id] = {
            "status": "RUNNING",
            "current_step": "ASSIGN_FULFILLMENT",
            "context": {"_crash_simulated": True},
        }
        return response

    def _on_resume(order_id: str) -> None:
        orchestrator.sagas[order_id] = {"status": "FAILED", "current_step": "DONE", "context": {}}

    gateway.create_order = _create_and_pause
    orchestrator.on_resume = _on_resume

    outcome = saga_crash_resume.run(ctx)
    assert outcome.status == STATUS_FAILED


def test_reset_message(make_ctx):
    outcome = saga_crash_resume.reset(make_ctx())
    assert isinstance(outcome, str) and outcome
