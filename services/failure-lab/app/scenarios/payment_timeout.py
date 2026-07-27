"""Scenario 2: payment gateway transient timeout, then recovery.

Places a real order containing the payment simulator's "recoverable
transient timeout" marker SKU (services/fulfillment-orchestrator/app/
payment.py's `TRANSIENT_RECOVER_SKU`, which fails attempt 1 and succeeds
from attempt 2 onward — deterministic, not random).

Expected failure behavior: AUTHORIZE_PAYMENT's first attempt raises
PaymentGatewayTimeoutError (retryable); app.retry.retry_with_backoff retries
with exponential backoff + jitter (docs/event-catalog.md "Retry policy").

Expected recovery behavior: the second attempt succeeds, and the saga
proceeds to CONFIRM_SHIPMENT — the order reaches SHIPPED without any
compensation, purely through the existing retry mechanism. This scenario's
terminal PASS status is RECOVERED, not the generic PASSED, since recovery
*is* the thing being demonstrated.
"""

from __future__ import annotations

from app.clients import NotFoundError, new_customer_payload
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_RECOVERED
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until
from app.scenarios.inventory_seed import ensure_marker_stock

TRANSIENT_RECOVER_SKU = "SKU-PAYMENT-TIMEOUT-RECOVER"

id = "payment-timeout"
name = "Payment gateway timeout"
description = "Force a transient timeout on the first authorization attempt."
category = "retry-backoff"
mechanism_reference = "docs/event-catalog.md — Retry policy (consumers)"
expected_failure_behavior = (
    "AUTHORIZE_PAYMENT's first attempt raises a retryable PaymentGatewayTimeoutError."
)
expected_recovery_behavior = (
    "app.retry.retry_with_backoff retries with exponential backoff + jitter; attempt 2 "
    "succeeds and the saga completes normally through CONFIRM_SHIPMENT to SHIPPED."
)


def _order_payload() -> dict:
    return {
        **new_customer_payload(),
        "items": [{"sku": TRANSIENT_RECOVER_SKU, "qty": 1, "unit_price": 24.5}],
        "currency": "USD",
    }


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    ensure_marker_stock(ctx, TRANSIENT_RECOVER_SKU)
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
            status=STATUS_ERROR, summary=str(exc), resources={"order_id": order_id}
        )

    try:
        current_order = ctx.order_service.get_order(order_id)
    except NotFoundError:
        current_order = {}

    diagnostics = {"saga": saga, "order_status": current_order.get("status")}
    resources = {"order_id": order_id}

    if saga["status"] == "COMPLETED" and current_order.get("status") == "SHIPPED":
        return ScenarioOutcome(
            status=STATUS_RECOVERED,
            summary=(
                f"Order {order_id} recovered from a simulated first-attempt gateway timeout "
                "and shipped normally after a retried payment authorization."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected the order to recover and reach SHIPPED; saga status={saga['status']!r}, "
            f"order status={current_order.get('status')!r}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return "Nothing to reset — each run creates a fresh order; no shared state is mutated."
