"""Regression test for a real bug found running Phase 8's downstream-outage
scenario against a live stack: `handle_order_validated` used to mark a
brand-new order.validated event "processed" *before* calling `advance_saga`
for the first time. If that first call raised an unexpected exception (a
downstream 503, any bug), the event was already marked processed — so
Kafka's own redelivery-of-the-same-message retry became a silent no-op
(`_already_processed` short-circuited before ever calling `advance_saga`
again), leaving the saga stuck RUNNING forever with no dead-letter entry
and no further retry. Fixed by marking processed only after advance_saga
returns without raising; a raise now correctly falls through to Kafka's
retry, which re-enters the "existing saga" branch and resumes it.
"""

import uuid

from sqlalchemy import select

from app.models import ProcessedEvent, SagaInstance
from app.saga import (
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STEP_SELECT_AND_RESERVE,
    handle_order_validated,
)
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


class _FlakyInventoryServiceClient(FakeInventoryServiceClient):
    """Raises on its first `list_nodes()` call (simulating a downstream
    outage / any transient failure), then behaves normally afterward —
    models exactly what a real redelivery-after-recovery looks like."""

    def __init__(self) -> None:
        super().__init__()
        self.list_nodes_calls = 0

    def list_nodes(self):
        self.list_nodes_calls += 1
        if self.list_nodes_calls == 1:
            raise RuntimeError("simulated downstream outage")
        return super().list_nodes()


def _validated_envelope(order_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": order_id, "validated_at": "2026-07-24T00:00:00Z"},
    )


def test_a_transient_failure_on_first_advance_leaves_the_event_unprocessed_for_retry(db_session):
    order_id = str(uuid.uuid4())
    order_client = FakeOrderServiceClient()
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id="customer-1",
        order_total=10.0,
        items=[{"sku": "SKU-1", "qty": 1, "unit_price": 10.0}],
    )
    inventory_client = _FlakyInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", "SKU-1", 10)

    envelope = _validated_envelope(order_id)

    try:
        handle_order_validated(db_session, order_client, inventory_client, envelope)
        raise AssertionError("expected the simulated outage to raise")
    except RuntimeError as exc:
        assert "simulated downstream outage" in str(exc)

    # The saga row was created and persisted (so a retry can find and
    # resume it), but the event itself must NOT be marked processed yet —
    # that's the exact bug this test guards against.
    saga = db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()
    assert saga.status == STATUS_RUNNING
    assert saga.current_step == STEP_SELECT_AND_RESERVE

    processed = db_session.execute(
        select(ProcessedEvent).where(ProcessedEvent.event_id == uuid.UUID(envelope.event_id))
    ).scalar_one_or_none()
    assert processed is None

    # Kafka redelivers the identical message (same event_id) once the
    # downstream dependency has recovered — this must actually resume the
    # saga, not silently no-op.
    handle_order_validated(db_session, order_client, inventory_client, envelope)

    db_session.refresh(saga)
    assert saga.status == STATUS_COMPLETED
    assert order_client.orders[order_id]["status"] == "SHIPPED"

    processed = db_session.execute(
        select(ProcessedEvent).where(ProcessedEvent.event_id == uuid.UUID(envelope.event_id))
    ).scalar_one()
    assert processed is not None
