import uuid

from sqlalchemy import select

from app.models import ProcessedEvent, SagaInstance
from app.saga import handle_order_validated
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def test_redelivered_order_validated_event_only_runs_the_saga_once(db_session):
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
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", "SKU-1", 10)

    envelope = EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": order_id, "validated_at": "2026-07-24T00:00:00Z"},
    )

    handle_order_validated(db_session, order_client, inventory_client, envelope)
    transition_calls_after_first = len(order_client.transition_calls)

    # redeliver the identical event (same event_id)
    handle_order_validated(db_session, order_client, inventory_client, envelope)

    assert len(order_client.transition_calls) == transition_calls_after_first  # no new calls
    assert inventory_client.stock[("node-a", "SKU-1")] == 9  # decremented once, not twice

    sagas = (
        db_session.execute(select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id)))
        .scalars()
        .all()
    )
    assert len(sagas) == 1

    processed = (
        db_session.execute(
            select(ProcessedEvent).where(ProcessedEvent.event_id == uuid.UUID(envelope.event_id))
        )
        .scalars()
        .all()
    )
    assert len(processed) == 1
