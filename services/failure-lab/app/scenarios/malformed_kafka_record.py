"""Scenario 7: malformed Kafka record.

Publishes a raw, deliberately non-JSON byte string directly onto the real
`inventory.low` topic (bypassing `publish_envelope`, which requires a valid
`EventEnvelope`) — `inventory.low` is a real event-catalog topic with zero
transactional consumers (only order-service's validator consumes
`order.created`; only fulfillment-orchestrator's saga consumer consumes
`order.validated`/`order.cancelled` — grepped to confirm before choosing
this topic), so this can never crash or wedge a real business consumer, only
ever be observed by the data platform's Bronze ingestion.

Expected failure behavior: a naive Bronze sink would either crash the
Structured Streaming query or silently drop the record.

Expected recovery behavior: Bronze's malformed-JSON quarantine
(`transform_to_bronze_rejects`, added in the streaming-data-platform
hardening pass — docs/phase-6-streaming-data-platform.md) routes any record
that fails JSON parsing to the `bronze_rejects` MinIO prefix instead,
keeping the stream itself healthy.

This scenario's PASS condition only requires the publish itself to succeed
— that is the deterministic, always-available part this service controls
directly. Whether the record actually shows up in `bronze_rejects` depends
on the data platform (Spark/MinIO) being up, which is optional in a
lighter-weight `docker compose up` subset; that check is best-effort and
surfaced as a diagnostic, never as the pass/fail gate (see
docs/phase-8-failure-laboratory.md "Determinism and timing").
"""

from __future__ import annotations

import uuid

from app.kafka import publish_malformed_record
from app.models import STATUS_PASSED
from app.scenarios.base import ScenarioContext, ScenarioOutcome

TARGET_TOPIC = "inventory.low"

id = "malformed-kafka-record"
name = "Malformed Kafka record"
description = "Publish a non-JSON / non-envelope-shaped raw record onto a real topic."
category = "data-quality"
mechanism_reference = "docs/data-pipeline.md — Bronze, malformed-event handling"
expected_failure_behavior = (
    "A naive Bronze sink would crash the streaming query or silently drop an unparseable record."
)
expected_recovery_behavior = (
    "Bronze's malformed-JSON quarantine routes the record to bronze_rejects instead, keeping "
    "the stream healthy — never written to Bronze itself as if it were valid."
)


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    producer = ctx.producer_factory()
    key = str(uuid.uuid4())
    raw_bytes = b"{not-valid-json::: this is a deliberately malformed Kafka record body"

    publish_malformed_record(producer, topic=TARGET_TOPIC, key=key, raw_bytes=raw_bytes)

    diagnostics = {
        "topic": TARGET_TOPIC,
        "key": key,
        "raw_bytes_preview": raw_bytes.decode("utf-8", errors="replace"),
        "note": (
            "Bronze quarantine verification (bronze_rejects) is best-effort and requires the "
            "data-platform stack (spark-bronze) to be running — see make inspect-bronze-rejects."
        ),
    }
    resources = {"topic": TARGET_TOPIC, "key": key}

    return ScenarioOutcome(
        status=STATUS_PASSED,
        summary=(
            f"Published a deliberately malformed record to {TARGET_TOPIC} (zero transactional "
            "consumers — confirmed safe). Run `make inspect-bronze-rejects` to see it quarantined "
            "in bronze_rejects if the data platform is up."
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    return (
        "Nothing to reset — this scenario only ever publishes new, disposable records; it never "
        "mutates shared service state."
    )
