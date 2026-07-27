"""Scenario 4: duplicate order submission (same Idempotency-Key).

Submits the same Idempotency-Key + payload to POST /api/orders three times
in a row (through the gateway, the real customer path), then submits the
same key with a *different* payload once to confirm the conflict case too.

Expected failure behavior: naively, a duplicate submission (a retried
client, a flaky network causing a double-send) would create a second order
and potentially double-charge/double-reserve.

Expected recovery behavior: order-service's `idempotency_keys` table
(docs/data-model.md) makes every repeat of the same key + payload a no-op —
the identical cached response is returned, and no new order is created.
Reusing the same key with a *different* payload is correctly rejected
(409) rather than silently accepted, per docs/product-requirements.md
functional requirement 2.
"""

from __future__ import annotations

from app.clients import ConflictError, new_customer_payload
from app.models import STATUS_FAILED, STATUS_PASSED
from app.scenarios.base import ScenarioContext, ScenarioOutcome

id = "duplicate-order-submit"
name = "Duplicate order submission"
description = "Replay the same Idempotency-Key + payload against POST /api/orders."
category = "idempotency"
mechanism_reference = "docs/data-model.md — idempotency_keys"
expected_failure_behavior = (
    "Without dedup, resubmitting the same request would create a second order."
)
expected_recovery_behavior = (
    "The idempotency-key ledger returns the identical cached response for a repeated "
    "key+payload (no new order), and correctly 409s a key reused with a different payload."
)


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    idempotency_key = f"failure-lab-{id}-{ctx.correlation_id}"
    payload = {
        **new_customer_payload(),
        "items": [{"sku": "SKU-DUPLICATE-SUBMIT-TEST", "qty": 1, "unit_price": 9.99}],
        "currency": "USD",
    }

    responses = [ctx.gateway.create_order(payload, idempotency_key) for _ in range(3)]
    order_ids = {r["id"] for r in responses}

    conflict_detail: str | None = None
    conflict_seen = False
    try:
        ctx.gateway.create_order(
            {**payload, "customer_email": "different@example.invalid"}, idempotency_key
        )
    except ConflictError as exc:
        conflict_seen = True
        conflict_detail = exc.body

    diagnostics = {
        "responses": responses,
        "distinct_order_ids": list(order_ids),
        "conflict_on_different_payload": conflict_seen,
        "conflict_detail": conflict_detail,
    }
    resources = {"order_id": responses[0]["id"], "idempotency_key": idempotency_key}

    if len(order_ids) == 1 and conflict_seen:
        return ScenarioOutcome(
            status=STATUS_PASSED,
            summary=(
                f"All 3 repeats of the same Idempotency-Key returned the same order "
                f"{next(iter(order_ids))}; reusing the key with a different payload was "
                "correctly rejected with 409."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected exactly 1 distinct order id and a 409 conflict on payload mismatch; got "
            f"{len(order_ids)} distinct order id(s), conflict_seen={conflict_seen}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return (
        "Nothing to reset — each run uses a correlation-scoped Idempotency-Key, so a rerun "
        "always starts from a fresh key/order pair."
    )
