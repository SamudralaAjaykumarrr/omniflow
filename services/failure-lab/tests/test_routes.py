import time

from app.models import STATUS_PASSED
from app.scenarios import registry
from app.scenarios.base import ScenarioContext, ScenarioOutcome


def _wait_for_terminal(client, scenario_id: str, run_id: str, timeout_seconds: float = 5.0) -> str:
    """Polls the run over HTTP until it leaves RUNNING — used even in tests
    that don't care about the outcome, so a still-running background
    thread never outlives its test and races the next test's table
    truncation (autouse `_clean_tables` in conftest.py)."""
    deadline = time.monotonic() + timeout_seconds
    status = "RUNNING"
    while status == "RUNNING":
        assert time.monotonic() < deadline, "scenario did not finish in time"
        time.sleep(0.05)
        status = client.get(f"/scenarios/{scenario_id}/runs/{run_id}").json()["status"]
    return status


def _fast_pass_entry(scenario_id: str = "payment-decline"):
    real_entry = registry.REGISTRY[scenario_id]

    def _run(ctx: ScenarioContext) -> ScenarioOutcome:
        return ScenarioOutcome(status=STATUS_PASSED, summary="ok (faked for API test)")

    return registry.ScenarioEntry(
        id=real_entry.id,
        name=real_entry.name,
        description=real_entry.description,
        category=real_entry.category,
        mechanism_reference=real_entry.mechanism_reference,
        expected_failure_behavior=real_entry.expected_failure_behavior,
        expected_recovery_behavior=real_entry.expected_recovery_behavior,
        run=_run,
        reset=real_entry.reset,
    )


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200


def test_list_scenarios_returns_all_10_with_no_runs_yet(client):
    resp = client.get("/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 10
    ids = [entry["catalog"]["id"] for entry in body]
    assert ids == registry.SCENARIO_ORDER
    for entry in body:
        assert entry["latest_run"] is None
        assert entry["run_count"] == 0
        assert entry["catalog"]["expected_failure_behavior"]
        assert entry["catalog"]["expected_recovery_behavior"]


def test_get_unknown_scenario_is_404(client):
    resp = client.get("/scenarios/does-not-exist")
    assert resp.status_code == 404


def test_trigger_unknown_scenario_is_404(client):
    resp = client.post("/scenarios/does-not-exist/trigger")
    assert resp.status_code == 404


def test_reset_unknown_scenario_is_404(client):
    resp = client.post("/scenarios/does-not-exist/reset")
    assert resp.status_code == 404


def test_trigger_reaches_a_terminal_state_and_is_visible_in_the_catalog(client, monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "payment-decline", _fast_pass_entry("payment-decline"))

    trigger_resp = client.post("/scenarios/payment-decline/trigger")
    assert trigger_resp.status_code == 202
    run = trigger_resp.json()
    assert run["status"] == "RUNNING"

    status = _wait_for_terminal(client, "payment-decline", run["id"])

    assert status == STATUS_PASSED

    detail = client.get("/scenarios/payment-decline").json()
    assert detail["latest_run"]["id"] == run["id"]
    assert detail["run_count"] == 1

    history = client.get("/scenarios/payment-decline/runs").json()
    assert len(history) == 1
    assert history[0]["id"] == run["id"]


def test_get_run_under_the_wrong_scenario_id_is_404(client, monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "payment-decline", _fast_pass_entry("payment-decline"))
    run = client.post("/scenarios/payment-decline/trigger").json()

    resp = client.get(f"/scenarios/payment-timeout/runs/{run['id']}")
    assert resp.status_code == 404

    _wait_for_terminal(client, "payment-decline", run["id"])


def test_reset_returns_the_scenario_specific_summary(client, monkeypatch):
    # inventory-oversell-race's real reset() calls the real InventoryServiceClient
    # over HTTP — not reachable from this test container, so fake just the
    # reset callable (same technique _fast_pass_entry uses for run()) and
    # exercise the route/persistence wiring, not a live network call.
    real_entry = registry.REGISTRY["inventory-oversell-race"]
    fake_entry = registry.ScenarioEntry(
        id=real_entry.id,
        name=real_entry.name,
        description=real_entry.description,
        category=real_entry.category,
        mechanism_reference=real_entry.mechanism_reference,
        expected_failure_behavior=real_entry.expected_failure_behavior,
        expected_recovery_behavior=real_entry.expected_recovery_behavior,
        run=real_entry.run,
        reset=lambda ctx: "Re-seeded available_qty=1 (faked for API test).",
    )
    monkeypatch.setitem(registry.REGISTRY, "inventory-oversell-race", fake_entry)

    resp = client.post("/scenarios/inventory-oversell-race/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario_id"] == "inventory-oversell-race"
    assert "available_qty=1" in body["summary"]
