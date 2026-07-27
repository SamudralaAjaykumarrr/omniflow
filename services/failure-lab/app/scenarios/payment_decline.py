"""Scenario 1: payment hard decline.

Places a real order (through the API Gateway, the same path a real customer
uses) containing the payment simulator's decline marker SKU
(services/fulfillment-orchestrator/app/payment.py's `DECLINE_SKU`), then
polls the real saga until it reaches a terminal state.

Expected failure behavior: the saga's AUTHORIZE_PAYMENT step raises
PaymentDeclinedError (not retryable — a hard business rejection, not a
transient fault), which sends the saga straight to
COMPENSATE_RELEASE_INVENTORY: the reservation made moments earlier is
released and the order transitions to FAILED. No retry is attempted for a
hard decline (docs/architecture.md "Saga compensation (failure path)").

Expected recovery behavior: there is nothing to "recover" from a hard
decline — the compensation *is* the correct, complete outcome. The scenario
PASSes when the order reaches FAILED with its inventory reservation
released, not when the order somehow succeeds.
"""

from __future__ import annotations

from app.clients import NotFoundError
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_PASSED
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until
from app.scenarios.inventory_seed import ensure_marker_stock

DECLINE_SKU = "SKU-PAYMENT-DECLINE"

id = "payment-decline"
name = "Payment hard decline"
description = "Force the deterministic payment simulator to decline an in-flight order."
category = "saga-compensation"
mechanism_reference = "docs/architecture.md — Saga compensation (failure path)"
expected_failure_behavior = (
    "AUTHORIZE_PAYMENT raises a non-retryable PaymentDeclinedError; the saga skips retry "
    "entirely and moves straight to COMPENSATE_RELEASE_INVENTORY."
)
expected_recovery_behavior = (
    "The saga's compensation releases the reservation and transitions the order to FAILED — "
    "this *is* the correct terminal state for a hard decline, not something to retry past."
)


def _order_payload() -> dict:
    from app.clients import new_customer_payload

    return {
        **new_customer_payload(),
        "items": [{"sku": DECLINE_SKU, "qty": 1, "unit_price": 19.99}],
        "currency": "USD",
    }


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    ensure_marker_stock(ctx, DECLINE_SKU)
    idempotency_key = f"failure-lab-{id}-{ctx.correlation_id}"
    order = ctx.gateway.create_order(_order_payload(), idempotency_key)
    order_id = order["id"]

    def _saga_terminal() -> dict | None:
        saga = ctx.orchestrator.get_saga_for_order(order_id)
        if saga is not None and saga["status"] in ("COMPLETED", "FAILED"):
            return saga
        return None

    try:
        saga = poll_until(
            _saga_terminal,
            timeout_seconds=ctx.settings.poll_timeout_seconds,
            interval_seconds=ctx.settings.poll_interval_seconds,
            description=f"saga for order {order_id} to reach a terminal state",
        )
    except PollTimeoutError as exc:
        return ScenarioOutcome(
            status=STATUS_ERROR,
            summary=str(exc),
            resources={"order_id": order_id},
        )

    try:
        current_order = ctx.order_service.get_order(order_id)
    except NotFoundError:
        current_order = {}

    diagnostics = {"saga": saga, "order_status": current_order.get("status")}
    resources = {"order_id": order_id}

    # A reservation actually being made (then released) is what distinguishes
    # "failed via payment compensation" (what this scenario means to prove)
    # from "failed because no node had stock" (STEP_FAIL_NO_INVENTORY) —
    # both leave order/saga at the same FAILED status otherwise.
    reservation_was_made = bool(saga["context"].get("reservation_ids"))

    if (
        saga["status"] == "FAILED"
        and current_order.get("status") == "FAILED"
        and reservation_was_made
    ):
        return ScenarioOutcome(
            status=STATUS_PASSED,
            summary=(
                f"Order {order_id} correctly failed via saga compensation after a simulated "
                "hard payment decline; inventory reservation released."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected the order to reach FAILED via compensation; saga status="
            f"{saga['status']!r}, order status={current_order.get('status')!r}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return "Nothing to reset — each run creates a fresh order; no shared state is mutated."
