import time

import pytest

from app.outage import get_outage_state


@pytest.fixture(autouse=True)
def _reset_outage_state():
    """app.outage's module-level singleton persists across TestClient
    instances within a test process — must not leak between tests."""
    get_outage_state().disable()
    yield
    get_outage_state().disable()


def test_outage_disabled_by_default(client):
    resp = client.get("/internal/failure-lab/outage/status")
    assert resp.status_code == 200
    assert resp.json()["active"] is False


def test_enabling_outage_makes_healthz_and_business_routes_503(client):
    enable_resp = client.post("/internal/failure-lab/outage/enable", json={"duration_seconds": 30})
    assert enable_resp.status_code == 200
    assert enable_resp.json()["active"] is True

    healthz_resp = client.get("/healthz")
    assert healthz_resp.status_code == 503
    assert healthz_resp.json()["status"] == "simulated_outage"

    nodes_resp = client.get("/fulfillment-nodes")
    assert nodes_resp.status_code == 503


def test_outage_control_and_metrics_endpoints_stay_reachable_during_an_outage(client):
    client.post("/internal/failure-lab/outage/enable", json={"duration_seconds": 30})

    status_resp = client.get("/internal/failure-lab/outage/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["active"] is True

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200


def test_disabling_outage_restores_normal_behavior(client):
    client.post("/internal/failure-lab/outage/enable", json={"duration_seconds": 30})
    assert client.get("/healthz").status_code == 503

    disable_resp = client.post("/internal/failure-lab/outage/disable")
    assert disable_resp.status_code == 200
    assert disable_resp.json()["active"] is False

    assert client.get("/healthz").status_code == 200


def test_outage_self_clears_after_its_duration(client):
    client.post("/internal/failure-lab/outage/enable", json={"duration_seconds": 0.2})
    assert client.get("/healthz").status_code == 503

    time.sleep(0.3)

    assert client.get("/healthz").status_code == 200
    assert client.get("/internal/failure-lab/outage/status").json()["active"] is False
