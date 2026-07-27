"""Scenario 3: concurrent reservation race for the last unit of a SKU.

Seeds a dedicated fulfillment node + SKU to exactly 1 available unit, then
fires N concurrent POST /reservations for qty=1 directly at
inventory-service (bypassing the saga entirely — this exercises the
row-level lock itself, not the whole order flow).

Expected failure behavior: N-1 of the concurrent requests are rejected with
409 Insufficient stock — `SELECT ... FOR UPDATE` (ADR 0002) serializes the
concurrent transactions against the same (sku, node_id) row, so only one can
see and consume the unit.

Expected recovery behavior: there is no failure to recover from — rejecting
every over-the-limit request *is* the correct, safe behavior (never
oversell). PASS means exactly one reservation succeeded and final
available_qty is 0, never negative.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from app.clients import ConflictError
from app.models import STATUS_FAILED, STATUS_PASSED
from app.scenarios.base import ScenarioContext, ScenarioOutcome

NODE_NAME = "failure-lab-race-node"
SKU = "FAILURE-LAB-RACE-SKU"
CONCURRENCY = 8

id = "inventory-oversell-race"
name = "Concurrent reservation race"
description = "Fire N concurrent reservation requests for the last unit of one SKU/node."
category = "concurrency-control"
mechanism_reference = "ADR 0002 — Inventory concurrency control"
expected_failure_behavior = (
    "N-1 of N concurrent reservation requests for the same last unit are rejected with "
    "409 Insufficient stock."
)
expected_recovery_behavior = (
    "Nothing to recover — rejecting every over-the-limit concurrent request is the correct, "
    "safe outcome. Row-level locking (SELECT ... FOR UPDATE) serializes the race so exactly "
    "one request wins, never zero and never more than one."
)


def _ensure_seeded(ctx: ScenarioContext) -> str:
    node = ctx.inventory.get_or_create_node(
        NODE_NAME, latitude=0.0, longitude=0.0, capacity_per_day=1000
    )
    node_id = node["id"]
    # Release any reservation a previous run left ACTIVE (should be none —
    # every reservation attempt here is resolved synchronously — but this
    # keeps the scenario safe to rerun even after an interrupted prior run.
    ctx.inventory.upsert_stock(SKU, node_id, available_qty=1, reorder_threshold=0)
    return node_id


def _attempt_reservation(ctx: ScenarioContext, node_id: str) -> dict:
    order_id = str(uuid.uuid4())
    try:
        resp = ctx.inventory.reserve(
            order_id=order_id,
            sku=SKU,
            node_id=node_id,
            qty=1,
            correlation_id=ctx.correlation_id,
        )
        return {"order_id": order_id, "status_code": resp.status_code, "outcome": "reserved"}
    except ConflictError as exc:
        return {
            "order_id": order_id,
            "status_code": exc.status_code,
            "outcome": "rejected",
            "detail": exc.body,
        }


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    node_id = _ensure_seeded(ctx)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(lambda _: _attempt_reservation(ctx, node_id), range(CONCURRENCY)))

    reserved = [r for r in results if r["outcome"] == "reserved"]
    rejected = [r for r in results if r["outcome"] == "rejected"]
    final_stock = ctx.inventory.get_stock(SKU, node_id)

    diagnostics = {
        "concurrency": CONCURRENCY,
        "reserved_count": len(reserved),
        "rejected_count": len(rejected),
        "final_available_qty": final_stock["available_qty"],
        "results": results,
    }
    resources = {"node_id": node_id, "sku": SKU}

    if len(reserved) == 1 and final_stock["available_qty"] == 0:
        return ScenarioOutcome(
            status=STATUS_PASSED,
            summary=(
                f"Exactly 1 of {CONCURRENCY} concurrent reservation attempts for the last unit "
                f"succeeded; the other {len(rejected)} were correctly rejected. No oversell."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected exactly 1 winner and available_qty=0; got {len(reserved)} winner(s) and "
            f"available_qty={final_stock['available_qty']}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    """Release every ACTIVE reservation this scenario's SKU/node might still
    hold (e.g. from a run interrupted mid-flight) and re-seed available_qty
    back to 1, so the next run starts from the same known-good state."""
    node = ctx.inventory.get_or_create_node(
        NODE_NAME, latitude=0.0, longitude=0.0, capacity_per_day=1000
    )
    node_id = node["id"]
    ctx.inventory.upsert_stock(SKU, node_id, available_qty=1, reorder_threshold=0)
    return f"Re-seeded {SKU} at node {node_id} to available_qty=1."
