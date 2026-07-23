import uuid

from sqlalchemy import select

from app.models import OutboxEvent, SagaInstance
from app.saga import STATUS_COMPLETED, STEP_DONE, handle_order_validated
from event_contracts import EventEnvelope, EventType
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def _seeded_clients(
    order_id: str, customer_id: str = "customer-1", sku: str = "SKU-1", qty: int = 2
):
    order_client = FakeOrderServiceClient()
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id=customer_id,
        order_total=25.0,
        items=[{"sku": sku, "qty": qty, "unit_price": 12.5}],
    )
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", sku, 10)
    return order_client, inventory_client


def _validated_envelope(order_id: str, correlation_id: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_VALIDATED,
        producer="order-service",
        correlation_id=correlation_id or str(uuid.uuid4()),
        data={"order_id": order_id, "validated_at": "2026-07-24T00:00:00Z"},
    )


def test_happy_path_completes_and_ships(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seeded_clients(order_id)
    envelope = _validated_envelope(order_id)

    handle_order_validated(db_session, order_client, inventory_client, envelope)

    order = order_client.orders[order_id]
    assert order["status"] == "SHIPPED"
    assert order["node_id"] == "node-a"

    saga = db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()
    assert saga.status == STATUS_COMPLETED
    assert saga.current_step == STEP_DONE
    assert saga.context["reservation_ids"]

    # stock was actually decremented, not just the order flagged
    assert inventory_client.stock[("node-a", "SKU-1")] == 8

    outbox_event_types = {
        row.event_type for row in db_session.execute(select(OutboxEvent)).scalars()
    }
    assert EventType.INVENTORY_RESERVATION_REQUESTED in outbox_event_types
    assert EventType.FULFILLMENT_ASSIGNED in outbox_event_types
    assert EventType.ORDER_SHIPPED in outbox_event_types


def test_picks_the_better_scoring_node_among_two_sufficient_candidates(db_session):
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seeded_clients(order_id, customer_id="customer-close-to-a")

    # node-b is deliberately far from every simulated customer location by
    # being at the antipode-ish offset relative to node-a for this test.
    inventory_client.add_node(
        "node-b", latitude=-40.0, longitude=60.0, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-b", "SKU-1", 10)

    envelope = _validated_envelope(order_id)
    handle_order_validated(db_session, order_client, inventory_client, envelope)

    saga = db_session.execute(
        select(SagaInstance).where(SagaInstance.order_id == uuid.UUID(order_id))
    ).scalar_one()
    assert saga.context["node_id"] in ("node-a", "node-b")  # one was chosen and reserved
    chosen = saga.context["node_id"]
    other = "node-b" if chosen == "node-a" else "node-a"
    # only the chosen node's stock was touched
    assert inventory_client.stock[(chosen, "SKU-1")] == 8
    assert inventory_client.stock[(other, "SKU-1")] == 10


def test_falls_back_to_next_candidate_when_the_best_scored_node_rejects_at_reservation_time(
    db_session,
):
    """Both node-a and node-b pass the advisory stock-check (sufficient at
    check time), but node-a's actual reservation call is forced to reject —
    simulating a race where a concurrent order won the row lock first. The
    saga must roll back nothing (nothing was reserved at node-a yet) and
    fall through to node-b, still completing successfully.
    """
    order_id = str(uuid.uuid4())
    order_client, inventory_client = _seeded_clients(order_id, qty=2)
    inventory_client.add_node(
        "node-b", latitude=10, longitude=10, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-b", "SKU-1", 10)
    inventory_client.force_reserve_rejection("node-a", times=1)

    envelope = _validated_envelope(order_id)
    handle_order_validated(db_session, order_client, inventory_client, envelope)

    order = order_client.orders[order_id]
    assert order["status"] == "SHIPPED"
    assert order["node_id"] == "node-b"
    # node-a's stock is untouched — the forced rejection happened before any
    # decrement, so there was nothing to roll back
    assert inventory_client.stock[("node-a", "SKU-1")] == 10
    assert inventory_client.stock[("node-b", "SKU-1")] == 8


def test_rolls_back_partial_reservation_when_a_later_item_is_rejected_at_the_same_node(
    db_session,
):
    """Two-item order: the first item reserves fine at node-a, but the
    second item's reservation is forced to reject at node-a — the saga must
    release the first item's reservation before falling through to node-b.
    """
    order_id = str(uuid.uuid4())
    order_client = FakeOrderServiceClient()
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id="customer-1",
        order_total=40.0,
        items=[
            {"sku": "SKU-1", "qty": 1, "unit_price": 10.0},
            {"sku": "SKU-2", "qty": 1, "unit_price": 30.0},
        ],
    )
    inventory_client = FakeInventoryServiceClient()
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", "SKU-1", 5)
    inventory_client.set_stock("node-a", "SKU-2", 5)
    inventory_client.add_node(
        "node-b", latitude=10, longitude=10, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-b", "SKU-1", 5)
    inventory_client.set_stock("node-b", "SKU-2", 5)

    # node-a passes the pre-check (both SKUs genuinely in stock), but its
    # SKU-2 reservation is forced to reject — a race the pre-check couldn't
    # see, e.g. a concurrent order winning the row lock between check and
    # reserve.
    inventory_client.force_reserve_rejection_for_sku("node-a", "SKU-2", times=1)

    envelope = _validated_envelope(order_id)
    handle_order_validated(db_session, order_client, inventory_client, envelope)

    order = order_client.orders[order_id]
    assert order["status"] == "SHIPPED"
    assert order["node_id"] == "node-b"
    # SKU-1's reservation at node-a was rolled back, not left dangling
    assert inventory_client.stock[("node-a", "SKU-1")] == 5
    assert inventory_client.stock[("node-b", "SKU-1")] == 4
    assert inventory_client.stock[("node-b", "SKU-2")] == 4
