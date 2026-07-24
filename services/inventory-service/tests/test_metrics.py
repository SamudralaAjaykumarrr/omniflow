import uuid

from app.metrics import INVENTORY_RESERVATION_CONFLICTS_TOTAL


def _create_node(client):
    resp = client.post(
        "/fulfillment-nodes",
        json={
            "name": f"node-{uuid.uuid4()}",
            "latitude": 47.6,
            "longitude": -122.3,
            "capacity_per_day": 100,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_insufficient_stock_increments_conflict_counter(client):
    node = _create_node(client)
    client.post(
        "/stock",
        json={
            "sku": "SKU-METRIC",
            "node_id": node["id"],
            "available_qty": 1,
            "reorder_threshold": 0,
        },
    )

    before = INVENTORY_RESERVATION_CONFLICTS_TOTAL.labels("SKU-METRIC")._value.get()

    resp = client.post(
        "/reservations",
        json={
            "order_id": str(uuid.uuid4()),
            "sku": "SKU-METRIC",
            "node_id": node["id"],
            "qty": 5,
            "correlation_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 409

    after = INVENTORY_RESERVATION_CONFLICTS_TOTAL.labels("SKU-METRIC")._value.get()
    assert after == before + 1


def test_metrics_endpoint_exposes_prometheus_text(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"http_requests_total" in resp.content
