import uuid

from app.models import Order
from app.state_machine import OrderStatus


def _create_order(client):
    resp = client.post(
        "/orders",
        json={
            "customer_id": str(uuid.uuid4()),
            "customer_email": "shopper@example.com",
            "customer_display_name": "Test Shopper",
            "items": [{"sku": "SKU-1", "qty": 1, "unit_price": 10.0}],
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201
    return resp.json()


def _force_status(db_session, order_id: str, status: OrderStatus) -> None:
    order = db_session.get(Order, uuid.UUID(order_id))
    order.status = status.value
    db_session.commit()


def test_transition_moves_order_forward_through_the_saga(client, db_session):
    order = _create_order(client)
    _force_status(db_session, order["id"], OrderStatus.VALIDATED)

    resp = client.post(
        f"/orders/{order['id']}/transition",
        json={
            "to_status": "INVENTORY_PENDING",
            "expected_version": 1,
            "reason": "orchestrator: requesting reservation",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INVENTORY_PENDING"
    assert resp.json()["version"] == 2


def test_transition_to_fulfillment_assigned_requires_and_sets_node_id(client, db_session):
    order = _create_order(client)
    _force_status(db_session, order["id"], OrderStatus.INVENTORY_RESERVED)
    node_id = str(uuid.uuid4())

    missing_node = client.post(
        f"/orders/{order['id']}/transition",
        json={
            "to_status": "FULFILLMENT_ASSIGNED",
            "expected_version": 1,
            "reason": "orchestrator: node scored",
        },
    )
    assert missing_node.status_code == 422

    resp = client.post(
        f"/orders/{order['id']}/transition",
        json={
            "to_status": "FULFILLMENT_ASSIGNED",
            "expected_version": 1,
            "reason": "orchestrator: node scored",
            "node_id": node_id,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FULFILLMENT_ASSIGNED"
    assert resp.json()["assigned_node_id"] == node_id


def test_transition_rejects_invalid_target_status(client, db_session):
    order = _create_order(client)
    _force_status(db_session, order["id"], OrderStatus.VALIDATED)

    resp = client.post(
        f"/orders/{order['id']}/transition",
        json={"to_status": "SHIPPED", "expected_version": 1, "reason": "skip ahead"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "conflict"


def test_transition_rejects_stale_version(client, db_session):
    order = _create_order(client)
    _force_status(db_session, order["id"], OrderStatus.VALIDATED)

    resp = client.post(
        f"/orders/{order['id']}/transition",
        json={"to_status": "INVENTORY_PENDING", "expected_version": 99, "reason": "stale"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "conflict"


def test_transition_unknown_order_returns_404(client):
    resp = client.post(
        f"/orders/{uuid.uuid4()}/transition",
        json={"to_status": "INVENTORY_PENDING", "expected_version": 1, "reason": "n/a"},
    )
    assert resp.status_code == 404
