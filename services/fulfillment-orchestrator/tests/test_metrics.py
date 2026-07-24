import uuid

from app.metrics import SAGA_DURATION_SECONDS
from app.payment import DECLINE_SKU
from app.saga import handle_order_validated
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def _seed(order_id, sku="SKU-1", qty=1):
    order_client = FakeOrderServiceClient()
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id="customer-1",
        order_total=10.0,
        items=[{"sku": sku, "qty": qty, "unit_price": 10.0}],
    )
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", sku, 5)
    return order_client, inventory_client


def _validated_envelope(order_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": order_id, "validated_at": "2026-07-24T00:00:00Z"},
    )


def test_completed_saga_observes_a_real_duration_with_completed_label(db_session):
    before_sum = SAGA_DURATION_SECONDS.labels("completed")._sum.get()

    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id)
    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    after_sum = SAGA_DURATION_SECONDS.labels("completed")._sum.get()
    assert after_sum > before_sum  # a real, positive duration was added to the sum


def test_failed_saga_observes_a_real_duration_with_failed_label(db_session):
    before_sum = SAGA_DURATION_SECONDS.labels("failed")._sum.get()

    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=DECLINE_SKU)
    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    after_sum = SAGA_DURATION_SECONDS.labels("failed")._sum.get()
    assert after_sum > before_sum
