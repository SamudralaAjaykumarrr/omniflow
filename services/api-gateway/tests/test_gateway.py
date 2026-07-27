import httpx
import respx
from httpx import Response

from app.config import get_settings

# Phase 9 (JWT/RBAC): every /api/* route below now requires a valid JWT
# (viewer for reads, ops/admin for mutations — see app/routes.py). These
# tests were updated, not weakened, to keep asserting the real proxy
# behavior under valid auth; the 401/403 boundary itself is covered
# separately in tests/test_auth.py.


def _auth(make_token, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(role=role)}"}


@respx.mock
def test_create_order_is_proxied_to_order_service(client, make_token):
    settings = get_settings()
    route = respx.post(f"{settings.order_service_url}/orders").mock(
        return_value=Response(201, json={"id": "abc", "status": "CREATED"})
    )
    resp = client.post(
        "/api/orders",
        json={"customer_id": "x"},
        headers={"Idempotency-Key": "key-1", **_auth(make_token, "ops")},
    )
    assert route.called
    assert resp.status_code == 201
    assert resp.json()["status"] == "CREATED"
    assert "X-Correlation-ID" in resp.headers


@respx.mock
def test_get_order_is_proxied(client, make_token):
    settings = get_settings()
    order_id = "11111111-1111-1111-1111-111111111111"
    respx.get(f"{settings.order_service_url}/orders/{order_id}").mock(
        return_value=Response(200, json={"id": order_id, "status": "CREATED"})
    )
    resp = client.get(f"/api/orders/{order_id}", headers=_auth(make_token, "viewer"))
    assert resp.status_code == 200
    assert resp.json()["id"] == order_id


@respx.mock
def test_stock_query_is_proxied_to_inventory_service(client, make_token):
    settings = get_settings()
    node_id = "22222222-2222-2222-2222-222222222222"
    respx.get(f"{settings.inventory_service_url}/stock/SKU-1/{node_id}").mock(
        return_value=Response(200, json={"sku": "SKU-1", "available_qty": 5})
    )
    resp = client.get("/api/inventory/stock/SKU-1/" + node_id, headers=_auth(make_token, "viewer"))
    assert resp.status_code == 200
    assert resp.json()["available_qty"] == 5


@respx.mock
def test_upstream_unreachable_returns_502(client, make_token):
    settings = get_settings()
    respx.get(f"{settings.order_service_url}/orders/whatever").mock(
        side_effect=httpx.ConnectError("boom")
    )
    resp = client.get("/api/orders/whatever", headers=_auth(make_token, "viewer"))
    assert resp.status_code == 502
    assert resp.json()["error_code"] == "upstream_unavailable"


@respx.mock
def test_upstream_timeout_returns_504(client, make_token):
    settings = get_settings()
    respx.get(f"{settings.order_service_url}/orders/slow").mock(
        side_effect=httpx.TimeoutException("too slow")
    )
    resp = client.get("/api/orders/slow", headers=_auth(make_token, "viewer"))
    assert resp.status_code == 504
    assert resp.json()["error_code"] == "upstream_timeout"


@respx.mock
def test_correlation_id_is_propagated_to_upstream_and_echoed(client, make_token):
    settings = get_settings()
    captured = {}

    def responder(request):
        captured["correlation_id"] = request.headers.get("X-Correlation-ID")
        return Response(200, json={"status": "ok"})

    respx.get(f"{settings.order_service_url}/orders/xyz").mock(side_effect=responder)
    resp = client.get(
        "/api/orders/xyz",
        headers={"X-Correlation-ID": "caller-supplied-id", **_auth(make_token, "viewer")},
    )
    assert resp.status_code == 200
    assert captured["correlation_id"] == "caller-supplied-id"
    assert resp.headers["X-Correlation-ID"] == "caller-supplied-id"


@respx.mock
def test_correlation_id_is_minted_when_absent(client, make_token):
    settings = get_settings()
    respx.get(f"{settings.order_service_url}/orders/xyz").mock(return_value=Response(200, json={}))
    resp = client.get("/api/orders/xyz", headers=_auth(make_token, "viewer"))
    assert resp.status_code == 200
    assert resp.headers["X-Correlation-ID"]  # non-empty, minted by the gateway


def test_readyz_reports_not_ready_when_upstreams_unreachable(client):
    # /readyz is a platform endpoint, deliberately unauthenticated — no
    # respx mock active — real httpx calls to the http://*-test hosts fail
    # to resolve/connect
    resp = client.get("/readyz")
    assert resp.status_code == 503
