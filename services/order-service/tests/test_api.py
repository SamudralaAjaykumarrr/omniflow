import uuid


def _order_payload(**overrides):
    payload = {
        "customer_id": str(uuid.uuid4()),
        "customer_email": "shopper@example.com",
        "customer_display_name": "Test Shopper",
        "items": [{"sku": "SKU-1", "qty": 1, "unit_price": 19.99}],
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def _create_order(client):
    resp = client.post(
        "/orders", json=_order_payload(), headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_and_get_order(client):
    order = _create_order(client)
    assert order["status"] == "CREATED"
    assert order["version"] == 1

    resp = client.get(f"/orders/{order['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == order["id"]


def test_get_nonexistent_order_returns_404(client):
    resp = client.get(f"/orders/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "not_found"


def test_cancel_order_from_created_succeeds(client):
    order = _create_order(client)
    resp = client.post(
        f"/orders/{order['id']}/cancel",
        json={"reason": "customer changed their mind", "expected_version": order["version"]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    assert resp.json()["version"] == order["version"] + 1


def test_cancel_already_cancelled_order_is_rejected(client):
    order = _create_order(client)
    first = client.post(
        f"/orders/{order['id']}/cancel",
        json={"reason": "first cancel", "expected_version": order["version"]},
    )
    assert first.status_code == 200

    second = client.post(
        f"/orders/{order['id']}/cancel",
        json={"reason": "second cancel", "expected_version": first.json()["version"]},
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "conflict"


def test_cancel_with_stale_version_is_rejected(client):
    order = _create_order(client)
    resp = client.post(
        f"/orders/{order['id']}/cancel",
        json={"reason": "stale attempt", "expected_version": order["version"] + 5},
    )
    assert resp.status_code == 409


def test_order_history_records_transitions(client):
    order = _create_order(client)
    client.post(
        f"/orders/{order['id']}/cancel",
        json={"reason": "no longer needed", "expected_version": order["version"]},
    )
    resp = client.get(f"/orders/{order['id']}/history")
    assert resp.status_code == 200
    history = resp.json()
    assert [h["to_status"] for h in history] == ["CREATED", "CANCELLED"]
