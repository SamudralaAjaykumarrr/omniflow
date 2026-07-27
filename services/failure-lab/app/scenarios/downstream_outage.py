"""Scenario 10: downstream service outage.

Enables inventory-service's simulated-outage fault injection (a new
internal endpoint added for this phase — every non-internal route returns
503 while it's active; it self-clears after a bounded duration even if
nobody calls disable, so a forgotten trigger can never permanently wedge the
shared dev stack), places a real order while the "outage" is active, then
disables it and recovers the resulting dead letter via replay.

Expected failure behavior: the API Gateway's own real `/readyz` (which
live-pings order-service and inventory-service's `/healthz`) reports 503
`not_ready` — a genuine, observable consequence, not a mocked one. A saga
started for an order placed during the outage fails to reserve inventory
(`InventoryServiceClient.list_nodes()`/`reserve()` raise on the 503), and
after Kafka's generic retry/backoff exhausts, the order.validated event is
dead-lettered into fulfillment-orchestrator's real `dead_letter_events`
table — the same DLQ the dashboard's Dead Letter Queue screen reads from.

Expected recovery behavior: once the outage is disabled, replaying the
dead-lettered event (`POST /dead-letters/{id}/replay`, added for this
phase — the same replay mechanism `app.replay`'s CLI already used, now also
reachable over HTTP) redelivers `order.validated`; this time inventory-service
is healthy, the saga completes normally, and the order reaches SHIPPED.
Unlike poison-message-dlq, this failure genuinely is transient — replay is
the correct fix, not just a safe no-op.
"""

from __future__ import annotations

from app.clients import NotFoundError, new_customer_payload
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_RECOVERED
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until
from app.scenarios.inventory_seed import ensure_marker_stock

id = "downstream-outage"
name = "Downstream service outage"
description = "Stop inventory-service while orders are mid-saga."
category = "resilience"
mechanism_reference = "docs/architecture.md — Service boundaries"
expected_failure_behavior = (
    "The gateway's /readyz reports 503 (a real, live check of downstream health); a saga "
    "started during the outage cannot reserve inventory, and after Kafka-level retries exhaust, "
    "the order.validated event is dead-lettered."
)
expected_recovery_behavior = (
    "Once the simulated outage is disabled, replaying the dead-lettered event redelivers "
    "order.validated; the saga completes normally this time and the order reaches SHIPPED."
)

OUTAGE_DURATION_SECONDS = 20
TEST_SKU = "SKU-DOWNSTREAM-OUTAGE-TEST"


def _order_payload() -> dict:
    return {
        **new_customer_payload(),
        "items": [{"sku": TEST_SKU, "qty": 1, "unit_price": 12.0}],
        "currency": "USD",
    }


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    diagnostics: dict = {}
    # Must seed stock *before* the outage — inventory-service refuses every
    # request, seeding included, once it's "down".
    ensure_marker_stock(ctx, TEST_SKU)
    ctx.inventory.enable_outage(OUTAGE_DURATION_SECONDS)
    try:
        gateway_status_code, gateway_body = ctx.gateway.readyz()
        diagnostics["gateway_readyz_during_outage"] = {
            "status_code": gateway_status_code,
            "body": gateway_body,
        }

        idempotency_key = f"failure-lab-{id}-{ctx.correlation_id}"
        order = ctx.gateway.create_order(_order_payload(), idempotency_key)
        order_id = order["id"]
        resources = {"order_id": order_id}

        def _dead_lettered() -> dict | None:
            # DeadLetterEvent.payload is the flat original envelope itself
            # (app/consumer.py's dead_letter(): `payload=envelope.model_dump(...)`) —
            # not wrapped in an "original_event" key (that wrapping only
            # happens in the *separate* deadletter.event Kafka message's
            # own data, not this DB column). A real bug found running this
            # scenario against a live stack: the dead letter was created
            # correctly and immediately, but this matcher never found it.
            for dl in ctx.orchestrator.list_dead_letters(unreplayed_only=True):
                if dl.get("payload", {}).get("data", {}).get("order_id") == order_id:
                    return dl
            return None

        try:
            dead_letter = poll_until(
                _dead_lettered,
                timeout_seconds=ctx.settings.poll_timeout_seconds,
                interval_seconds=ctx.settings.poll_interval_seconds,
                description=f"order {order_id}'s order.validated to dead-letter during the outage",
            )
        except PollTimeoutError as exc:
            diagnostics["error"] = str(exc)
            return ScenarioOutcome(
                status=STATUS_ERROR, summary=str(exc), diagnostics=diagnostics, resources=resources
            )
        diagnostics["dead_letter_id"] = dead_letter["id"]
    finally:
        ctx.inventory.disable_outage()

    gateway_status_after, gateway_body_after = ctx.gateway.readyz()
    diagnostics["gateway_readyz_after_disable"] = {
        "status_code": gateway_status_after,
        "body": gateway_body_after,
    }

    ctx.orchestrator.replay_dead_letter(dead_letter["id"])

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
            description=f"order {order_id}'s saga to complete after replay",
        )
    except PollTimeoutError as exc:
        diagnostics["error_after_replay"] = str(exc)
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
                f"Order {order_id} dead-lettered while inventory-service was in a simulated "
                "outage (gateway /readyz correctly reported 503); after the outage cleared, "
                "replaying the dead letter recovered the order to SHIPPED."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected the replayed saga to reach COMPLETED/SHIPPED; got saga status="
            f"{final_saga['status']!r}, order status={current_order.get('status')!r}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    """Force-disable the simulated outage regardless of the automatic
    timeout — a safety valve if a run was interrupted mid-scenario."""
    status = ctx.inventory.disable_outage()
    return f"Simulated outage force-disabled (was: {status})."
