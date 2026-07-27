"""Phase 8 (failure lab) scenario 9, saga-crash-resume: an order carrying
CRASH_SIMULATION_SKU makes advance_saga pause itself right after
SELECT_AND_RESERVE commits, leaving the saga_instances row RUNNING at
ASSIGN_FULFILLMENT — exactly the state a real process crash between those
two steps would leave (RISKS.md #11). These tests exercise app.saga
directly with the same fakes the rest of this suite uses; the failure-lab
service's own route-level resume test
(tests/test_failure_lab_routes.py::test_resume_route_drives_a_paused_saga_to_completion)
covers the HTTP surface on top of this.
"""

import uuid

from app.saga import (
    CRASH_SIMULATION_SKU,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STEP_ASSIGN_FULFILLMENT,
    advance_saga,
    handle_order_validated,
)
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def _seed(order_id, sku, qty=1):
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


def test_marker_sku_pauses_the_saga_right_after_select_and_reserve(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=CRASH_SIMULATION_SKU)

    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    from sqlalchemy import select

    from app.models import SagaInstance

    saga = db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()

    assert saga.status == STATUS_RUNNING
    assert saga.current_step == STEP_ASSIGN_FULFILLMENT
    assert saga.context["_crash_simulated"] is True
    # The reservation genuinely happened before the pause — this is what
    # makes it a faithful "crashed after committing, before continuing"
    # simulation, not just a saga that never started.
    assert saga.context["reservation_ids"]
    assert inventory_client.stock[("node-a", CRASH_SIMULATION_SKU)] == 4

    # A second call (e.g. a redelivered order.validated) must not re-run the
    # saga from scratch or double-reserve — it's already processed/paused.
    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )
    assert inventory_client.stock[("node-a", CRASH_SIMULATION_SKU)] == 4


def test_resuming_a_paused_saga_completes_it_without_pausing_again(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seed(order_id, sku=CRASH_SIMULATION_SKU)
    handle_order_validated(
        db_session, order_client, inventory_client, _validated_envelope(order_id)
    )

    from sqlalchemy import select

    from app.models import SagaInstance

    saga = db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()
    assert saga.current_step == STEP_ASSIGN_FULFILLMENT  # paused

    advance_saga(db_session, order_client, inventory_client, saga)

    assert saga.status == STATUS_COMPLETED
    assert order_client.orders[order_id]["status"] == "SHIPPED"
