import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import OutboxEvent
from event_contracts import EventEnvelope, TraceContext, current_traceparent

PRODUCER_NAME = "fulfillment-orchestrator"


def stage_event(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID | None,
    data: dict[str, Any],
) -> OutboxEvent:
    """Write an outbox row in the caller's current transaction — see
    docs/adrs/0003-transactional-outbox.md. Captures the current span's
    trace context so a later consumer of this event resumes the same
    trace (event_contracts.tracing_setup)."""
    envelope = EventEnvelope(
        event_type=event_type,
        producer=PRODUCER_NAME,
        correlation_id=str(correlation_id),
        causation_id=str(causation_id) if causation_id else None,
        trace_context=TraceContext(traceparent=current_traceparent()),
        data=data,
    )
    row = OutboxEvent(
        id=uuid.UUID(envelope.event_id),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=envelope.model_dump(mode="json"),
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    db.add(row)
    return row
