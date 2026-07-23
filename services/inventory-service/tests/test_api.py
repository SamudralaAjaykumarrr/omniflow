import uuid


def _create_node(client):
    resp = client.post(
        "/fulfillment-nodes",
        json={
            "name": f"node-{uuid.uuid4()}",
            "latitude": 47.6,
            "longitude": -122.3,
            "capacity_per_day": 500,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _seed_stock(client, node_id, sku="SKU-1", qty=10):
    resp = client.post(
        "/stock",
        json={"sku": sku, "node_id": node_id, "available_qty": qty, "reorder_threshold": 2},
    )
    assert resp.status_code == 200
    return resp.json()


def test_seed_and_get_stock(client):
    node = _create_node(client)
    _seed_stock(client, node["id"], qty=25)
    resp = client.get(f"/stock/SKU-1/{node['id']}")
    assert resp.status_code == 200
    assert resp.json()["available_qty"] == 25


def test_get_unknown_stock_returns_404(client):
    resp = client.get(f"/stock/NOPE/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "not_found"


def test_reserve_and_release_round_trip(client):
    node = _create_node(client)
    _seed_stock(client, node["id"], qty=10)

    reserve_resp = client.post(
        "/reservations",
        json={
            "order_id": str(uuid.uuid4()),
            "sku": "SKU-1",
            "node_id": node["id"],
            "qty": 3,
            "correlation_id": str(uuid.uuid4()),
        },
    )
    assert reserve_resp.status_code == 201
    reservation = reserve_resp.json()
    assert reservation["status"] == "ACTIVE"

    stock_after_reserve = client.get(f"/stock/SKU-1/{node['id']}").json()
    assert stock_after_reserve["available_qty"] == 7
    assert stock_after_reserve["reserved_qty"] == 3

    release_resp = client.post(
        f"/reservations/{reservation['id']}/release", json={"reason": "order cancelled"}
    )
    assert release_resp.status_code == 200
    assert release_resp.json()["status"] == "RELEASED"

    stock_after_release = client.get(f"/stock/SKU-1/{node['id']}").json()
    assert stock_after_release["available_qty"] == 10
    assert stock_after_release["reserved_qty"] == 0


def test_reserve_more_than_available_is_rejected(client):
    node = _create_node(client)
    _seed_stock(client, node["id"], qty=2)

    resp = client.post(
        "/reservations",
        json={
            "order_id": str(uuid.uuid4()),
            "sku": "SKU-1",
            "node_id": node["id"],
            "qty": 5,
            "correlation_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "conflict"

    stock = client.get(f"/stock/SKU-1/{node['id']}").json()
    assert stock["available_qty"] == 2  # untouched


def test_release_unknown_reservation_returns_404(client):
    resp = client.post(f"/reservations/{uuid.uuid4()}/release", json={"reason": "n/a"})
    assert resp.status_code == 404


def test_release_already_released_reservation_is_conflict(client):
    node = _create_node(client)
    _seed_stock(client, node["id"], qty=5)
    reservation = client.post(
        "/reservations",
        json={
            "order_id": str(uuid.uuid4()),
            "sku": "SKU-1",
            "node_id": node["id"],
            "qty": 1,
            "correlation_id": str(uuid.uuid4()),
        },
    ).json()

    first = client.post(f"/reservations/{reservation['id']}/release", json={"reason": "first"})
    assert first.status_code == 200

    second = client.post(f"/reservations/{reservation['id']}/release", json={"reason": "second"})
    assert second.status_code == 409
