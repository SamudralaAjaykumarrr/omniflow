import respx
from httpx import Response

from app.clients import (
    ConflictError,
    GatewayClient,
    InventoryServiceClient,
    NotFoundError,
    OrchestratorClient,
    RemoteServiceError,
)

BASE = "http://test-service"


@respx.mock
def test_gateway_client_create_order_sends_idempotency_key_header():
    route = respx.post(f"{BASE}/api/orders").mock(
        return_value=Response(201, json={"id": "abc", "status": "CREATED"})
    )
    client = GatewayClient(BASE)

    result = client.create_order({"customer_id": "x"}, "key-1")

    assert result["id"] == "abc"
    assert route.calls.last.request.headers["Idempotency-Key"] == "key-1"


@respx.mock
def test_gateway_client_readyz_returns_status_and_body():
    respx.get(f"{BASE}/readyz").mock(return_value=Response(503, json={"status": "not_ready"}))
    client = GatewayClient(BASE)

    status_code, body = client.readyz()

    assert status_code == 503
    assert body == {"status": "not_ready"}


@respx.mock
def test_inventory_client_reserve_raises_conflict_on_409():
    respx.post(f"{BASE}/reservations").mock(
        return_value=Response(409, json={"message": "insufficient stock"})
    )
    client = InventoryServiceClient(BASE)

    try:
        client.reserve(order_id="o1", sku="SKU-1", node_id="n1", qty=1, correlation_id="c1")
        raise AssertionError("expected ConflictError")
    except ConflictError as exc:
        assert exc.status_code == 409


@respx.mock
def test_inventory_client_get_or_create_node_reuses_an_existing_node_by_name():
    respx.get(f"{BASE}/fulfillment-nodes").mock(
        return_value=Response(200, json=[{"id": "n1", "name": "my-node"}])
    )
    post_route = respx.post(f"{BASE}/fulfillment-nodes").mock(
        return_value=Response(201, json={"id": "n2", "name": "my-node"})
    )
    client = InventoryServiceClient(BASE)

    node = client.get_or_create_node("my-node", latitude=0.0, longitude=0.0, capacity_per_day=1)

    assert node["id"] == "n1"
    assert not post_route.called


@respx.mock
def test_inventory_client_get_or_create_node_recovers_from_a_create_race():
    respx.get(f"{BASE}/fulfillment-nodes").mock(
        side_effect=[
            Response(200, json=[]),
            Response(200, json=[{"id": "n1", "name": "my-node"}]),
        ]
    )
    respx.post(f"{BASE}/fulfillment-nodes").mock(
        return_value=Response(409, json={"message": "name already exists"})
    )
    client = InventoryServiceClient(BASE)

    node = client.get_or_create_node("my-node", latitude=0.0, longitude=0.0, capacity_per_day=1)

    assert node["id"] == "n1"


@respx.mock
def test_orchestrator_client_get_saga_for_order_returns_none_on_404():
    order_id = "11111111-1111-1111-1111-111111111111"
    respx.get(f"{BASE}/saga-instances/{order_id}").mock(return_value=Response(404, json={}))
    client = OrchestratorClient(BASE)

    assert client.get_saga_for_order(order_id) is None


@respx.mock
def test_get_raises_not_found_error_on_404():
    respx.get(f"{BASE}/orders/missing").mock(return_value=Response(404, json={"detail": "nope"}))
    client = OrchestratorClient(
        BASE
    )  # any _JsonClient subclass exercises the same _raise_for_status

    try:
        client._get("/orders/missing")
        raise AssertionError("expected NotFoundError")
    except NotFoundError:
        pass


@respx.mock
def test_get_raises_remote_service_error_on_500():
    respx.get(f"{BASE}/boom").mock(return_value=Response(500, text="internal error"))
    client = OrchestratorClient(BASE)

    try:
        client._get("/boom")
        raise AssertionError("expected RemoteServiceError")
    except RemoteServiceError as exc:
        assert exc.status_code == 500
