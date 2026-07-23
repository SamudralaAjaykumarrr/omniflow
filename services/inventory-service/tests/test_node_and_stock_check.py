import uuid


def _create_node(client, **overrides):
    payload = {
        "name": f"node-{uuid.uuid4()}",
        "latitude": 47.6,
        "longitude": -122.3,
        "capacity_per_day": 200,
    }
    payload.update(overrides)
    resp = client.post("/fulfillment-nodes", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_list_nodes_returns_created_nodes(client):
    node_a = _create_node(client)
    node_b = _create_node(client)

    resp = client.get("/fulfillment-nodes")
    assert resp.status_code == 200
    ids = {n["id"] for n in resp.json()}
    assert node_a["id"] in ids
    assert node_b["id"] in ids


def test_stock_check_reports_sufficient_when_all_items_available(client):
    node = _create_node(client)
    client.post(
        "/stock",
        json={"sku": "SKU-1", "node_id": node["id"], "available_qty": 10, "reorder_threshold": 2},
    )
    client.post(
        "/stock",
        json={"sku": "SKU-2", "node_id": node["id"], "available_qty": 5, "reorder_threshold": 1},
    )

    resp = client.post(
        "/stock/check",
        json={
            "node_id": node["id"],
            "items": [{"sku": "SKU-1", "qty": 3}, {"sku": "SKU-2", "qty": 5}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sufficient"] is True
    assert body["shortfalls"] == []


def test_stock_check_reports_shortfalls_for_insufficient_or_unknown_sku(client):
    node = _create_node(client)
    client.post(
        "/stock",
        json={"sku": "SKU-1", "node_id": node["id"], "available_qty": 1, "reorder_threshold": 0},
    )

    resp = client.post(
        "/stock/check",
        json={
            "node_id": node["id"],
            "items": [{"sku": "SKU-1", "qty": 5}, {"sku": "SKU-UNKNOWN", "qty": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sufficient"] is False
    shortfalls_by_sku = {s["sku"]: s for s in body["shortfalls"]}
    assert shortfalls_by_sku["SKU-1"]["available_qty"] == 1
    assert shortfalls_by_sku["SKU-1"]["requested_qty"] == 5
    assert shortfalls_by_sku["SKU-UNKNOWN"]["available_qty"] == 0
