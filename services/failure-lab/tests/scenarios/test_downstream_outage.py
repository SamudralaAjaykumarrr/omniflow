from app.models import STATUS_ERROR, STATUS_RECOVERED
from app.scenarios import downstream_outage
from tests.fakes import (
    FakeGatewayClient,
    FakeInventoryServiceClient,
    FakeOrchestratorClient,
    FakeOrderServiceClient,
)


def _seed_dead_letter(orchestrator: FakeOrchestratorClient, order_id: str) -> None:
    # Matches the REAL DeadLetterEvent.payload shape (the flat original
    # envelope — app/consumer.py's dead_letter(): `payload=envelope.
    # model_dump(...)`), not wrapped in an "original_event" key. An earlier
    # version of this fixture used the wrong (wrapped) shape, which made
    # this test a false positive — it never caught the real matching bug
    # in downstream_outage.py's own _dead_lettered(), only found running
    # the scenario against a live stack.
    orchestrator.dead_letters.append(
        {
            "id": "dl-1",
            "replayed_at": None,
            "payload": {"data": {"order_id": order_id}},
        }
    )


def test_run_recovers_after_replaying_the_dead_letter(make_ctx):
    gateway = FakeGatewayClient()
    order_service = FakeOrderServiceClient()
    inventory = FakeInventoryServiceClient()
    orchestrator = FakeOrchestratorClient()
    ctx = make_ctx(
        gateway=gateway, order_service=order_service, inventory=inventory, orchestrator=orchestrator
    )

    gateway.readyz_response = (503, {"status": "not_ready"})

    original_create = gateway.create_order

    def _create_and_dead_letter(payload, idempotency_key):
        response = original_create(payload, idempotency_key)
        order_id = response["id"]
        _seed_dead_letter(orchestrator, order_id)
        return response

    def _replay_and_recover(dead_letter_id: str) -> dict:
        for dl in orchestrator.dead_letters:
            if dl["id"] == dead_letter_id:
                dl["replayed_at"] = "2026-01-01T00:00:00Z"
        # Find the order_id this dead letter was for and mark its saga/order SHIPPED.
        order_id = orchestrator.dead_letters[0]["payload"]["data"]["order_id"]
        order_service.orders[order_id] = {"id": order_id, "status": "SHIPPED", "version": 8}
        orchestrator.sagas[order_id] = {
            "status": "COMPLETED",
            "current_step": "DONE",
            "context": {},
        }
        orchestrator.replayed_ids.append(dead_letter_id)
        return {"id": dead_letter_id}

    gateway.create_order = _create_and_dead_letter
    orchestrator.replay_dead_letter = _replay_and_recover

    outcome = downstream_outage.run(ctx)

    assert outcome.status == STATUS_RECOVERED
    assert inventory.outage_calls[0] == ("enable", downstream_outage.OUTAGE_DURATION_SECONDS)
    assert inventory.outage_calls[-1] == ("disable", None)
    assert not inventory.outage_active
    assert outcome.diagnostics["gateway_readyz_during_outage"]["status_code"] == 503


def test_run_errors_if_nothing_ever_dead_letters(make_ctx):
    gateway = FakeGatewayClient()
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(gateway=gateway, inventory=inventory)

    outcome = downstream_outage.run(ctx)

    assert outcome.status == STATUS_ERROR
    # Outage is always disabled again, even on the error path (the `finally`).
    assert not inventory.outage_active


def test_reset_force_disables_the_outage(make_ctx):
    inventory = FakeInventoryServiceClient()
    inventory.outage_active = True
    ctx = make_ctx(inventory=inventory)

    summary = downstream_outage.reset(ctx)

    assert not inventory.outage_active
    assert isinstance(summary, str) and summary
