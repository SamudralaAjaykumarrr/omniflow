"""Scenario 9: orchestrator crash mid-saga.

Places a real order containing the saga engine's crash-simulation marker SKU
(services/fulfillment-orchestrator/app/saga.py's `CRASH_SIMULATION_SKU`).
The *real*, automatic order.validated consumer picks it up and runs the saga
exactly as it would for any order — but `advance_saga` pauses itself
immediately after SELECT_AND_RESERVE commits (reservation already made,
context already holds the chosen node/reservation ids) and returns without
raising, without dead-lettering, and without advancing further. This is
deliberately data-driven (keyed off the marker SKU already present in the
order, not off timing of an admin call racing the live consumer) — it
leaves the exact on-disk state a real crash between those two steps would:
a `saga_instances` row stuck `status=RUNNING` at a step it never returns
from on its own.

Expected failure behavior: the saga simply stops advancing — no error, no
DLQ entry, no order-status regression. Left alone, it would sit there
forever (this narrow gap is documented as accepted in RISKS.md #11).

Expected recovery behavior: a new fulfillment-orchestrator-consumer process
starting up calls `resume_incomplete_sagas`, which re-enters `advance_saga`
for every row still RUNNING, picking up at `current_step` rather than
restarting the saga from scratch. This scenario's "resume" step calls the
identical `advance_saga` function through a dedicated on-demand endpoint
(added for this phase) rather than requiring an actual container restart —
same recovery code path, deterministic, no Docker control needed.
"""

from __future__ import annotations

from app.clients import NotFoundError, new_customer_payload
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_RECOVERED
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until
from app.scenarios.inventory_seed import ensure_marker_stock

CRASH_SIMULATION_SKU = "SKU-SAGA-CRASH-SIMULATION"

id = "saga-crash-resume"
name = "Orchestrator crash mid-saga"
description = "Kill the orchestrator consumer process between two saga steps."
category = "saga-resumability"
mechanism_reference = "RISKS.md #11 — Saga resume gap"
expected_failure_behavior = (
    "The saga pauses right after SELECT_AND_RESERVE commits (reservation already made) and "
    "never advances on its own — no error, no DLQ entry, just a stuck RUNNING row."
)
expected_recovery_behavior = (
    "advance_saga, called again for this one saga (the same function resume_incomplete_sagas "
    "calls for every RUNNING row at real process startup), picks up exactly where it left off "
    "and drives the order to SHIPPED."
)


def _order_payload() -> dict:
    return {
        **new_customer_payload(),
        "items": [{"sku": CRASH_SIMULATION_SKU, "qty": 1, "unit_price": 15.0}],
        "currency": "USD",
    }


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    ensure_marker_stock(ctx, CRASH_SIMULATION_SKU)
    idempotency_key = f"failure-lab-{id}-{ctx.correlation_id}"
    order = ctx.gateway.create_order(_order_payload(), idempotency_key)
    order_id = order["id"]

    def _saga_paused() -> dict | None:
        saga = ctx.orchestrator.get_saga_for_order(order_id)
        if (
            saga is not None
            and saga["status"] == "RUNNING"
            and saga["context"].get("_crash_simulated")
        ):
            return saga
        return None

    try:
        paused_saga = poll_until(
            _saga_paused,
            timeout_seconds=ctx.settings.poll_timeout_seconds,
            interval_seconds=ctx.settings.poll_interval_seconds,
            description=f"saga for order {order_id} to pause mid-saga (simulated crash)",
        )
    except PollTimeoutError as exc:
        return ScenarioOutcome(
            status=STATUS_ERROR, summary=str(exc), resources={"order_id": order_id}
        )

    resources = {"order_id": order_id}
    diagnostics: dict = {"paused_saga": paused_saga}

    resumed_saga = ctx.orchestrator.resume_saga(order_id)
    diagnostics["resumed_saga_immediate_response"] = resumed_saga

    def _saga_terminal() -> dict | None:
        saga = ctx.orchestrator.get_saga_for_order(order_id)
        if saga is not None and saga["status"] in ("COMPLETED", "FAILED"):
            return saga
        return None

    try:
        final_saga = poll_until(
            _saga_terminal,
            timeout_seconds=ctx.settings.poll_timeout_seconds,
            interval_seconds=ctx.settings.poll_interval_seconds,
            description=f"resumed saga for order {order_id} to reach a terminal state",
        )
    except PollTimeoutError as exc:
        diagnostics["error_after_resume"] = str(exc)
        return ScenarioOutcome(
            status=STATUS_ERROR, summary=str(exc), diagnostics=diagnostics, resources=resources
        )

    try:
        current_order = ctx.order_service.get_order(order_id)
    except NotFoundError:
        current_order = {}
    diagnostics["final_saga"] = final_saga
    diagnostics["order_status"] = current_order.get("status")

    if final_saga["status"] == "COMPLETED" and current_order.get("status") == "SHIPPED":
        return ScenarioOutcome(
            status=STATUS_RECOVERED,
            summary=(
                f"Order {order_id}'s saga paused mid-flight (simulated crash right after "
                "SELECT_AND_RESERVE), then resumed via the real resume_incomplete_sagas code "
                "path and completed normally to SHIPPED."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected the resumed saga to reach COMPLETED/SHIPPED; got saga status="
            f"{final_saga['status']!r}, order status={current_order.get('status')!r}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return "Nothing to reset — each run creates a fresh order; no shared state is mutated."
