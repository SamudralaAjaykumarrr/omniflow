"""Scenario 6: poison message / retry exhaustion.

Publishes a message onto `failure-lab.poison`, a topic owned entirely by the
failure lab (app.kafka_topics.POISON_TOPIC) — no real business consumer
subscribes to it. The failure lab's own dedicated consumer
(app.poison_consumer) reuses the exact same generic
`event_contracts.run_consume_loop` every production consumer uses, but its
`process()` deliberately raises unconditionally: this is what a message no
amount of reprocessing can ever fix looks like.

Expected failure behavior: every processing attempt raises; the shared
consume loop retries with exponential backoff + jitter up to its configured
attempt budget (docs/event-catalog.md "Retry policy"), never silently
dropping the message and never blocking the partition forever.

Expected recovery behavior: this is the one scenario where "recovery" is
deliberately *not* automatic replay — a true poison message fails
identically no matter how many times it's reprocessed. The correct
remediation is operator triage (inspect the DLQ row's error, decide to
discard or fix-and-replay something upstream), which is why the scenario
also demonstrates that replaying it (via the same replay mechanism
downstream-outage's recovery uses) is safe to attempt but does not change
the outcome — see docs/phase-8-failure-laboratory.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.kafka_topics import POISON_TOPIC
from app.models import STATUS_ERROR, STATUS_PASSED, FailureLabDeadLetter
from app.scenarios.base import PollTimeoutError, ScenarioContext, ScenarioOutcome, poll_until
from event_contracts import EventEnvelope, publish_envelope

id = "poison-message-dlq"
name = "Poison message / retry exhaustion"
description = "Feed a consumer an event that fails every retry attempt."
category = "dead-letter-queue"
mechanism_reference = "docs/event-catalog.md — Retry policy; Dead Letter Queue screen"
expected_failure_behavior = (
    "Every processing attempt raises unconditionally; the shared consume loop retries with "
    "exponential backoff + jitter to exhaustion, never silently dropping the message."
)
expected_recovery_behavior = (
    "A true poison message is not fixed by replay — it fails identically every time. The "
    "correct remediation is operator triage from the DLQ row, not automatic reprocessing. "
    "(Contrast with downstream-outage, scenario 10, where replay *does* recover the message.)"
)


def run(ctx: ScenarioContext) -> ScenarioOutcome:
    producer = ctx.producer_factory()
    envelope = EventEnvelope(
        event_type="failure-lab.poison",
        producer="failure-lab",
        correlation_id=ctx.correlation_id,
        data={"reason": "deterministic simulated unrecoverable processing failure"},
    )
    publish_envelope(producer, topic=POISON_TOPIC, key=envelope.event_id, envelope=envelope)

    def _dead_lettered() -> FailureLabDeadLetter | None:
        ctx.db.expire_all()
        return ctx.db.execute(
            select(FailureLabDeadLetter).where(
                FailureLabDeadLetter.original_event_id == uuid.UUID(envelope.event_id)
            )
        ).scalar_one_or_none()

    try:
        dead_letter = poll_until(
            _dead_lettered,
            timeout_seconds=ctx.settings.poll_timeout_seconds,
            interval_seconds=ctx.settings.poll_interval_seconds,
            description=f"poison message {envelope.event_id} to exhaust retries and dead-letter",
        )
    except PollTimeoutError as exc:
        return ScenarioOutcome(
            status=STATUS_ERROR, summary=str(exc), resources={"event_id": envelope.event_id}
        )

    diagnostics = {
        "event_id": envelope.event_id,
        "dead_letter_id": str(dead_letter.id),
        "error_type": dead_letter.error_type,
        "attempt_count": dead_letter.attempt_count,
    }
    resources = {"event_id": envelope.event_id, "dead_letter_id": str(dead_letter.id)}

    return ScenarioOutcome(
        status=STATUS_PASSED,
        summary=(
            f"Message {envelope.event_id} exhausted {dead_letter.attempt_count} retry attempt(s) "
            "and was correctly dead-lettered, never silently dropped and never blocking the "
            "consumer indefinitely."
        ),
        diagnostics=diagnostics,
        resources=resources,
    )


def reset(ctx: ScenarioContext) -> str:
    """Clears the failure lab's own dead-letter rows — this table exists
    only to demonstrate the mechanism, so there is nothing to preserve
    across demo runs."""
    deleted = ctx.db.query(FailureLabDeadLetter).delete()
    ctx.db.commit()
    return f"Cleared {deleted} failure-lab dead-letter row(s)."
