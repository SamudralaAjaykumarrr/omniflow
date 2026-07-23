import uuid

from sqlalchemy import select

from app.models import SagaInstance
from app.payment import DECLINE_SKU, TRANSIENT_PERSISTENT_SKU, TRANSIENT_RECOVER_SKU
from app.saga import STATUS_FAILED, STEP_DONE, handle_order_cancelled, handle_order_validated
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def _seed(order_id, sku="SKU-1", qty=1, customer_id="customer-1"):
    order_client = FakeOrderServiceClient()
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id=customer_id,
        order_total=10.0,
        items=[{"sku": sku, "qty": qty, "unit_price": 10.0}],
    )
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    return order_client, inventory_client


def _validated_envelope(order_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": order_id, "validated_at": "2026-07-24T00:00:00Z"},
    )


def _saga_for(db_session, order_id: str) -> SagaInstance:
    return db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()


def test_no_node_has_sufficient_stock_fails_the_order_with_no_compensation(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, qty=5)
    # node-a exists but has zero stock — no candidate can satisfy the order
    inventory_client.set_stock("node-a", "SKU-1", 0)

    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    order = order_client.orders[order_id]
    assert order["status"] == "FAILED"

    saga = _saga_for(db_session, order_id)
    assert saga.status == STATUS_FAILED
    assert saga.current_step == STEP_DONE


def test_payment_hard_decline_compensates_by_releasing_the_reservation(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=DECLINE_SKU, qty=1)
    inventory_client.set_stock("node-a", DECLINE_SKU, 5)

    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    order = order_client.orders[order_id]
    assert order["status"] == "FAILED"
    # the reservation was released — stock restored to its pre-reservation level
    assert inventory_client.stock[("node-a", DECLINE_SKU)] == 5

    saga = _saga_for(db_session, order_id)
    assert saga.status == STATUS_FAILED
    assert saga.context["reservation_ids"]  # a reservation really was made, then released


def test_payment_transient_failure_exhausts_retries_then_compensates(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=TRANSIENT_PERSISTENT_SKU, qty=1)
    inventory_client.set_stock("node-a", TRANSIENT_PERSISTENT_SKU, 5)

    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    order = order_client.orders[order_id]
    assert order["status"] == "FAILED"
    assert inventory_client.stock[("node-a", TRANSIENT_PERSISTENT_SKU)] == 5

    saga = _saga_for(db_session, order_id)
    assert saga.status == STATUS_FAILED


def test_payment_transient_failure_recovers_on_retry_and_completes(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=TRANSIENT_RECOVER_SKU, qty=1)
    inventory_client.set_stock("node-a", TRANSIENT_RECOVER_SKU, 5)

    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    order = order_client.orders[order_id]
    assert order["status"] == "SHIPPED"  # recovered on the 2nd payment attempt


def test_cancelling_a_running_saga_releases_its_reservation(db_session):
    """Simulates a customer cancellation racing the saga: rather than
    driving the saga all the way through, we manually construct a saga row
    parked at AUTHORIZE_PAYMENT with an active reservation (as if the
    process had gotten that far), then deliver order.cancelled and confirm
    the reservation is released and the saga is marked failed/aborted.
    """
    order_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", "SKU-1", 10)
    handle = inventory_client.reserve(
        order_id=str(order_id),
        sku="SKU-1",
        node_id="node-a",
        qty=2,
        correlation_id=str(correlation_id),
    )
    assert inventory_client.stock[("node-a", "SKU-1")] == 8

    saga = SagaInstance(
        order_id=order_id,
        correlation_id=correlation_id,
        current_step="AUTHORIZE_PAYMENT",
        status="RUNNING",
        context={"reservation_ids": [handle.id], "node_id": "node-a"},
    )
    db_session.add(saga)
    db_session.commit()

    cancelled_envelope = EventEnvelope(
        event_type=EventType.ORDER_CANCELLED,
        producer="order-service",
        correlation_id=str(correlation_id),
        data={
            "order_id": str(order_id),
            "cancelled_by": "customer",
            "reason": "changed their mind",
            "previous_state": "FULFILLMENT_ASSIGNED",
        },
    )
    handle_order_cancelled(db_session, inventory_client, cancelled_envelope)

    assert inventory_client.stock[("node-a", "SKU-1")] == 10  # released back
    db_session.refresh(saga)
    assert saga.status == STATUS_FAILED
    assert saga.current_step == STEP_DONE
