import uuid

ORDER_PAYLOAD = {
    "customer_id": str(uuid.uuid4()),
    "customer_email": "shopper@example.com",
    "customer_display_name": "Test Shopper",
    "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 9.99}],
    "currency": "USD",
}


def test_duplicate_submission_with_same_key_and_payload_returns_original_order(client):
    key = str(uuid.uuid4())
    first = client.post("/orders", json=ORDER_PAYLOAD, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    second = client.post("/orders", json=ORDER_PAYLOAD, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_same_key_different_payload_is_conflict(client):
    key = str(uuid.uuid4())
    first = client.post("/orders", json=ORDER_PAYLOAD, headers={"Idempotency-Key": key})
    assert first.status_code == 201

    different_payload = {**ORDER_PAYLOAD, "items": [{"sku": "SKU-2", "qty": 1, "unit_price": 5.0}]}
    second = client.post("/orders", json=different_payload, headers={"Idempotency-Key": key})
    assert second.status_code == 409


def test_different_keys_create_different_orders(client):
    first = client.post(
        "/orders", json=ORDER_PAYLOAD, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    second = client.post(
        "/orders", json=ORDER_PAYLOAD, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
