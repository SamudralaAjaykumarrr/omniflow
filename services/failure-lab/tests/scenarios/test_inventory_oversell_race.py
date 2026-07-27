from app.models import STATUS_FAILED, STATUS_PASSED
from app.scenarios import inventory_oversell_race
from tests.fakes import FakeInventoryServiceClient


def test_run_lets_exactly_one_concurrent_reservation_win(make_ctx):
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    outcome = inventory_oversell_race.run(ctx)

    assert outcome.status == STATUS_PASSED
    assert outcome.diagnostics["reserved_count"] == 1
    assert outcome.diagnostics["rejected_count"] == inventory_oversell_race.CONCURRENCY - 1
    assert outcome.diagnostics["final_available_qty"] == 0
    # Never oversold: available_qty never goes negative.
    node_id = outcome.resources["node_id"]
    assert inventory.stock[(inventory_oversell_race.SKU, node_id)]["available_qty"] == 0


def test_run_is_safe_to_call_twice_in_a_row(make_ctx):
    """The scenario re-seeds available_qty=1 itself at the start of every
    run — safe to rerun without an explicit reset() in between."""
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    first = inventory_oversell_race.run(ctx)
    second = inventory_oversell_race.run(ctx)

    assert first.status == STATUS_PASSED
    assert second.status == STATUS_PASSED


def test_run_reports_failed_if_more_than_one_reservation_could_win(make_ctx, monkeypatch):
    """Scripts `_attempt_reservation` to return 2 "reserved" outcomes
    instead of the real (lock-serialized) behavior's 1 — simulating what a
    broken concurrency control would produce — and confirms the scenario's
    own assertion (exactly 1 winner, available_qty == 0) correctly reports
    FAILED rather than silently passing. Deterministic by construction
    (no real thread race involved), unlike asserting on genuine thread
    timing would be."""
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)

    call_count = 0

    def _fake_attempt_reservation(ctx, node_id):
        nonlocal call_count
        call_count += 1
        outcome = "reserved" if call_count <= 2 else "rejected"
        return {"order_id": f"order-{call_count}", "status_code": 201, "outcome": outcome}

    monkeypatch.setattr(inventory_oversell_race, "_attempt_reservation", _fake_attempt_reservation)

    outcome = inventory_oversell_race.run(ctx)

    assert outcome.status == STATUS_FAILED
    assert outcome.diagnostics["reserved_count"] == 2


def test_reset_reseeds_available_quantity_to_one(make_ctx):
    inventory = FakeInventoryServiceClient()
    ctx = make_ctx(inventory=inventory)
    inventory_oversell_race.run(ctx)  # consumes the unit

    summary = inventory_oversell_race.reset(ctx)

    node = inventory.get_or_create_node(
        inventory_oversell_race.NODE_NAME, latitude=0.0, longitude=0.0, capacity_per_day=1000
    )
    assert inventory.stock[(inventory_oversell_race.SKU, node["id"])]["available_qty"] == 1
    assert "available_qty=1" in summary
