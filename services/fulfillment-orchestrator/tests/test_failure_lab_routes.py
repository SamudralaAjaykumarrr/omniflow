import json
import uuid
from datetime import UTC, datetime

import respx
from httpx import Response

from app.config import get_settings
from app.models import DeadLetterEvent, SagaInstance
from app.saga import CRASH_SIMULATION_SKU
from event_contracts import EventEnvelope, EventType


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bytes]] = []

    def produce(self, topic, key, value, on_delivery=None):
        self.published.append((topic, key, value))
        if on_delivery:
            on_delivery(None, None)

    def flush(self, timeout=10):
        return 0


class _StatefulOrderService:
    """A tiny in-memory order-service stand-in for respx — the resume
    endpoint's saga steps issue real REST calls, so unlike the rest of this
    service's test suite (which calls saga functions directly with
    tests/fakes.py's fakes), this route-level test needs HTTP-level
    responses that reflect state changes across several calls."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        self.status = "INVENTORY_RESERVED"
        self.version = 3

    def _body(self) -> dict:
        return {
            "id": self.order_id,
            "status": self.status,
            "version": self.version,
            "customer_id": str(uuid.uuid4()),
            "order_total": 10.0,
            "items": [{"sku": "SKU-1", "qty": 1, "unit_price": 10.0}],
        }

    def get(self, request):
        return Response(200, json=self._body())

    def transition(self, request):
        body = json.loads(request.content)
        self.status = body["to_status"]
        self.version += 1
        return Response(200, json=self._body())


def _paused_saga(order_id: uuid.UUID) -> SagaInstance:
    return SagaInstance(
        order_id=order_id,
        correlation_id=uuid.uuid4(),
        current_step="ASSIGN_FULFILLMENT",
        status="RUNNING",
        context={
            "_crash_simulated": True,
            "items": [{"sku": CRASH_SIMULATION_SKU, "qty": 1, "unit_price": 15.0}],
            "customer_id": str(uuid.uuid4()),
            "order_total": 15.0,
            "node_id": str(uuid.uuid4()),
            "reservation_ids": ["res-1"],
            "score": 1.0,
            "score_breakdown": {
                "stock": 1.0,
                "distance": 1.0,
                "capacity": 1.0,
                "delivery_estimate": 1.0,
                "backlog": 1.0,
            },
            "estimated_ship_date_days": 1,
        },
    )


def test_resume_route_drives_a_paused_saga_to_completion(client, db_session):
    settings = get_settings()
    saga = _paused_saga(uuid.uuid4())
    db_session.add(saga)
    db_session.commit()

    order_service = _StatefulOrderService(str(saga.order_id))
    with respx.mock:
        respx.get(f"{settings.order_service_url}/orders/{saga.order_id}").mock(
            side_effect=order_service.get
        )
        respx.post(f"{settings.order_service_url}/orders/{saga.order_id}/transition").mock(
            side_effect=order_service.transition
        )

        resp = client.post(f"/internal/failure-lab/saga-crash-resume/{saga.order_id}/resume")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["current_step"] == "DONE"
    assert order_service.status == "SHIPPED"


def test_resume_route_404s_for_an_unknown_order(client):
    resp = client.post(f"/internal/failure-lab/saga-crash-resume/{uuid.uuid4()}/resume")
    assert resp.status_code == 404


def test_resume_route_409s_for_a_saga_that_is_not_running(client, db_session):
    saga = _paused_saga(uuid.uuid4())
    saga.status = "COMPLETED"
    db_session.add(saga)
    db_session.commit()

    resp = client.post(f"/internal/failure-lab/saga-crash-resume/{saga.order_id}/resume")
    assert resp.status_code == 409


def _dead_letter_row(event_type=EventType.ORDER_VALIDATED) -> DeadLetterEvent:
    original = EventEnvelope(
        event_type=event_type,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": str(uuid.uuid4()), "validated_at": "2026-07-24T00:00:00Z"},
    )
    now = datetime.now(UTC)
    return DeadLetterEvent(
        original_event_id=uuid.UUID(original.event_id),
        event_type=original.event_type,
        failed_consumer="fulfillment-orchestrator",
        error_type="KeyError",
        error_message="boom",
        attempt_count=5,
        # The flat envelope itself — see test_dlq_and_replay.py's matching
        # comment for why this must not be wrapped in "original_event".
        payload=original.model_dump(mode="json"),
        first_failed_at=now,
        last_failed_at=now,
    )


def test_replay_route_republishes_and_marks_replayed(client, db_session, monkeypatch):
    dead_letter = _dead_letter_row()
    db_session.add(dead_letter)
    db_session.commit()

    fake_producer = FakeProducer()
    monkeypatch.setattr("app.routes.get_producer", lambda: fake_producer)

    resp = client.post(f"/dead-letters/{dead_letter.id}/replay")

    assert resp.status_code == 200
    assert resp.json()["replayed_at"] is not None
    assert len(fake_producer.published) == 1


def test_replay_route_404s_for_an_unknown_dead_letter(client):
    resp = client.post(f"/dead-letters/{uuid.uuid4()}/replay")
    assert resp.status_code == 404


def test_replay_route_409s_if_already_replayed(client, db_session, monkeypatch):
    dead_letter = _dead_letter_row()
    dead_letter.replayed_at = datetime.now(UTC)
    db_session.add(dead_letter)
    db_session.commit()

    fake_producer = FakeProducer()
    monkeypatch.setattr("app.routes.get_producer", lambda: fake_producer)

    resp = client.post(f"/dead-letters/{dead_letter.id}/replay")
    assert resp.status_code == 409
