"""Scenario 8: late-arriving event.

Publishes a well-formed `order.shipped` envelope (synthetic order_id, safe
per the same pattern as duplicate-event-delivery/RISKS.md #17) whose
business `occurred_at` trails real time by well more than Silver's lateness
threshold (`LATE_THRESHOLD_SECONDS = 600`, i.e. 10 minutes —
services/data-platform/app/silver.py). `order.shipped` has zero
transactional consumers (only Bronze/Silver observe it), so this is safe
regardless of whether the data platform is running.

Expected failure behavior: naively, a late event folded into an
already-closed aggregation window would silently skew that window's
numbers without anyone noticing the input was late.

Expected recovery behavior: Silver's lateness check
(`ingested_at - occurred_at > LATE_THRESHOLD_SECONDS`) routes it to the
`late_events` side path (`dropped_reason: "late"`) instead of Silver proper
— visible and quarantined, not silently blended in.

Like malformed-kafka-record, the deterministic, always-available part is
the publish itself; whether it lands in `late_events` depends on the data
platform being up, so that verification is a best-effort diagnostic, not
the pass/fail gate.
"""

from __future__ import annotations

from datetime import timedelta

from app.kafka import publish_late_order_shipped_envelope
from app.models import STATUS_PASSED
from app.scenarios.base import ScenarioContext, ScenarioOutcome

# Comfortably past Silver's 600-second (10 minute) LATE_THRESHOLD_SECONDS —
# see services/data-platform/app/silver.py.
LATENESS = timedelta(minutes=45)

id = "late-event-arrival"
name = "Late-arriving event"
description = "Publish an event whose occurred_at trails real time well past the dedup watermark."
category = "data-quality"
mechanism_reference = "docs/data-pipeline.md — Watermarks and late data"
expected_failure_behavior = (
    "A late event folded into an already-closed aggregation window would silently skew that "
    "window without anyone noticing the input was late."
)
expected_recovery_behavior = (
    "Silver's lateness check routes it to late_events (dropped_reason: 'late') instead of "
    "Silver proper — visible and quarantined, never silently blended into on-time data."
)


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    producer = ctx.producer_factory()
    envelope = publish_late_order_shipped_envelope(
        producer, correlation_id=ctx.correlation_id, lateness=LATENESS
    )

    diagnostics = {
        "event_id": envelope.event_id,
        "order_id": envelope.data["order_id"],
        "occurred_at": envelope.occurred_at.isoformat(),
        "lateness_minutes": LATENESS.total_seconds() / 60,
        "note": (
            "late_events verification is best-effort and requires the data-platform stack "
            "(spark-silver) to be running — see make inspect-late-events."
        ),
    }
    resources = {"event_id": envelope.event_id, "order_id": envelope.data["order_id"]}

    return ScenarioOutcome(
        status=STATUS_PASSED,
        summary=(
            f"Published order.shipped for synthetic order {envelope.data['order_id']} with "
            f"occurred_at {LATENESS} in the past. Run `make inspect-late-events` to see it "
            "quarantined if the data platform is up."
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return (
        "Nothing to reset — this scenario only ever publishes new, disposable synthetic events; "
        "it never mutates shared service state."
    )
