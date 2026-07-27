"""Shared inventory seeding for scenarios that need a real saga to actually
reach SELECT_AND_RESERVE successfully (payment-decline, payment-timeout,
saga-crash-resume, downstream-outage) — a fresh `docker compose up` has no
stock at all for these scenarios' marker SKUs, so without this the saga
would fail at STEP_FAIL_NO_INVENTORY (no candidate node has sufficient
stock) before ever reaching the step each scenario actually means to
exercise. A real bug found running `scripts/phase8_smoke_test.sh` against
a clean stack for the first time: payment-timeout's order failed with no
`reservation_ids`/`node_id` in its saga context at all — the tell that it
never got past inventory selection, not a payment problem.
"""

from __future__ import annotations

from app.scenarios.base import ScenarioContext

SHARED_NODE_NAME = "failure-lab-shared-node"
ABUNDANT_QTY = 1000


def ensure_marker_stock(ctx: ScenarioContext, sku: str) -> str:
    """Idempotent: get-or-create a dedicated fulfillment node and (re-)seed
    abundant stock for `sku` there. Safe to call on every run — resetting
    available_qty back to a large number never breaks anything, since every
    caller only ever reserves qty=1."""
    node = ctx.inventory.get_or_create_node(
        SHARED_NODE_NAME, latitude=0.0, longitude=0.0, capacity_per_day=10_000
    )
    ctx.inventory.upsert_stock(sku, node["id"], available_qty=ABUNDANT_QTY, reorder_threshold=0)
    return node["id"]
