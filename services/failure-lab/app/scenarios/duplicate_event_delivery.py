"""Scenario 5: duplicate event redelivery (same event_id).

Publishes a synthetic `order.created` envelope (a fresh, made-up order_id
that intentionally has no real row in order-service's database — the same
safe pattern the Phase 4 synthetic generator already uses against these
same real topics, confirmed harmless in RISKS.md #17) directly onto the real
`order.created` topic, then republishes the *exact same envelope* (same
event_id) twice more.

Expected failure behavior: without dedup, redelivery (a consumer restart
mid-batch before committing offsets, a broker-level at-least-once retry)
would reprocess the event and could apply its side effects twice.

Expected recovery behavior: order-service's validator consumer's
`processed_events` ledger (docs/event-catalog.md "Consumer idempotency")
makes every redelivery of the same event_id a pure no-op — the row's
`processed_at` timestamp never changes after the first delivery. Verified
via a small internal read endpoint on order-service (added for this
scenario), not by inference.
"""

from __future__ import annotations

import time

from app.clients import NotFoundError
from app.kafka import publish_order_created_envelope
from app.models import STATUS_ERROR, STATUS_FAILED, STATUS_PASSED
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until

id = "duplicate-event-delivery"
name = "Duplicate event redelivery"
description = "Replay an already-processed event with the same event_id."
category = "idempotency"
mechanism_reference = "docs/event-catalog.md — Consumer idempotency"
expected_failure_behavior = (
    "Without dedup, redelivering the same event_id would reprocess it and could reapply its "
    "side effects a second time."
)
expected_recovery_behavior = (
    "order-service's processed_events ledger makes every redelivery of the same event_id a "
    "no-op; processed_at never changes after the first delivery."
)


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    producer = ctx.producer_factory()
    envelope = publish_order_created_envelope(producer, correlation_id=ctx.correlation_id)
    event_id = envelope.event_id

    def _first_seen() -> dict | None:
        status = ctx.order_service.processed_event_status(event_id)
        return status if status.get("processed") else None

    try:
        first_status = poll_until(
            _first_seen,
            timeout_seconds=ctx.settings.poll_timeout_seconds,
            interval_seconds=ctx.settings.poll_interval_seconds,
            description=f"order-service to record event {event_id} as processed",
        )
    except PollTimeoutError as exc:
        return ScenarioOutcome(
            status=STATUS_ERROR, summary=str(exc), resources={"event_id": event_id}
        )

    first_processed_at = first_status["processed_at"]

    for _ in range(2):
        publish_order_created_envelope(
            producer, correlation_id=ctx.correlation_id, envelope=envelope
        )

    # No new async effect to wait for on a true no-op redelivery — pause
    # briefly to give the (already-idempotent) consumer a chance to touch
    # the row, then assert it didn't.
    time.sleep(min(2.0, ctx.settings.poll_timeout_seconds))
    final_status = ctx.order_service.processed_event_status(event_id)

    diagnostics = {
        "event_id": event_id,
        "order_id": envelope.data["order_id"],
        "first_processed_at": first_processed_at,
        "final_processed_at": final_status["processed_at"],
        "redeliveries_sent": 2,
    }
    resources = {"event_id": event_id, "order_id": envelope.data["order_id"]}

    try:
        # The synthetic order_id has no real row — confirms this scenario
        # never touches real order data.
        ctx.order_service.get_order(envelope.data["order_id"])
        order_exists = True
    except NotFoundError:
        order_exists = False
    diagnostics["synthetic_order_exists"] = order_exists

    if first_processed_at == final_status["processed_at"] and not order_exists:
        return ScenarioOutcome(
            status=STATUS_PASSED,
            summary=(
                f"Event {event_id} was processed once; 2 redeliveries of the identical "
                "envelope were correctly no-op'd (processed_at unchanged)."
            ),
            diagnostics=diagnostics,
            resources=resources,
        )

    return ScenarioOutcome(
        status=STATUS_FAILED,
        summary=(
            f"Expected processed_at to stay {first_processed_at!r} across redeliveries; got "
            f"{final_status['processed_at']!r}"
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return (
        "Nothing to reset — each run publishes a fresh synthetic event_id/order_id pair that "
        "never corresponds to a real order row."
    )
